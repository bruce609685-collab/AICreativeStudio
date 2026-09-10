"""后台任务（QThread + 信号）：生成 / 导入时界面不卡死。

本模块是 UI 层的"后台线程"集合。Qt 规定界面只能在主（UI）线程更新，
而脚本执行 / LLM 调用可能耗时几十秒——若在 UI 线程直接跑，界面会
完全卡死。这里用 QThread 把耗时操作放到子线程，结果通过 Signal
发出；Qt 的信号槽机制自动把回调切回 UI 线程执行（跨线程安全），
页面里连接信号的槽函数可以放心更新界面。

  - GenerateWorker：执行一个制式脚本（图/视/音生成共用），成功/失败
    分别经 finished_ok / finished_err 信号回传 RunResult；
  - ImportWorker：跑智能导入管线，过程日志经 log_line、LLM 流式输出
    经 chunk_received 实时回传，最终结果经 finished_import 回传。
"""

from pathlib import Path

from PySide6.QtCore import QThread, Signal

from core.importer.llm_client import LLMConfig
from core.importer.pipeline import ImportResult, import_from_document
from core.runner.runner import RunResult, run_script


class GenerateWorker(QThread):
    """在后台线程执行一次制式脚本，结果经信号回传（UI 线程消费）。

    线程安全说明：run() 在子线程执行耗时脚本；finished_ok /
    finished_err 是 Qt 信号，跨线程 emit 时 Qt 自动把槽调用排队到
    UI 线程执行，页面槽函数中更新界面是安全的。
    """

    # 信号：脚本执行成功，参数 RunResult（ok=True）
    finished_ok = Signal(object)
    # 信号：脚本执行失败，参数 RunResult（ok=False，含 code/message）
    finished_err = Signal(object)

    def __init__(self, script_path, params_json, timeout: float = 360.0,
                 parent=None) -> None:
        """记录脚本路径、参数文件与超时。

        参数：
            script_path: 脚本绝对路径；params_json: 任务参数 JSON 文件路径；
            timeout: 脚本执行超时秒数（默认 360：脚本预算 300 + 60 秒安全余量）。
        """
        super().__init__(parent)
        self._script = script_path
        self._params = params_json
        self._timeout = timeout

    def run(self) -> None:
        """QThread 子线程入口：执行脚本并按结果发出对应信号。"""
        result = run_script(self._script, self._params, timeout=self._timeout)
        if result.ok:
            self.finished_ok.emit(result)
        else:
            self.finished_err.emit(result)


class ImportWorker(QThread):
    """在后台线程跑智能导入管线（LLM 调用可能很慢），进度经信号回传。

    三个信号分工：
      finished_import: 管线最终结果（ImportResult）；
      log_line:        过程日志（一行一条，页面追加到日志区）；
      chunk_received:  LLM 流式输出的增量文本块（页面实时追加显示）。
    """

    finished_import = Signal(object)   # ImportResult
    log_line = Signal(str)             # 进度日志一行
    chunk_received = Signal(str)       # LLM 输出增量块（流式实时显示）

    def __init__(self, doc_text: str, cfg: LLMConfig,
                 templates_dir: Path, scripts_dir: Path,
                 category: str = "",
                 parent=None) -> None:
        """记录导入所需的输入与目录。

        参数：
            doc_text: 用户粘贴的 API 接入文档全文；
            cfg: LLM 配置（地址/密钥/模型/演示模式）；
            templates_dir: 提示词模板目录；scripts_dir: 脚本输出目录；
            category: 指定 API 类别（空串=自动识别）。
        """
        super().__init__(parent)
        self._doc = doc_text
        self._cfg = cfg
        self._templates = templates_dir
        self._scripts = scripts_dir
        self._category = category

    def run(self) -> None:
        """QThread 子线程入口：跑完整导入管线。

        通过 on_log / on_chunk 回调把日志与流式输出转成信号发回
        UI 线程（回调发生在子线程，emit 信号本身是线程安全的）。
        """
        result = import_from_document(
            self._doc, self._cfg, self._templates, self._scripts,
            on_log=lambda msg: self.log_line.emit(msg),
            on_chunk=lambda text: self.chunk_received.emit(text),
            category=self._category,
        )
        self.finished_import.emit(result)
