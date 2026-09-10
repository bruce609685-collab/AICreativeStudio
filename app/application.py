"""应用装配：QApplication 初始化、全局样式、异常钩子、主窗口启动。

这个文件是程序的"总装车间"：main.py 只负责走进来，而真正把日志、
单实例锁、界面框架、脚本注册表、历史数据库等零件按顺序组装起来、
最后亮出主窗口的工作都在这里完成。两个入口分别是：

- run()：正常启动，带完整图形界面；
- run_script_only()：打包后子进程模式（--run-script），不启动 UI，
  只在后台执行一个制式脚本并输出结果。

另含 run_script_only()：打包后子进程模式（--run-script），不启动 UI。
"""

import argparse
import json
import logging
import sys
from pathlib import Path

from PySide6.QtWidgets import QApplication, QMessageBox

import about
from app import paths
from app.logger_setup import setup_logging
from app.single_instance import SingleInstance
from core.registry import ScriptRegistry, scan_scripts_dir
from infra.persistence import HistoryDatabase
from ui.main_window import MainWindow
from ui.style import apply_global_style

# 本模块专用的日志器：日志名会自动带上 "app.application" 前缀，便于定位
logger = logging.getLogger(__name__)


def _install_excepthook() -> None:
    """未捕获异常统一落到日志 + 弹窗，避免静默崩溃。

    Python 程序一旦有错误没被 try/except 捕住就会直接崩溃退出，用户
    只会看到"窗口突然消失"。安装 excepthook（异常钩子）后，任何未捕获
    异常都会先进入我们自定义的 _hook 函数：写入日志，并弹一个带技术
    详情的对话框，让用户知道发生了什么、能反馈日志。
    """

    def _hook(exc_type, exc_value, exc_tb):
        # exc_info 让 logger 把完整异常堆栈写进日志文件
        logger.critical("unhandled exception", exc_info=(exc_type, exc_value, exc_tb))
        # 只有 Qt 应用已创建时才弹窗（否则弹窗本身也会崩）；instance() 为
        # None 表示 QApplication 还没起来或已退出
        if QApplication.instance() is not None:
            box = QMessageBox()
            box.setIcon(QMessageBox.Icon.Critical)
            box.setWindowTitle(about.APP_NAME)
            box.setText("程序遇到未处理的错误，详情已写入日志文件。")
            # "详细文本"里放上完整堆栈，方便开发者排查；
            # __import__("traceback") 是局部导入，避免模块顶层多余依赖
            box.setDetailedText("".join(
                __import__("traceback").format_exception(exc_type, exc_value, exc_tb)
            ))
            box.exec()

    # 把自定义钩子挂到 sys.excepthook，之后所有未捕获异常都会走这里
    sys.excepthook = _hook


