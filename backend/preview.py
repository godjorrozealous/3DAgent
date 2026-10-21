"""文档预览代理：统一 PDF / Word / WPS 的弹窗内展示。

历史关联(知识库)答案中的来源文件链接指向 KB 文件服务器。浏览器只能内嵌 PDF，
Word/WPS 会触发静默下载。本代理在后端取文件：
- PDF           → 原样透传(inline)
- .doc/.docx/.wps → LibreOffice(soffice) 转 PDF(磁盘缓存，同 URL 只转一次)后 inline 返回
- 无 soffice / 转换失败 / 取数失败 → 返回带「下载原始文件」出口的 HTML 提示页
安全：仅允许 http/https 链接。
"""
import asyncio
import hashlib
import logging
import os
import re
import shutil
import subprocess
import threading
from pathlib import Path
from urllib.parse import unquote, urlsplit

import httpx
from fastapi import APIRouter, Response
from fastapi.responses import HTMLResponse

logger = logging.getLogger(__name__)

router = APIRouter()

CACHE_DIR = Path(__file__).resolve().parent / "data" / "preview_cache"
WORD_EXTS = {".doc", ".docx", ".wps"}
WORD_CONTENT_TYPES = (
    "application/msword",
    "application/vnd.openxmlformats-officedocument.wordprocessingml",
    "application/octet-stream",  # KB 对 .wps 返回此类型，需结合文件名判断
)
_FETCH_TIMEOUT = httpx.Timeout(connect=10, read=60, write=10, pool=10)
_CONVERT_TIMEOUT = 120

# soffice 多实例并发会抢用户配置锁，串行化转换
_convert_lock = threading.Lock()


class FetchError(Exception):
    """源文件获取失败。"""


# 安装包内置的 LibreOffice 便携版目录（构建时解包，解压即用、无需 root）
_BUNDLED_LO_DIR = Path(__file__).resolve().parent.parent / "libreoffice"


def _soffice() -> str | None:
    """soffice 解析顺序：SOFFICE_PATH 环境变量 → 安装包内置便携版 → 系统 PATH。"""
    env = os.getenv("SOFFICE_PATH")
    if env and Path(env).exists():
        return env
    bundled = sorted(_BUNDLED_LO_DIR.glob("opt/libreoffice*/program/soffice"))
    if bundled:
        return str(bundled[0])
    return shutil.which("soffice")


async def _fetch_bytes(url: str) -> tuple[int, dict, bytes]:
    """GET url，返回 (状态码, 响应头, 内容)。网络异常抛 FetchError。"""
    try:
        async with httpx.AsyncClient(timeout=_FETCH_TIMEOUT, follow_redirects=True) as c:
            resp = await c.get(url)
            return resp.status_code, dict(resp.headers), resp.content
    except httpx.HTTPError as e:
        raise FetchError(str(e)) from e


def _filename_ext(headers: dict) -> str:
    """从 Content-Disposition 文件名取扩展名（小写，含点），取不到返回 ''。"""
    disp = headers.get("content-disposition", "")
    m = re.search(r"filename\*=UTF-8''([^;]+)", disp) or re.search(r'filename="?([^";]+)', disp)
    if not m:
        return ""
    return Path(unquote(m.group(1))).suffix.lower()


def _is_word(headers: dict) -> bool:
    ct = headers.get("content-type", "")
    ext = _filename_ext(headers)
    if ext in WORD_EXTS:
        return True
    return any(wct in ct for wct in WORD_CONTENT_TYPES[:2])  # 无文件名时仅凭精确 Word 类型


async def _convert_to_pdf(data: bytes, ext: str, key: str) -> Path | None:
    """Word/WPS 字节流转 PDF，命中缓存直接返回；无 soffice 或转换失败返回 None。"""
    cached = CACHE_DIR / f"{key}.pdf"
    if cached.exists():
        return cached
    soffice = _soffice()
    if not soffice:
        return None
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    src = CACHE_DIR / f"{key}{ext}"
    src.write_bytes(data)

    def _run() -> subprocess.CompletedProcess:
        with _convert_lock:
            # 独立用户配置目录：避免 HOME 不可写/多实例抢锁导致 headless 转换失败
            return subprocess.run(
                [soffice, "--headless", "-env:UserInstallation=file:///tmp/lo_preview_profile",
                 "--convert-to", "pdf", "--outdir", str(CACHE_DIR), str(src)],
                timeout=_CONVERT_TIMEOUT, capture_output=True,
            )

    try:
        proc = await asyncio.to_thread(_run)
    except (subprocess.TimeoutExpired, OSError) as e:
        logger.warning("soffice 转换异常(%s): %s", src.name, e)
        src.unlink(missing_ok=True)
        return None
    # soffice 输出文件名 = 输入文件名主干 + .pdf
    if cached.exists():
        src.unlink(missing_ok=True)
        return cached
    logger.warning(
        "soffice 转换失败 rc=%s stderr=%s",
        proc.returncode, proc.stderr.decode(errors="replace")[-500:],
    )
    src.unlink(missing_ok=True)
    return None


def _fallback_html(message: str, url: str) -> HTMLResponse:
    body = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>无法预览</title>
<style>
  body{{font-family:sans-serif;display:flex;flex-direction:column;align-items:center;
       justify-content:center;height:100vh;margin:0;background:#1e1e2e;color:#cbd5e1}}
  a{{color:#a78bfa;margin-top:16px;padding:8px 20px;border:1px solid #a78bfa;
     border-radius:8px;text-decoration:none}}
  a:hover{{background:#a78bfa;color:#1e1e2e}}
</style></head>
<body><p>{message}</p><a href="{url}" target="_blank">下载原始文件查看</a></body></html>"""
    return HTMLResponse(body)


@router.get("/api/file-preview")
async def file_preview(url: str) -> Response:
    if urlsplit(url).scheme not in ("http", "https"):
        return Response("仅允许 http/https 链接", status_code=400)

    # KB 文件服务器 /reports/{id}/raw 直接返回文件本体，优先探测
    candidates = [url] if url.rstrip("/").endswith("/raw") else [url.rstrip("/") + "/raw", url]
    status, headers, data = 0, {}, b""
    try:
        for cand in candidates:
            status, headers, data = await _fetch_bytes(cand)
            if status == 200:
                break
    except FetchError:
        return _fallback_html("来源文件获取失败（知识库服务不可达或超时）", url)
    if status != 200:
        return _fallback_html(f"来源文件不存在或不可用（HTTP {status}）", url)

    ct = headers.get("content-type", "")
    if "application/pdf" in ct:
        return Response(data, media_type="application/pdf",
                        headers={"Content-Disposition": "inline"})

    if _is_word(headers):
        ext = _filename_ext(headers) or ".doc"
        key = hashlib.sha1(url.encode()).hexdigest()
        pdf = await _convert_to_pdf(data, ext, key)
        if pdf is not None:
            return Response(pdf.read_bytes(), media_type="application/pdf",
                            headers={"Content-Disposition": "inline"})
        tip = "服务器未安装 LibreOffice，" if not _soffice() else "文档转换失败，"
        return _fallback_html(f"该文件为 Word/WPS 格式，{tip}暂不支持在线预览", url)

    # 其他格式：同样给提示页，避免 iframe 静默触发下载
    return _fallback_html("该文件格式暂不支持在线预览", url)
