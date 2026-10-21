#!/usr/bin/env python3
"""补全离线 wheelhouse 中被 pip 漏掉的「环境标记依赖」。

背景：pip download 的依赖解析按【本机】Python 版本评估 marker。
本机构建机是 Python 3.11，目标机是 3.10，于是 `python_version < "3.11"`
的条件依赖（典型：anyio → exceptiongroup）会被误判为「不需要」而漏下载，
导致目标机离线安装失败。

本脚本扫描 wheelhouse 内所有 wheel 的 METADATA，用目标环境
（Linux x86_64 / CPython 3.10）评估 marker，把缺失的依赖补下载进来，
迭代至依赖闭包完整。

用法：fill_wheelhouse.py <wheelhouse目录> <pip下载参数...>
"""
import re
import subprocess
import sys
import zipfile
from email.parser import Parser
from pathlib import Path

from packaging.markers import default_environment
from packaging.requirements import Requirement
from packaging.utils import canonicalize_name

TARGET_ENV = {
    **default_environment(),
    "python_version": "3.10",
    "python_full_version": "3.10.0",
    "sys_platform": "linux",
    "platform_system": "Linux",
    "platform_machine": "x86_64",
    "os_name": "posix",
    "implementation_name": "cpython",
}

MAX_ROUNDS = 5


def wheel_dist_name(path: Path) -> str:
    return canonicalize_name(path.name.split("-")[0])


def present_names(wheelhouse: Path) -> set[str]:
    return {wheel_dist_name(p) for p in wheelhouse.glob("*.whl")}


def required_names(wheelhouse: Path) -> set[str]:
    """扫描全部 wheel 的 METADATA，返回目标环境下真正需要的依赖名集合。"""
    needed: set[str] = set()
    for whl in wheelhouse.glob("*.whl"):
        with zipfile.ZipFile(whl) as zf:
            meta_file = next(
                (n for n in zf.namelist() if n.endswith(".dist-info/METADATA")), None
            )
            if not meta_file:
                continue
            headers = Parser().parsestr(zf.read(meta_file).decode("utf-8", "replace"))
        for req_str in headers.get_all("Requires-Dist") or []:
            req = Requirement(req_str)
            if req.marker is not None and not req.marker.evaluate(TARGET_ENV):
                continue
            needed.add(canonicalize_name(req.name))
    return needed


def main() -> int:
    wheelhouse = Path(sys.argv[1])
    pip_args = sys.argv[2:]  # 例如 --only-binary=:all: --platform ... --python-version 3.10

    for round_no in range(1, MAX_ROUNDS + 1):
        missing = sorted(required_names(wheelhouse) - present_names(wheelhouse))
        if not missing:
            print(f"  依赖闭包完整（第 {round_no} 轮检查通过）：{wheelhouse}")
            return 0
        print(f"  第 {round_no} 轮：补下载缺失依赖 {missing}")
        subprocess.run(
            [sys.executable, "-m", "pip", "download", *missing,
             "-d", str(wheelhouse), *pip_args, "--quiet"],
            check=True,
        )

    print(f"错误：{MAX_ROUNDS} 轮后依赖仍不完整：{wheelhouse}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