def run_script_only() -> int:
    """无头模式：子进程内直接执行制式脚本（打包后 --run-script 入口）。

    不初始化 UI、不检查单实例。OS 进程边界已保证隔离，
    脚本通过 exec() 在当前进程执行，结果 JSON 写入 stdout 供父进程读取。

    参数（从命令行解析）：--run-script 脚本文件路径、--params 参数 JSON 路径。
    返回值：进程退出码，0 表示脚本执行成功，1 表示失败。
    """
    setup_logging()
    paths.ensure_dirs()

    # 强制子进程 stdout/stderr 用 UTF-8（修复历史 bug：Windows 默认 GBK
    # 打印中文 → 父进程按 UTF-8 读 → 错误消息和产物路径全部乱码，
    # 进而导致历史库里的路径失效、缩略图/点击打开全部失灵）。
    # reconfigure 在 Python 3.7+ 可用；万一失败也不影响后续执行。
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, OSError):
        pass

    # parse_known_args：只认 --run-script / --params，多余参数不报错
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-script")
    parser.add_argument("--params")
    args, _ = parser.parse_known_args()

    # 缺 --run-script / --params 时按契约输出错误 JSON，而不是 Path(None) 崩溃
    if not args.run_script or not args.params:
        err = {"status": "error", "code": "INTERNAL",
               "message": "缺少 --run-script 或 --params 参数"}
        print(json.dumps(err, ensure_ascii=False))
        return 1
    script_path = Path(args.run_script)
    params_path = Path(args.params)

    # 文件不存在时按契约输出一行错误 JSON（供父进程解析），退出码 1
    if not script_path.exists():
        err = {"status": "error", "code": "INTERNAL",
               "message": f"脚本文件不存在：{script_path}"}
        print(json.dumps(err, ensure_ascii=False))
        return 1
    if not params_path.exists():
        err = {"status": "error", "code": "INTERNAL",
               "message": f"参数文件不存在：{params_path}"}
        print(json.dumps(err, ensure_ascii=False))
        return 1

    # 在当前进程（已隔离子进程）内执行脚本
    # 之所以用 exec() 而不是再开一个 python 进程：打包后的 exe 里没有
    # 独立可调的 python 解释器，只能"在自己身体里"运行脚本
    old_argv = sys.argv
    # 伪装成"直接运行该脚本"的样子：脚本内部读 sys.argv 就能拿到参数
    sys.argv = [str(script_path), "--params", str(params_path)]
    try:
        # compile + exec 相当于把脚本文件当作 main 程序跑一遍；
        # errors="replace" 让读取含坏字节的文件也不崩（坏字节替换为 U+FFFD）
        code = compile(script_path.read_text(encoding="utf-8", errors="replace"),
                       str(script_path), "exec")
        exec(code, {"__name__": "__main__", "__file__": str(script_path)})
    except SystemExit as e:
        # 脚本里可能调用了 sys.exit()：把它的退出码透传出去
        return e.code if isinstance(e.code, int) else 1
    except Exception as exc:
        # 脚本抛了普通异常：按契约输出错误 JSON，而不是让进程崩溃
        err = {"status": "error", "code": "INTERNAL",
               "message": f"脚本执行异常：{exc}"}
        print(json.dumps(err, ensure_ascii=False))
        return 1
    finally:
        # 无论成功失败都把 sys.argv 还原，避免污染后续逻辑
        sys.argv = old_argv
    return 0


def run() -> int:
    """程序入口：日志 → 单实例 → QApplication → 主窗口。

    按固定顺序完成全部初始化，任何一步失败都能在日志中看到进度。
    返回值：Qt 事件循环的退出码，原样交给 main.py 返回给操作系统。
    """
    setup_logging()
    logger.info("%s v%s starting (build %s)", about.APP_ID, about.APP_VERSION, about.BUILD_DATE)

    paths.ensure_dirs()

    # 创建 Qt 应用对象（整个 GUI 的"心脏"，必须最先创建）
    app = QApplication(sys.argv)
    app.setApplicationName(about.APP_NAME)
    app.setOrganizationName(about.AUTHOR)

    # 单实例检查：已有实例在跑就提示后退出，避免数据竞争和窗口重复
    guard = SingleInstance()
    if not guard.try_lock():
        QMessageBox.information(
            None, about.APP_NAME, "程序已在运行中，请勿重复打开。"
        )
        return 0

    _install_excepthook()
    apply_global_style(app)

    # 扫描 scripts/ 建立脚本注册表（页面下拉与参数区由它驱动）
    registry = ScriptRegistry()
    registry.load(scan_scripts_dir(paths.SCRIPTS_DIR))
    logger.info("scripts loaded: %d", registry.count())

    # 历史记录库（三个生成页共用，SQLite 单文件）
    db = HistoryDatabase(paths.HISTORY_DB)

    # 组装主窗口：把脚本注册表和历史库注入，窗口自己不再创建它们
    window = MainWindow(registry, db)
    window.show()
    logger.info("main window shown")

    # exec() 进入 Qt 事件循环并阻塞到窗口关闭；返回后做清理
    exit_code = app.exec()
    guard.release()
    logger.info("exit with code %s", exit_code)
    return exit_code
