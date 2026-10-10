"""测试包。

各测试模块自行把 ``src/`` 加进 ``sys.path``，因此**无需安装**即可运行：
``python -m unittest discover -s tests -t .``

``make_temp_dir`` 会优先使用系统临时目录；在某些受限沙箱（例如只允许写工作区
的环境）下系统临时目录不可写，此时自动退回到项目内的 ``.test-tmp/``。
"""

from __future__ import annotations

import os
import pathlib
import shutil
import tempfile
import uuid

PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[1]
_FALLBACK = PROJECT_ROOT / ".test-tmp"


def make_temp_dir() -> pathlib.Path:
    """返回一个**确实可写**的空目录。"""
    name = f"skill-atlas-test-{os.getpid()}-{uuid.uuid4().hex[:8]}"
    for base in (pathlib.Path(tempfile.gettempdir()), _FALLBACK):
        try:
            base.mkdir(parents=True, exist_ok=True)
            target = base / name
            target.mkdir()
            probe = target / ".write-probe"
            probe.write_text("ok", encoding="utf-8")
            probe.unlink()
            return target
        except OSError:
            continue
    raise RuntimeError("no writable temporary directory available")


def cleanup(path: pathlib.Path) -> None:
    shutil.rmtree(path, ignore_errors=True)
