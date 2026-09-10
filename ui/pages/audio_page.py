"""AI 生语音页（还原预览文档 page-audio）。

界面布局：左栏"文本内容（带字符数统计/超限变红）+ 语音参数（音色/格式）
+ 风格指令 + 生成按钮"，右栏"语音播放器（波形示意+真实元数据）
+ 提示词回看 + 历史表格"。

生成流程（与图/视频页同构）：
  _start_generate 校验文本长度 → 写 job 任务文件 → GenerateWorker
  后台线程执行脚本 → finished_ok/finished_err 信号回 UI 线程 →
  _on_gen_ok 加载 WAV 到播放器 / _on_gen_err 显示错误 → 历史落库刷新。

M1：静态演示；M3：注册表驱动参数区 + 真实生成链路（QThread 后台）+ 产物
播放（系统播放器打开）+ 历史记录落库 SQLite（表格展示真实元数据）。
"""

from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QGroupBox, QHBoxLayout, QLabel, QPlainTextEdit, QPushButton, QScrollArea,
    QVBoxLayout, QWidget,
)

from app import paths
from core.keys import detect_key_status
from core.registry import ScriptRegistry
from core.runner import RunResult, build_audio_params, write_job_file
from core.services import HistoryDatabase
from domain.enums import MediaCategory
from ui.widgets import (
    AudioPlayer, ElapsedTimer, HistoryTable, KeyWarnBar, ModelBar, ParamPanel,
    PromptEcho,
)
from ui.workers import GenerateWorker

# 默认合成文本 / 风格指令 / 默认字符上限（实际以脚本元数据 max_text_len 为准）
DEFAULT_TEXT = "大家好，欢迎来到 AI 创意工坊。今天我将带你领略人工智能在创意领域的无限可能。"
STYLE_TTS = "温柔、亲切、带有微笑的语气"
DEFAULT_MAX_LEN = 1000


