"""控制台输出处理的测试。

对应真实事故：GitHub Actions 的 windows runner 上，demo 打印中文时

    UnicodeEncodeError: 'charmap' codec can't encode characters in position 0-73

因为 stdout 被重定向到管道后不再用 UTF-8。同一个问题在英文 Windows 上
直接运行也会发生，所以修的是代码而不只是 CI 配置。
"""

from __future__ import annotations

import io
import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))

from skill_atlas.console import ensure_safe_output  # noqa: E402


class _StreamWithoutReconfigure:
    """模拟没有 reconfigure 的流（例如被替换过的 stdout）。"""

    encoding = "utf-8"

    def write(self, text: str) -> int:
        return len(text)

    def flush(self) -> None:
        pass


class _StreamThatRefusesReconfigure:
    encoding = "utf-8"

    def reconfigure(self, **kwargs: object) -> None:
        raise ValueError("stream is closed")

    def write(self, text: str) -> int:
        return len(text)

    def flush(self) -> None:
        pass


class TestEnsureSafeOutput(unittest.TestCase):
    def test_changes_the_error_handler_not_the_encoding(self) -> None:
        """必须保留原编码：中文 Windows 用 cp936，改成 UTF-8 反而会乱码。"""
        raw = io.BytesIO()
        stream = io.TextIOWrapper(raw, encoding="cp1252")
        self.assertEqual(stream.encoding, "cp1252")

        original = sys.stdout
        sys.stdout = stream
        try:
            ensure_safe_output()
            self.assertEqual(stream.encoding, "cp1252", "编码不应被改掉")
            self.assertEqual(stream.errors, "replace", "错误处理应变成 replace")
        finally:
            sys.stdout = original
            stream.detach()

    def test_unencodable_text_no_longer_raises(self) -> None:
        """修复前这里会抛 UnicodeEncodeError。"""
        raw = io.BytesIO()
        stream = io.TextIOWrapper(raw, encoding="cp1252")

        original = sys.stdout
        sys.stdout = stream
        try:
            with self.assertRaises(UnicodeEncodeError):
                print("本地推理引擎")
            ensure_safe_output()
            print("本地推理引擎")  # 不应再抛异常
            stream.flush()
        finally:
            sys.stdout = original
            stream.detach()

        self.assertIn(b"?", raw.getvalue(), "无法编码的字符应降级为占位符")

    def test_stream_without_reconfigure_is_skipped(self) -> None:
        original = sys.stdout
        sys.stdout = _StreamWithoutReconfigure()  # type: ignore[assignment]
        try:
            ensure_safe_output()  # 不应抛异常
        finally:
            sys.stdout = original

    def test_reconfigure_failure_is_swallowed(self) -> None:
        original = sys.stdout
        sys.stdout = _StreamThatRefusesReconfigure()  # type: ignore[assignment]
        try:
            ensure_safe_output()  # 不应把 ValueError 传出去
        finally:
            sys.stdout = original

    def test_is_idempotent(self) -> None:
        original = sys.stdout
        try:
            ensure_safe_output()
            ensure_safe_output()
        finally:
            sys.stdout = original


if __name__ == "__main__":
    unittest.main()
