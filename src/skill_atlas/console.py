"""控制台输出的安全处理。

为什么需要
----------
Windows 上 Python 默认用当前代码页写 stdout（英文系统常见 cp1252）。
本工具的输出里有中文，于是：

* 直接运行 —— 在英文 Windows 控制台上打印中文会 `UnicodeEncodeError` 崩掉
* 被重定向到管道（CI 就是这么做的）—— 同样崩掉

实测复现（GitHub Actions 的 windows runner 上真实发生过）::

    UnicodeEncodeError: 'charmap' codec can't encode characters in position 0-73

取舍：**保留控制台原有的编码**，只把错误处理换成 ``replace``。
这样在中文 Windows（cp936）上中文照常正确显示，在别的代码页上最多把
个别字符显示成 ``?``，而不是整个程序崩掉。需要日志里保留完整中文的环境
（例如 CI）应当设 ``PYTHONIOENCODING=utf-8``。
"""

from __future__ import annotations

import sys


def ensure_safe_output() -> None:
    """让 stdout/stderr 遇到无法编码的字符时降级，而不是抛异常。"""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:  # 被替换过的流，或非常规流
            continue
        try:
            reconfigure(errors="replace")
        except (ValueError, OSError):
            # 流已关闭、或底层不支持重新配置 —— 不是致命问题
            pass
