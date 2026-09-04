"""子进程执行制式脚本（headless，ADR-001 子进程隔离）。

本模块负责真正"跑脚本"。为什么用子进程而不是直接在主程序里调用？
——隔离。脚本是用户/LLM 生成的外部代码，可能有 bug：死循环、内存
暴涨、直接崩溃，如果在本进程里跑，一个坏脚本就能把整个应用拖死。
用子进程执行则完全隔离开：卡死了就超时杀掉，崩了主程序安然无恙，
还能拿到独立的结果输出。

执行协议（契约约定）：主程序把参数写成 job.json，命令行传给脚本；
脚本跑完向 stdout 打印**最后一行 JSON 结果**（status/files/elapsed），
日志一律走 stderr。本模块启动子进程、掐表计时、解析这行结果。

UI 层用 QThread 包装本模块（见 ui/workers.py），避免生成时界面卡死。
本模块禁止 import PySide6，保证可独立自动化测试。
"""

import logging
import os
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

from contract.result import parse_result_line

logger = logging.getLogger(__name__)


def _child_env() -> dict:
    """构造子进程环境变量：强制 UTF-8 输入输出。

    Windows 默认控制台编码是 GBK，脚本 print 中文（错误消息、产物路径）
    时按 GBK 编码写出，父进程按 UTF-8 读就全是乱码。设置 PYTHONIOENCODING
    让子进程解释器一启动就用 UTF-8，从源头解决（配合脚本模式
    run_script_only 里的 reconfigure 形成双保险）。
    """
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    return env


@dataclass
class RunResult:
    """一次脚本执行的结果（对应契约出参）。

    是 run_script 的返回值，无论成功失败都会给出结构化结果，
    界面据此展示文件列表或错误提示。

    关键属性：
    - ok: 脚本是否成功（status == "ok"）；
    - files: 成功时生成的文件完整路径列表；
    - elapsed: 脚本自报的耗时（秒）；
    - code: 失败时的错误码（TIMEOUT/INVALID_PARAMS/INTERNAL...）；
    - message: 失败时面向用户的错误说明；
    - stdout_tail: 脚本 stdout 原文（诊断用，正常时不关心）。
    """

    ok: bool
    files: list[str] = field(default_factory=list)
    elapsed: float = 0.0
    code: str = ""
    message: str = ""
    stdout_tail: str = ""


def run_script(
    script_path: Path,
    params_json: Path,
    timeout: float = 300.0,
    python: str | None = None,
) -> RunResult:
    """同步执行脚本；超时返回 code=TIMEOUT。python 参数供测试注入其他解释器。

    根据运行环境选择启动方式（见下）：
    - 传了 python 参数：测试场景，直接用它执行脚本；
    - frozen（打包成 exe 后）：sys.executable 是我们自己的 exe，
      它不能直接"执行".py——这时通过 --run-script 参数让子 exe
      进入无头模式（不启动界面），由子进程内的 exec() 执行脚本；
    - 普通开发环境：直接 python script.py --params xxx。

    打包后（frozen）：sys.executable 是 exe 自身，不能直接执行 .py 脚本，
    通过 --run-script 参数启动子 exe（不启动 UI），子进程内 exec() 执行脚本。
    非 frozen：直接 python script.py --params xxx。
    结果解析只认 stdout 最后一行（契约 §3）；脚本日志在 stderr，不参与解析。

    Args:
        script_path: 要执行的脚本 .py 路径。
        params_json: job.json 参数文件路径。
        timeout: 超时秒数，超时杀进程并返回 TIMEOUT。
        python: 测试注入的解释器路径（跳过 frozen 判断）。

    Returns:
        RunResult：结构化结果，永不抛异常（一切失败都转成 ok=False）。
    """
    if python:
        # 测试注入：完全跳过 frozen 逻辑
        cmd = [python, str(script_path), "--params", str(params_json)]
    elif getattr(sys, "frozen", False):
        # 打包后（frozen=True）：sys.executable 是应用 exe 本身，
        # 不能拿来执行 .py → 用 --run-script 走无头子进程模式
        cmd = [sys.executable, "--run-script",
               str(script_path), "--params", str(params_json)]
    else:
        # 开发环境：系统 Python 直接执行脚本
        cmd = [sys.executable, str(script_path), "--params", str(params_json)]
    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=timeout,
            env=_child_env(),
        )
    except subprocess.TimeoutExpired:
        logger.warning("脚本超时：%s（>%.0f 秒）", script_path.name, timeout)
        return RunResult(ok=False, code="TIMEOUT",
                         message=f"脚本执行超过 {timeout:.0f} 秒，已终止")
    except OSError as exc:
        return RunResult(ok=False, code="INTERNAL",
                         message=f"无法启动脚本进程：{exc}")

    stdout = proc.stdout or ""
    lines = [ln for ln in stdout.splitlines() if ln.strip()]
    tail = lines[-1] if lines else ""
    # 契约约定：结果 JSON 必须是 stdout 最后一行；非零退出且无输出 = 异常
    if proc.returncode != 0 and not tail:
        return RunResult(ok=False, code="INTERNAL",
                         message=f"脚本异常退出（码 {proc.returncode}），无结果输出",
                         stdout_tail=stdout)

    try:
        data = parse_result_line(tail)
    except ValueError as exc:
        return RunResult(ok=False, code="INTERNAL",
                         message=f"{exc}（退出码 {proc.returncode}）",
                         stdout_tail=stdout)

    if data.get("status") == "ok":
        return RunResult(ok=True, files=list(data.get("files", [])),
                         elapsed=float(data.get("elapsed", 0.0)))
    return RunResult(ok=False, code=data.get("code", "INTERNAL"),
                     message=data.get("message", "未知错误"),
                     stdout_tail=stdout)
