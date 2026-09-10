"""智能导入页（还原预览文档 page-import）。

用户把 API 接入文档粘贴进来，程序调用 LLM 自动生成制式脚本。
界面分三块：顶部说明横幅、LLM 配置卡片（API 地址/密钥/模型名，
保存到 data/config.json 复用）、文档粘贴卡片；下方是进度区
（进度条 + 流式日志区）。

导入流程（本页核心链路）：
  _start_import 校验输入 → ImportWorker（QThread 后台线程）跑
  import_from_document 管线 → 过程中 log_line 信号逐行打日志、
  chunk_received 信号把 LLM 输出的增量文本实时追加到日志区
  （流式效果，让用户看到"AI 正在写字"）→ finished_import 信号
  回 UI 线程 → 完备性门闸（必要缺失阻断 / 非必要缺失可继续）→
  预览弹窗确认 → 脚本落盘 + 刷新注册表 + 各页下拉联动刷新。

M1：静态演示；M5：真实管线——LLM 配置持久化（data/config.json）、
粘贴文档 → ImportWorker 后台跑 import_from_document（进度日志）→
完备性门闸（必要阻断/非必要继续）→ 预览（真实脚本）→ 落盘 + 刷新注册表。
支持「演示模式」（Mock LLM），无 LLM KEY 也能完整走通导入链路。
"""

from PySide6.QtCore import Qt
from PySide6.QtGui import QTextCursor
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QFrame, QGroupBox, QHBoxLayout,
    QLabel, QLineEdit,
    QMessageBox, QProgressBar, QPushButton, QScrollArea, QPlainTextEdit,
    QVBoxLayout, QWidget,
)

from app import paths
from core.importer import (
    ImportResult,
    LLMConfig,
    load_llm_config,
    save_llm_config,
    save_scripts,
)
from core.importer.llm_client import test_llm_connection
from core.registry import ScriptRegistry, scan_scripts_dir
from ui.dialogs.confirm_dialog import GapOptionalDialog, GapRequiredDialog
from ui.dialogs.import_preview_dialog import ImportPreviewDialog, scripts_to_preview
from ui.workers import ImportWorker

IMP_STEPS = [
    (15, "🔍 检查文档完整性…"),
    (40, "🤖 调用 LLM 生成脚本…"),
    (70, "📝 解析并校验脚本…"),
    (90, "🔒 安全检查（清空 API KEY）…"),
]