class AudioPage(QWidget):
    """生语音页：左参数 / 右预览+历史。

    与图/视频页同构；差异点：输入是"文本"而非提示词（带字数上限校验），
    右栏用 AudioPlayer + HistoryTable（表格形式历史）。
    """

    def __init__(self, main_window, registry: ScriptRegistry,
                 db: HistoryDatabase, parent=None) -> None:
        """构造生语音页。

        参数：
            main_window: 主窗口引用（状态栏提示 / 页签跳转）
            registry: 脚本注册表，提供语音类可用脚本
            db: 历史数据库，用于记录生成结果
        """
        super().__init__(parent)
        self._main = main_window
        self._registry = registry
        self._db = db
        self._current_key = ""            # 当前选中脚本 key
        self._max_len = DEFAULT_MAX_LEN   # 当前脚本的文本字符上限
        self._worker: GenerateWorker | None = None  # 后台生成线程
        self._last_output_dir = ""        # 最近输出目录（兜底扫描用）
        self._last_params: dict = {}      # 最近一次生成的参数快照（历史落库用）
        # 计时进度：生成中每 0.5 秒刷新"已等待 N 秒"
        self._gen_timer = ElapsedTimer(self, self._on_gen_tick)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(12)
        layout.addWidget(self._build_left(), stretch=0)
        layout.addWidget(self._build_right(), stretch=1)

        # 初始选中第一个语音脚本并加载历史
        metas = self._registry.by_category(MediaCategory.AUDIO)
        self._on_script_changed(metas[0].file_path if metas else "")
        self._refresh_history()

    def refresh_scripts(self) -> None:
        """导入新脚本后刷新脚本下拉列表（由 import_page 导入完成后调用）。"""
        scripts = {
            m.file_path: m.display_name
            for m in self._registry.by_category(MediaCategory.AUDIO)
        }
        self._model_bar.reload(scripts)
        if not self._current_key or self._current_key not in scripts:
            metas = self._registry.by_category(MediaCategory.AUDIO)
            self._on_script_changed(metas[0].file_path if metas else "")

    # ------------------------------------------------------------------
    # 左栏
    # ------------------------------------------------------------------

    def _build_left(self) -> QWidget:
        """构建左栏：脚本选择条 + KEY 警告条 + 文本/参数/风格 + 生成按钮。

        返回：组装好的左栏 QWidget（固定宽 372px）。
        """
        col = QWidget()
        col.setFixedWidth(372)
        outer = QVBoxLayout(col)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(7)

        # 脚本选择条：语音类脚本下拉
        scripts = {
            m.file_path: m.display_name
            for m in self._registry.by_category(MediaCategory.AUDIO)
        }
        self._model_bar = ModelBar(scripts)
        # 信号槽：切换脚本 → 刷新音色/格式选项与字数上限
        self._model_bar.script_changed.connect(self._on_script_changed)
        outer.addWidget(self._model_bar)

        self._key_warn = KeyWarnBar()
        outer.addWidget(self._key_warn)

        # 中间滚动区
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        inner = QWidget()
        outer.addWidget(scroll, stretch=1)
        s = QVBoxLayout(inner)
        s.setContentsMargins(0, 0, 2, 0)
        s.setSpacing(7)

        # 文本内容：输入框 + 实时字符数统计（超限变红）
        text_box = QGroupBox("文本内容")
        tv = QVBoxLayout(text_box)
        self._text = QPlainTextEdit(DEFAULT_TEXT)
        self._text.setFixedHeight(80)
        # 信号槽：文本变化 → 刷新字符数统计
        self._text.textChanged.connect(self._on_text)
        tv.addWidget(self._text)
        self._count = QLabel(f"字符数：{len(DEFAULT_TEXT)} / {self._max_len}")
        self._count.setStyleSheet("font-size:11px; color:#888;")
        tv.addWidget(self._count)
        s.addWidget(text_box)

        # 语音参数：音色与格式（选项由脚本元数据驱动）
        param = QGroupBox("语音参数")
        self._params = ParamPanel()
        self._params.add_combo_row("voice", "预置音色", [])
        self._params.add_combo_row("format", "音频格式", ["wav", "pcm16"])
        dv2 = QVBoxLayout(param)
        dv2.addWidget(self._params)
        s.addWidget(param)

        # 风格指令：普通 TTS 可选；voice_design 类脚本必填（标题会变）
        self._style_box = QGroupBox("风格指令（可选）")
        sv = QVBoxLayout(self._style_box)
        self._style = QPlainTextEdit(STYLE_TTS)
        self._style.setFixedHeight(60)
        sv.addWidget(self._style)
        s.addWidget(self._style_box)

        # 生成按钮 + 进度提示区
        gen_box = QWidget()
        gv = QVBoxLayout(gen_box)
        gv.setContentsMargins(0, 4, 0, 0)
        self._gen_btn = QPushButton("🎙 生成语音")
        self._gen_btn.setProperty("class", "primary")
        # 信号槽：点击生成 → 后台线程跑脚本
        self._gen_btn.clicked.connect(self._start_generate)
        gv.addWidget(self._gen_btn)
        self._prog = QPlainTextEdit("")
        self._prog.setReadOnly(True)
        self._prog.setFixedHeight(48)
        self._prog.setStyleSheet(
            "background:#f0f7ff; border:1px solid #b3d9f7; color:#0078d4;"
            " font-size:12px; padding:3px 7px; border-radius:1px;"
        )
        self._prog.hide()
        gv.addWidget(self._prog)
        s.addWidget(gen_box)
        s.addStretch(1)

        scroll.setWidget(inner)
        return col

    # ------------------------------------------------------------------
    # 右栏
    # ------------------------------------------------------------------

    def _build_right(self) -> QWidget:
        """构建右栏：语音播放器 + 提示词回看 + 按钮行 + 历史表格。

        返回：组装好的右栏 QWidget。
        """
        col = QWidget()
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        inner = QWidget()
        s = QVBoxLayout(inner)
        s.setContentsMargins(0, 0, 0, 0)
        s.setSpacing(7)

        # 语音播放器：波形示意 + 真实时长/采样率/格式
        prev = QGroupBox("语音预览")
        pv = QVBoxLayout(prev)
        pv.setContentsMargins(0, 0, 0, 0)
        self._player = AudioPlayer()
        pv.addWidget(self._player)
        s.addWidget(prev)

        # 播放器的上一首/下一首 → 按历史记录顺序切换（§3.3 播放控制）
        self._player.navigate_prev.connect(
            lambda: self._navigate_hist(-1))
        self._player.navigate_next.connect(
            lambda: self._navigate_hist(+1))

        # 提示词回看条（回显合成文本）
        self._echo = PromptEcho(DEFAULT_TEXT)
        s.addWidget(self._echo)

        # 按钮：打开输出目录 / 播放当前产物
        actions = QHBoxLayout()
        actions.setSpacing(5)
        # 文案修正：这两个按钮都是"打开"而非"下载"，用文件夹/播放图标更准确
        dl = QPushButton("📁 打开文件夹")
        dl.clicked.connect(self._open_output_dir)
        op = QPushButton("▶ 系统播放")
        op.clicked.connect(self._player.open_external)
        for b in (dl, op):
            b.setStyleSheet("padding:5px 0px;")
            actions.addWidget(b, stretch=1)
        s.addLayout(actions)

        # 历史表格：成功行"▶ 播放"，失败行"详情"
        hist_box = QGroupBox("历史记录")
        hv = QVBoxLayout(hist_box)
        self._hist = HistoryTable()
        # 信号槽：成功行点击 → 播放；失败行点击 → 状态栏显示错误详情
        self._hist.row_clicked.connect(self._play_hist)
        self._hist.detail_requested.connect(self._show_fail_detail)
        hv.addWidget(self._hist)
        s.addWidget(hist_box)
        s.addStretch(1)

        scroll.setWidget(inner)
        outer = QVBoxLayout(col)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(scroll)
        return col

    # ------------------------------------------------------------------
    # 元数据驱动
    # ------------------------------------------------------------------

    def _current_meta(self):
        """返回当前选中脚本的元数据；未选中时返回 None。"""
        if not self._current_key:
            return None
        return self._registry.get(self._current_key)

    def _script_abs_path(self, meta) -> Path:
        """把脚本相对路径拼成绝对路径（scripts/ 目录 + 相对路径）。"""
        return paths.SCRIPTS_DIR / meta.file_path

    def _on_script_changed(self, key: str) -> None:
        """切换脚本后的联动更新：音色/格式选项、字数上限、风格框标题、KEY 警告。

        参数：key: 新选中脚本的 key，空串表示无可选脚本。
        """
        self._current_key = key or ""
        meta = self._current_meta()
        if meta is None:
            self._params.set_caps({})
            self._key_warn.hide()
            return
        # 语音页能力字典只有音色与格式两项
        self._params.set_caps({"voice": meta.voices, "format": meta.formats})
        # 文本字数上限以脚本元数据为准；刷新统计显示
        self._max_len = meta.max_text_len or DEFAULT_MAX_LEN
        self._on_text()
        # voice_design（音色设计）类脚本：风格描述必填，标题随之变化
        self._style_box.setTitle(
            "音色设计描述（必填）" if meta.function == "voice_design"
            else "风格指令（可选）"
        )
        self._update_key_warn(meta)
        # §5.4 契约版本门闸：脚本模板过旧/过新时状态栏提醒（不阻断使用）
        self._warn_version_compat(meta)

    def _warn_version_compat(self, meta) -> None:
        """脚本模板版本与外壳不一致时状态栏提醒（§5.4，不阻断）。"""
        if getattr(meta, "version_compat", "ok") == "ok":
            return
        if meta.version_compat == "older":
            self._main.show_status(
                f"⚠ 脚本模板过旧（v{meta.template_version}），建议重新导入更新",
                4000)
        else:
            self._main.show_status(
                f"⚠ 脚本模板较新（v{meta.template_version}），请升级主程序以完整支持",
                4000)

    def _update_key_warn(self, meta) -> None:
        """检测脚本 API KEY 状态，未配置时显示黄色警告条。

        参数：meta: 当前脚本元数据。
        """
        if detect_key_status(self._script_abs_path(meta), meta) == "ok":
            self._key_warn.hide()
            return
        env = meta.key_env or "对应环境变量"
        self._key_warn.set_text(
            f"⚠ 脚本尚未配置 API KEY（脚本内 API_KEY 或环境变量 {env}），"
            "真实生成将失败，可先体验演示模式。"
        )
        self._key_warn.show()

    def _on_text(self) -> None:
        """文本变化时刷新字符数统计；超过脚本上限时数字变红警示。"""
        n = len(self._text.toPlainText())
        self._count.setText(f"字符数：{n} / {self._max_len}")
        self._count.setStyleSheet(
            "font-size:11px; color:#d32f2f;" if n > self._max_len
            else "font-size:11px; color:#888;"
        )

    # ------------------------------------------------------------------
    # 生成
    # ------------------------------------------------------------------

    def _start_generate(self, mock: bool = False) -> None:
        """启动一次语音合成：校验文本 → 写任务文件 → 后台线程跑脚本。

        参数：mock: True 时走演示链路（生成占位 WAV，无需 API KEY）。
        """
        meta = self._current_meta()
        if meta is None:
            self._main.show_status("未找到可用脚本，请检查 scripts/ 目录", 3000)
            return
        text = self._text.toPlainText().strip()
        if not text:
            self._main.show_status("请先输入文本内容", 2500)
            return
        # 文本长度校验：超过脚本上限直接拒绝（界面已红字提示）
        if len(text) > self._max_len:
            self._main.show_status(f"文本超过上限 {self._max_len} 字", 2500)
            return
        # 音色设计类脚本：风格描述必填校验（§3.3，标题为"必填"时拦截）
        style = self._style.toPlainText().strip()
        if meta.function == "voice_design" and not style:
            self._main.show_status("音色设计描述为必填项，请填写描述", 3500)
            return

        # 按时间戳建输出目录，收集界面参数
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        out_dir = paths.OUTPUT_AUDIO_DIR / stamp
        self._last_output_dir = str(out_dir)
        params = build_audio_params(
            text=text,
            voice=self._params.value("voice"),
            style=style,
            format_=self._params.value("format"),
            output_dir=out_dir,
            mock=mock,
        )
        # 记录本次生成参数（历史落库用，§7）
        self._last_params = {
            k: v for k, v in params.items()
            if k not in ("output_dir", "timeout")
        }
        # 参数落盘为 job JSON，脚本从文件读取
        job_file = write_job_file(paths.JOBS_DIR / f"job_audio_{stamp}.json",
                                  **params)

        # 进入"生成中"状态
        self._gen_btn.setEnabled(False)
        self._prog.setStyleSheet(
            "background:#f0f7ff; border:1px solid #b3d9f7; color:#0078d4;"
            " font-size:12px; padding:3px 7px; border-radius:1px;"
        )
        self._prog.show()
        self._gen_timer.start()   # 计时进度：文本由 _on_gen_tick 持续刷新
        self._main.show_status("生成中，请稍候…", 0)

        # 后台线程执行脚本，信号跨线程回传 UI 线程更新界面
        worker = GenerateWorker(self._script_abs_path(meta), job_file, parent=self)
        worker.finished_ok.connect(self._on_gen_ok)      # 成功 → 播放器加载 WAV
        worker.finished_err.connect(self._on_gen_err)    # 失败 → 显示错误
        worker.finished.connect(worker.deleteLater)      # 线程结束自动释放
        self._worker = worker
        worker.start()

    def demo_generate(self) -> None:
        """演示模式：mock 链路生成占位 WAV（截图/测试用，无需 KEY）。"""
        self._start_generate(mock=True)

    def _on_gen_tick(self, seconds: float) -> None:
        """计时器回调（0.5 秒一次）：把"已等待 N 秒"刷新到进度提示区。"""
        self._prog.setPlainText(f"⟳ 生成中… 已等待 {seconds:.0f} 秒")

    def _on_gen_ok(self, result: RunResult) -> None:
        """生成成功回调（UI 线程）：恢复按钮 → 历史落库 → 播放器加载 WAV。

        参数：result: 脚本执行结果。
        """
        self._gen_timer.stop()
        self._gen_btn.setEnabled(True)
        self._prog.hide()
        files = [f for f in result.files if Path(f).exists()]
        self._write_history(result)
        if files:
            self._player.load(files[0])
            self._echo.set_text(self._text.toPlainText())
            self._main.show_status(
                f"生成完成，耗时 {result.elapsed:.1f} 秒", 3000)
        else:
            # 脚本 stdout 可能未报告产物路径 → 兜底扫描输出目录找音频文件
            scanned: list[str] = []
            if self._last_output_dir:
                od = Path(self._last_output_dir)
                if od.is_dir():
                    scanned = sorted(
                        str(p) for p in od.rglob("*")
                        if p.is_file() and p.suffix.lower()
                        in (".wav", ".mp3", ".pcm", ".ogg", ".flac")
                    )
            if scanned:
                self._player.load(scanned[0])
                self._echo.set_text(self._text.toPlainText())
                self._main.show_status(
                    f"生成完成，共 {len(scanned)} 个文件（从产物目录发现）", 3000)
            else:
                # 无产物：黄色警告 + 显示脚本输出片段
                detail = "生成完成，但没有产物文件"
                if result.stdout_tail:
                    detail += f"\n脚本输出：{result.stdout_tail[:200]}"
                self._prog.setStyleSheet(
                    "background:#fff8e1; border:1px solid #f0c040;"
                    " color:#b8860b; font-size:12px; padding:3px 7px;"
                    " border-radius:1px;"
                )
                self._prog.setPlainText(f"⚠ {detail}")
                self._prog.show()
                self._main.show_status(detail, 5000)

    def _on_gen_err(self, result: RunResult) -> None:
        """生成失败回调（UI 线程）：红色错误提示 + 失败历史 + KEY 警告刷新。

        参数：result: 脚本执行结果（含错误码与错误信息）。
        """
        self._gen_timer.stop()
        self._gen_btn.setEnabled(True)
        self._prog.setStyleSheet(
            "background:#fff5f5; border:1px solid #f0b0b0; color:#d32f2f;"
            " font-size:12px; padding:3px 7px; border-radius:1px;"
        )
        self._prog.setPlainText(f"✕ {result.code}：{result.message}")
        self._prog.show()
        self._write_fail_history(result)
        self._main.show_status(f"生成失败：{result.message}", 4000)
        # 认证失败 → 重新检测 KEY 状态并显示警告条
        if result.code == "AUTH_FAILED":
            meta = self._current_meta()
            if meta is not None:
                self._update_key_warn(meta)

    # ------------------------------------------------------------------
    # 历史 / 产物
    # ------------------------------------------------------------------

    def _write_history(self, result: RunResult) -> None:
        """成功记录写入 SQLite 历史库并刷新历史表格。

        参数：result: 脚本执行结果。
        """
        self._db.add_record(
            category="audio", script_key=self._current_key,
            prompt=self._text.toPlainText(),
            params=dict(self._last_params),   # §7：历史记录含实际参数
            files=result.files, ok=True, elapsed=result.elapsed,
        )
        self._refresh_history()

    def _write_fail_history(self, result: RunResult) -> None:
        """失败记录写入 SQLite 历史库（含错误码/信息）并刷新。

        参数：result: 脚本执行结果。
        """
        self._db.add_record(
            category="audio", script_key=self._current_key,
            prompt=self._text.toPlainText(),
            params=dict(self._last_params),   # 失败记录也保留参数
            files=[],
            ok=False, code=result.code, message=result.message,
            elapsed=result.elapsed,
        )
        self._refresh_history()

    def _refresh_history(self) -> None:
        """从历史库读取最近 20 条语音记录，重新渲染历史表格。"""
        records = self._db.list_records(category="audio", limit=20)
        self._hist.load_records(records)

    def _play_hist(self, index: int) -> None:
        """播放历史语音：加载产物并用系统播放器打开，同时回显文本。

        参数：index: 历史表格行索引。
        """
        records = self._hist.records()
        if not (0 <= index < len(records)):
            return
        record = records[index]
        files = record.get("files") or []
        if files and Path(files[0]).exists():
            self._player.load(files[0])
            self._player.open_external()
        self._echo.set_text(record.get("prompt", ""))
        self._main.show_status("已播放历史语音", 2500)

    def _navigate_hist(self, step: int) -> None:
        """播放器的上一首/下一首：在历史记录范围内按 step 偏移并播放。

        找不到可播放的相邻记录（越界或产物缺失）时提示后停留原地。

        参数：step: 偏移量（-1 上一条 / +1 下一条）。
        """
        records = self._hist.records()
        if not records:
            self._main.show_status("暂无历史记录可切换", 2500)
            return
        # 以当前加载的文件在历史中定位；找不到从头开始
        cur = self._player.current_file()
        idx = next(
            (i for i, r in enumerate(records)
             if (r.get("files") or []) and r["files"][0] == cur),
            0,
        )
        target = idx + step
        # 在范围内找第一条"产物存在"的记录（跳过失败/文件丢失条目）
        while 0 <= target < len(records):
            files = records[target].get("files") or []
            if files and Path(files[0]).exists():
                self._player.load(files[0])
                self._echo.set_text(records[target].get("prompt", ""))
                self._main.show_status(
                    f"已切换到第 {target + 1} 条历史语音", 2000)
                return
            target += step
        self._main.show_status("没有更多可播放的历史语音", 2500)

    def _show_fail_detail(self, index: int) -> None:
        """查看失败详情：在状态栏显示该条记录的错误码与错误信息。

        参数：index: 历史表格行索引。
        """
        records = self._hist.records()
        if not (0 <= index < len(records)):
            return
        record = records[index]
        self._main.show_status(
            f"失败：{record.get('code', '')} {record.get('message', '')}", 5000)

    def _open_output_dir(self) -> None:
        """用系统文件管理器打开语音输出根目录 output/audio/。"""
        paths.OUTPUT_AUDIO_DIR.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(
            QUrl.fromLocalFile(str(paths.OUTPUT_AUDIO_DIR)))
