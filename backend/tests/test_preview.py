"""预览代理测试：PDF 透传 / Word 转换 / 无 soffice 兜底 / 非法链接拒绝。"""
import pytest
from fastapi.testclient import TestClient

import main
import preview


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(preview, "CACHE_DIR", tmp_path)
    return TestClient(main.app)


def _fake_fetch_pdf(monkeypatch):
    async def fake(url: str):
        return 200, {
            "content-type": "application/pdf",
            "content-disposition": "inline; filename*=UTF-8''a.pdf",
        }, b"%PDF-1.4 fake"
    monkeypatch.setattr(preview, "_fetch_bytes", fake)


def test_reject_non_http(client):
    r = client.get("/api/file-preview", params={"url": "file:///etc/passwd"})
    assert r.status_code == 400


def test_pdf_passthrough(client, monkeypatch):
    _fake_fetch_pdf(monkeypatch)
    r = client.get("/api/file-preview", params={"url": "http://kb:8503/reports/abc"})
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("application/pdf")
    assert r.content == b"%PDF-1.4 fake"


def test_word_converted_to_pdf(client, monkeypatch):
    async def fake(url: str):
        return 200, {
            "content-type": "application/msword",
            "content-disposition": "attachment; filename*=UTF-8''report.doc",
        }, b"doc-bytes"
    monkeypatch.setattr(preview, "_fetch_bytes", fake)
    monkeypatch.setattr(preview, "_soffice", lambda: "/usr/bin/soffice")

    async def fake_convert(data: bytes, ext: str, key: str):
        out = preview.CACHE_DIR / f"{key}.pdf"
        out.write_bytes(b"%PDF-1.4 converted")
        return out
    monkeypatch.setattr(preview, "_convert_to_pdf", fake_convert)

    r = client.get("/api/file-preview", params={"url": "http://kb:8503/reports/xyz"})
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("application/pdf")
    assert r.content == b"%PDF-1.4 converted"


def test_word_without_soffice_falls_back_to_html(client, monkeypatch):
    async def fake(url: str):
        return 200, {
            "content-type": "application/octet-stream",
            "content-disposition": "attachment; filename*=UTF-8''report.wps",
        }, b"wps-bytes"
    monkeypatch.setattr(preview, "_fetch_bytes", fake)
    monkeypatch.setattr(preview, "_soffice", lambda: None)

    r = client.get("/api/file-preview", params={"url": "http://kb:8503/reports/w1"})
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]
    assert "下载" in r.text  # 兜底页提供下载出口，不再静默触发浏览器下载


def test_fetch_failure_returns_html(client, monkeypatch):
    async def fake(url: str):
        raise preview.FetchError("connect timeout")
    monkeypatch.setattr(preview, "_fetch_bytes", fake)

    r = client.get("/api/file-preview", params={"url": "http://kb:8503/reports/bad"})
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]