class ImportPage(QWidget):
    """智能导入页：LLM 配置 + 文档粘贴 + 导入管线。

    导入任务交给 ImportWorker 后台线程，本页只负责收参数、
    显示进度、处理完成后的弹窗与落盘。
    """

    def __init__(self, main_window, registry: ScriptRegistry, parent=None) -> None:
        """构造智能导入页。

        参数：
            main_window: 主窗口引用（状态栏提示 / 页签跳转）
            registry: 脚本注册表（导入成功后重建 load）
        """
        super().__init__(parent)
        self._main = main_window
        self._registry = registry
        self._worker: ImportWorker | None = None  # 后台导入线程

        # 整页套滚动区（内容较多，窄窗口可上下滚动）
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        inner = QWidget()
        inner.setMaximumWidth(820)
        inner_layout = QVBoxLayout(inner)
        inner_layout.setContentsMargins(16, 12, 16, 12)
        inner_layout.setSpacing(10)

        inner_layout.addWidget(self._build_desc())
        inner_layout.addWidget(self._build_llm_card())
        inner_layout.addWidget(self._build_doc_card())

        # 开始按钮 + 状态文字一行
        start_row = QHBoxLayout()
        start_row.setSpacing(10)
        start_btn = QPushButton("📥 开始智能导入")
        start_btn.setProperty("class", "primary")
        start_btn.setStyleSheet("padding:8px 28px; font-size:14px;")
        # 信号槽：点击开始 → 启动导入管线
        start_btn.clicked.connect(self._start_import)
        self._status = QLabel("")
        self._status.setStyleSheet("font-size:12px; color:#888;")
        start_row.addWidget(start_btn)
        start_row.addWidget(self._status)
        start_row.addStretch(1)
        inner_layout.addLayout(start_row)

        inner_layout.addWidget(self._build_progress())
        inner_layout.addStretch(1)

        scroll.setWidget(inner)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(scroll)

        # 启动时把已保存的 LLM 配置回填到表单
        self._load_config_into_form()

    # ------------------------------------------------------------------
    # 构建
    # ------------------------------------------------------------------

    def _build_desc(self) -> QWidget:
        """构建顶部说明横幅（浅蓝底介绍文字）。

        返回：说明横幅 QWidget。
        """
        box = QFrame()
        box.setStyleSheet(
            "background:#f0f7ff; border:1px solid #b3d9f7; border-radius:1px;"
        )
        v = QVBoxLayout(box)
        v.setContentsMargins(12, 9, 12, 9)
        text = QLabel(
            "📥 <b>智能导入</b> — 粘贴 API 接入文档，LLM（提示词模板 "
            "<b>1.0.0</b>）生成制式脚本。导入前将进行完备性检查；"
            "必要项缺失仅可关闭，非必要项可继续默认。开启「演示模式」"
            "可不配置 LLM 密钥直接体验完整导入链路。"
        )
        text.setWordWrap(True)
        text.setStyleSheet("font-size:13px; border:none; background:transparent;")
        v.addWidget(text)
        return box

    def _build_llm_card(self) -> QGroupBox:
        """构建 LLM 配置卡片：API 地址 / 密钥（可显隐）/ 模型名 / 演示模式。

        返回：配置卡片 QGroupBox。
        """
        card = QGroupBox()
        v = QVBoxLayout(card)
        v.setSpacing(8)
        v.addWidget(self._card_title("LLM 配置", "（保存后自动复用）"))
        grid = QHBoxLayout()
        grid.setSpacing(8)

        # API 地址（独立 cell）
        url_cell = QWidget()
        uv = QVBoxLayout(url_cell)
        uv.setContentsMargins(0, 0, 0, 0)
        uv.setSpacing(2)
        uv.addWidget(self._mini_label("API 地址"))
        self._llm_url = QLineEdit()
        self._llm_url.setPlaceholderText("OpenAI 兼容接口地址，如 https://api.example.com/v1/chat/completions")
        uv.addWidget(self._llm_url)
        grid.addWidget(url_cell, stretch=1)

        # API 密钥：密码框 + 显示/隐藏切换按钮
        key_cell = QWidget()
        kv = QVBoxLayout(key_cell)
        kv.setContentsMargins(0, 0, 0, 0)
        kv.setSpacing(2)
        kv.addWidget(self._mini_label("API 密钥"))
        row = QHBoxLayout()
        row.setSpacing(4)
        self._imp_key = QLineEdit()
        self._imp_key.setPlaceholderText("粘贴 LLM API Key（演示模式可留空）")
        self._imp_key.setEchoMode(QLineEdit.EchoMode.Password)
        tog = QPushButton("显示")
        tog.setStyleSheet("font-size:11px; padding:2px 9px;")
        tog.clicked.connect(lambda: self._toggle_pwd(self._imp_key, tog))
        row.addWidget(self._imp_key, stretch=1)
        row.addWidget(tog)
        kv.addLayout(row)
        grid.addWidget(key_cell)

        # 模型名称（独立 cell）
        model_cell = QWidget()
        mv = QVBoxLayout(model_cell)
        mv.setContentsMargins(0, 0, 0, 0)
        mv.setSpacing(2)
        mv.addWidget(self._mini_label("模型名称"))
        self._llm_model = QLineEdit()
        self._llm_model.setPlaceholderText("模型名，如 gpt-4o")
        self._llm_model.setFixedWidth(170)
        mv.addWidget(self._llm_model)
        grid.addWidget(model_cell)

        # 保存 / 测试连接按钮
        save = QPushButton("💾 保存配置")
        save.setProperty("class", "primary")
        save.setStyleSheet("padding:0 12px; height:26px;")
        save.clicked.connect(self._save_config)
        grid.addWidget(save, alignment=Qt.AlignmentFlag.AlignBottom)

        test = QPushButton("🔌 测试连接")
        test.setStyleSheet("padding:0 12px; height:26px; font-size:12px;")
        test.clicked.connect(self._test_connection)
        grid.addWidget(test, alignment=Qt.AlignmentFlag.AlignBottom)

        v.addLayout(grid)

        # 演示模式勾选：不调真实 LLM，用内置 mock 输出走完整链路
        mock_row = QHBoxLayout()
        self._mock = QCheckBox("演示模式（Mock LLM，不调用真实接口）")
        self._mock.setStyleSheet("font-size:12px;")
        mock_row.addWidget(self._mock)
        mock_row.addStretch(1)
        v.addLayout(mock_row)

        # API 类别选择（用于加载专用提示词模板）
        cat_row = QHBoxLayout()
        cat_label = QLabel("API 类别：")
        cat_label.setStyleSheet("font-size:12px; font-weight:600; color:#555;")
        cat_row.addWidget(cat_label)
        self._api_cat = QComboBox()
        self._api_cat.setFixedWidth(150)
        # addItem(text, data)：data 作为业务值传给导入管线
        self._api_cat.addItem("🔄 通用（自动识别）", "")
        self._api_cat.addItem("🖼️ 生图片", "image")
        self._api_cat.addItem("🎬 生视频", "video")
        self._api_cat.addItem("🔊 生语音", "audio")
        self._api_cat.setStyleSheet("font-size:11px;")
        cat_row.addWidget(self._api_cat)
        cat_row.addStretch(1)
        v.addLayout(cat_row)
        return card

    def _build_doc_card(self) -> QGroupBox:
        """构建文档粘贴卡片：标题 + 清空按钮 + 大号粘贴框。

        返回：文档卡片 QGroupBox。
        """
        card = QGroupBox()
        v = QVBoxLayout(card)
        v.setSpacing(6)
        head = QHBoxLayout()
        head.addWidget(self._card_title("粘贴 API 接入文档", "", badge="2"))
        clear = QPushButton("清空")
        clear.setStyleSheet("font-size:11px; padding:2px 9px;")
        clear.clicked.connect(self._clear_doc)
        head.addStretch(1)
        head.addWidget(clear)
        v.addLayout(head)
        hint = QLabel("支持多模型/多能力文档；将分别生成独立脚本。")
        hint.setStyleSheet("font-size:12px; color:#666;")
        v.addWidget(hint)
        self._doc = QPlainTextEdit()
        self._doc.setPlaceholderText(
            "在此粘贴 API 接入文档（需含接口地址、认证方式、模型 ID）…")
        self._doc.setFixedHeight(160)
        # 等宽字体便于阅读接口文档
        self._doc.setStyleSheet(
            "font-family:Consolas, monospace; font-size:12px;"
        )
        v.addWidget(self._doc)
        return card

    def _build_progress(self) -> QWidget:
        """构建进度区：步骤文字 + 百分比 + 进度条 + 流式日志区（默认隐藏）。

        返回：进度区 QFrame（导入开始时才显示）。
        """
        self._prog_box = QFrame()
        self._prog_box.setStyleSheet(
            "background:#f6f8fa; border:1px solid #e0e0e0; border-radius:1px;"
        )
        self._prog_box.hide()
        v = QVBoxLayout(self._prog_box)
        v.setContentsMargins(12, 9, 12, 9)
        v.setSpacing(5)
        head = QHBoxLayout()
        self._step_label = QLabel("分析中…")
        self._step_label.setStyleSheet("font-size:12px; font-weight:600; border:none;")
        self._pct = QLabel("0%")
        self._pct.setStyleSheet("font-size:12px; color:#0078d4; border:none;")
        head.addWidget(self._step_label)
        head.addStretch(1)
        head.addWidget(self._pct)
        v.addLayout(head)
        # 细进度条（4px 高，不显示文字）
        self._bar = QProgressBar()
        self._bar.setFixedHeight(4)
        self._bar.setTextVisible(False)
        self._bar.setStyleSheet("background:#e0e0e0; border:none; border-radius:2px;")
        v.addWidget(self._bar)
        # 流式日志区：LLM 输出增量块实时显示的地方
        self._log = QPlainTextEdit()
        self._log.setReadOnly(True)
        self._log.setFixedHeight(150)   # 流式输出实时显示区（需足够高可见多行）
        self._log.setStyleSheet(
            "font-size:11px; color:#555; font-family:Consolas, monospace;"
            " border:1px solid #e0e0e0; border-radius:1px;"
            " background:#ffffff;"
        )
        v.addWidget(self._log)
        return self._prog_box

    # ------------------------------------------------------------------
    # 小控件
    # ------------------------------------------------------------------

    def _mini_label(self, text: str) -> QLabel:
        """构建小号加粗标签。

        参数：text: 标签文字。
        返回：QLabel。
        """
        lab = QLabel(text)
        lab.setStyleSheet("font-size:11px; font-weight:600; color:#555;")
        return lab

    def _card_title(self, title: str, hint: str = "", badge: str = "") -> QWidget:
        """构建卡片标题行：可选圆形数字徽标 + 标题 + 可选灰色提示。

        参数：
            title: 标题文字；hint: 灰色小字提示；badge: 圆形数字徽标（如 "1"）。
        返回：组装好的标题行 QWidget。
        """
        row = QHBoxLayout()
        row.setSpacing(7)
        if badge:
            b = QLabel(badge)
            b.setFixedSize(20, 20)
            b.setAlignment(Qt.AlignmentFlag.AlignCenter)
            b.setStyleSheet(
                "background:#0078d4; color:#ffffff; font-size:11px;"
                " border-radius:10px;"
            )
            row.addWidget(b)
        t = QLabel(title)
        t.setStyleSheet("font-size:13px; font-weight:600;")
        row.addWidget(t)
        if hint:
            h = QLabel(hint)
            h.setStyleSheet("font-size:11px; color:#888;")
            row.addWidget(h)
        row.addStretch(1)
        wrap = QWidget()
        wrap.setLayout(row)
        return wrap

    def _toggle_pwd(self, edit: QLineEdit, btn: QPushButton) -> None:
        """切换密码框显隐：显示 ←→ 隐藏，按钮文字随之变化。

        参数：edit: 目标密码框；btn: 触发切换的按钮。
        """
        hidden = edit.echoMode() == QLineEdit.EchoMode.Password
        edit.setEchoMode(QLineEdit.EchoMode.Normal if hidden else QLineEdit.EchoMode.Password)
        btn.setText("隐藏" if hidden else "显示")

    # ------------------------------------------------------------------
    # LLM 配置（data/config.json）
    # ------------------------------------------------------------------

    def _load_config_into_form(self) -> None:
        """从 data/config.json 读取 LLM 配置回填到表单。"""
        cfg = load_llm_config(paths.CONFIG_FILE)
        self._llm_url.setText(cfg.api_url)
        self._imp_key.setText(cfg.api_key)
        self._llm_model.setText(cfg.model)
        self._mock.setChecked(cfg.mock)

    def _current_config(self) -> LLMConfig:
        """收集当前表单 → LLMConfig 对象（不预填、不猜默认值，空就是空）。

        返回：LLMConfig。
        """
        return LLMConfig(
            api_url=self._llm_url.text().strip(),
            api_key=self._imp_key.text().strip(),
            model=self._llm_model.text().strip(),
            mock=self._mock.isChecked(),
        )

    def _save_config(self) -> None:
        """把当前表单保存到 data/config.json，状态栏提示成功。"""
        save_llm_config(paths.CONFIG_FILE, self._current_config())
        self._main.show_status("✅ LLM 配置已保存", 2500)

    def _test_connection(self) -> None:
        """发一个最小请求测试 LLM 连通性，弹窗显示分类结果。"""
        cfg = self._current_config()
        if cfg.mock:
            QMessageBox.information(self, "测试连接", "当前为演示模式，无需连接真实 LLM。")
            return
        if not cfg.api_key.strip():
            QMessageBox.warning(self, "测试连接", "请先填写 LLM API 密钥（演示模式可留空）。")
            return
        self._status.setText("测试连接中…")
        QApplication.processEvents()
        ok, msg = test_llm_connection(cfg)
        self._status.setText("")
        if ok:
            QMessageBox.information(self, "测试连接", msg)
        else:
            QMessageBox.warning(self, "测试连接", msg)

    def _clear_doc(self) -> None:
        """清空文档粘贴框；内容非空时先弹确认框防误删。"""
        if self._doc.toPlainText().strip():
            if QMessageBox.question(self, "确认", "确定清空已粘贴的 API 文档？") == QMessageBox.StandardButton.Yes:
                self._doc.clear()

    # ------------------------------------------------------------------
    # 导入流程
    # ------------------------------------------------------------------

    def _start_import(self) -> None:
        """启动导入：校验输入 → 显示进度区 → ImportWorker 后台跑管线。

        三个信号各司其职：
          log_line      → 逐行进度日志追加到日志区
          chunk_received→ LLM 输出增量块实时追加（流式效果）
          finished_import→ 导入结束后的门闸/预览/落盘
        """
        doc = self._doc.toPlainText().strip()
        if not doc:
            QMessageBox.warning(self, "提示", "请先粘贴 API 接入文档")
            return
        cfg = self._current_config()
        if not cfg.mock and not cfg.api_key.strip():
            QMessageBox.warning(self, "提示", "请填写 LLM API 密钥，或开启「演示模式」")
            return

        # 复位进度区并显示
        self._log.clear()
        self._prog_box.show()
        self._status.setText("导入中…")
        self._bar.setValue(5)
        self._pct.setText("5%")
        self._step_label.setText("开始导入…")
        self._append_log("📥 开始智能导入（演示模式）" if cfg.mock else "📥 开始智能导入")

        # 后台线程执行完整导入管线（LLM 调用可能很慢，绝不能卡 UI 线程）
        worker = ImportWorker(doc, cfg, paths.TEMPLATES_DIR, paths.SCRIPTS_DIR,
                              category=self._api_cat.currentData(),
                              parent=self)
        worker.log_line.connect(self._append_log)             # 日志 → 日志区
        worker.chunk_received.connect(self._on_llm_chunk)     # 流式块 → 实时追加
        worker.finished_import.connect(self._on_import_done)  # 完成 → 门闸/预览
        worker.finished.connect(worker.deleteLater)
        self._worker = worker
        worker.start()

    def _append_log(self, msg: str) -> None:
        """追加一行进度日志，并让进度条随之推进（封顶 95%）。

        参数：msg: 一行日志文本。
        """
        self._log.appendPlainText(msg)
        # 粗略进度：每行日志推进（封顶 95）
        self._bar.setValue(min(95, self._bar.value() + 12))
        self._pct.setText(f"{min(95, self._bar.value())}%")

    def _on_llm_chunk(self, text: str) -> None:
        """LLM 输出增量块：实时追加显示（不换行）+ 进度条跳动。

        这是"流式输出"的关键回调：ImportWorker 在后台每收到一小段
        LLM 文本就通过 chunk_received 信号发过来，本方法把光标移到
        日志区末尾原样插入，用户就能看到脚本内容逐渐"打"出来。

        参数：text: 本次收到的增量文本片段。
        """
        # 首次收到块时把光标移到末尾，连续追加
        self._log.moveCursor(QTextCursor.MoveOperation.End)
        self._log.insertPlainText(text)
        self._log.ensureCursorVisible()
        # 进度条随输出跳动，让用户看到"活着"的生成过程
        self._bar.setValue(min(92, self._bar.value() + 1))
        self._pct.setText(f"{min(92, self._bar.value())}%")
        if not self._step_label.text().startswith("🤖"):
            self._step_label.setText("🤖 LLM 正在生成脚本…")

    def _on_import_done(self, result: ImportResult) -> None:
        """导入完成回调（UI 线程）：走完备性门闸决定下一步。

        失败 → 弹窗显示错误（附 LLM 原始输出预览）；必要项缺失 → 阻断弹窗；
        非必要项缺失 → 可选择继续；都通过 → 直接进入预览。

        参数：result: 导入管线结果（ImportResult）。
        """
        self._worker_result = result
        self._bar.setValue(100)
        self._pct.setText("100%")
        self._step_label.setText("✨ 完成" if result.ok else "✕ 失败")

        if not result.ok:
            self._status.setText("")
            detail = result.error or "未知错误"
            if result.llm_output:
                preview = result.llm_output[:300].replace("\n", " ")
                QMessageBox.warning(
                    self, "导入失败",
                    f"{detail}\n\n—— LLM 原始输出预览 ——\n{preview}")
            else:
                QMessageBox.warning(self, "导入失败", detail)
            return

        # 完备性门闸：必要项缺失 → 仅可关闭（阻断导入）
        if result.required_missing:
            GapRequiredDialog(self, gaps=result.required_missing).exec()
            self._status.setText("必要信息缺失，请补充文档后重试")
            return
        # 非必要项缺失 → 弹窗让用户选择"继续（使用默认参数）"
        if result.optional_missing:
            GapOptionalDialog(
                self, on_continue=self._show_preview,
                gaps=result.optional_missing).exec()
            return
        self._show_preview(result)

    def _show_preview(self, result: ImportResult | None = None) -> None:
        """弹出导入预览；用户确认后落盘脚本并联动刷新其他页。

        参数：result: 导入结果；None 时取上次保存的 _worker_result
              （GapOptionalDialog"继续"回调走这条路径）。
        """
        if result is None:
            result = getattr(self, "_worker_result", None)
        if result is None:
            return
        dlg = ImportPreviewDialog(
            self, scripts=scripts_to_preview(result.scripts))
        if not dlg.exec():
            self._status.setText("已取消导入")
            return
        # 落盘 + 刷新注册表 + 刷新各页下拉 + 跳转设置页
        saved = save_scripts(result, paths.SCRIPTS_DIR)
        self._registry.load(scan_scripts_dir(paths.SCRIPTS_DIR))
        # 刷新设置页脚本列表
        main = self._main
        main.tab_widget.widget(main.TAB_SETTINGS).refresh()
        # 刷新三个生成页脚本下拉
        for tab in (main.TAB_IMAGE, main.TAB_VIDEO, main.TAB_AUDIO):
            page = main.tab_widget.widget(tab)
            if hasattr(page, "refresh_scripts"):
                page.refresh_scripts()
        # 状态栏右侧"脚本：N 个"同步刷新（原实现只在启动时算一次）
        main.refresh_status_info()
        self._status.setText(f"✅ 已导入 {len(saved)} 个脚本")
        self._main.show_status(f"已导入 {len(saved)} 个脚本，请在模型设置填写 API KEY", 4000)
        QMessageBox.information(
            self, "AI Creative Studio",
            f"✅ 导入成功！共 {len(saved)} 个脚本已写入 scripts/。\n"
            "请在「模型设置」为各脚本填写 API KEY。\n"
            "外部依赖脚本请到「关于 → 安装依赖项」安装。",
        )
        # 自动跳转到模型设置页，引导用户填写 KEY
        self._main.switch_tab(self._main.TAB_SETTINGS)
