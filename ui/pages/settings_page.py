"""模型设置页（还原预览文档 page-settings）。

界面布局：顶部工具栏（新增/删除/脚本目录/刷新 + 计数），
下方左右分栏——左侧脚本列表（名称 + 类型徽标 + 类别筛选页签），
右侧选中脚本的 API KEY 输入面板 + 可折叠的脚本代码编辑区。

本页职责：
  - 从注册表 + 脚本文件实时构建脚本列表；
  - API KEY 经 core/keys.inject_key 真正写入脚本文件（无需手动改代码）；
  - 代码区可展开查看/编辑并保存回文件；
  - 删除走"移入回收站目录 data/trash/"软删除，可手动恢复；
  - 刷新时重扫 scripts/ 目录并联动刷新三个生成页的下拉列表。

M1：静态占位数据；M4：脚本列表从注册表 + 脚本文件实时构建，
API KEY 经 core/keys.inject_key 真正写入脚本，代码编辑可保存回文件，
删除走"移入回收站目录"软删除，刷新重扫注册表。
"""

import shutil
from pathlib import Path

from PySide6.QtCore import QUrl, Qt
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QFrame, QGroupBox, QHBoxLayout, QLabel, QMessageBox, QPlainTextEdit,
    QPushButton, QScrollArea, QSplitter, QVBoxLayout, QWidget,
)

from app import paths
from core import keys
from core.registry import ScriptRegistry, scan_scripts_dir
from ui.widgets import KeyInputPanel

# 类型徽标配色（按"图片/视频/语音"分类着色）
BADGE_STYLE = {
    "图片": "background:#e3f2fd; color:#1565c0;",
    "视频": "background:#f3e5f5; color:#6a1b9a;",
    "语音": "background:#e8f5e9; color:#2e7d32;",
}
# 筛选页签 + 英文类别 → 中文徽标映射
FILTERS = ["全部", "图片", "视频", "语音"]
BADGE_MAP = {"image": "图片", "video": "视频", "audio": "语音"}
# 软删除回收站目录：删除的脚本移到这里，可手动恢复
TRASH_DIR = paths.DATA_DIR / "trash"


class _ClickableRow(QWidget):
    """可点击行基类：规范的 mousePressEvent 子类化实现（替代实例级覆盖）。

    子类设置 clicked_callback，左键点击时触发；事件继续向上传播。
    """

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.clicked_callback = None   # 点击回调（宿主设置）

    def mousePressEvent(self, event) -> None:  # noqa: N802（Qt 命名）
        """左键点击 → 触发宿主注入的回调（Qt 事件回调，规范子类化）。"""
        if event.button() == Qt.MouseButton.LeftButton and self.clicked_callback:
            self.clicked_callback()
        super().mousePressEvent(event)


class _ScriptRow(_ClickableRow):
    """脚本列表行：单选圆点 + 名称 + 类型徽标。

    自绘的一行控件（非标准列表项），点击时由 SettingsPage 接管选中逻辑。
    """

    def __init__(self, data: dict, parent=None) -> None:
        """构建一行。

        参数：data: 脚本数据字典（含 name 名称 / badge 类型徽标文字）。
        """
        super().__init__(parent)
        self.data = data
        self.setFixedHeight(34)
        # 行样式：底部分隔线 + 悬停浅色 + 选中浅蓝
        self._base = (
            "QFrame#row{border-bottom:1px solid #f0f0f0;}"
            "QFrame#row:hover{background:#f5f8fc;}"
            "QFrame#row.sel{background:#e5f1fb;}"
        )
        self.setStyleSheet(self._base)
        self.setObjectName("row")

        from PySide6.QtWidgets import QGridLayout

        grid = QGridLayout(self)
        grid.setContentsMargins(8, 0, 8, 0)
        grid.setHorizontalSpacing(6)

        # 左侧单选圆点（选中时呈蓝色实心）
        self._dot = QFrame()
        self._dot.setFixedSize(12, 12)
        self._dot.setStyleSheet(
            "border:1.5px solid #b0b0b0; border-radius:6px; background:transparent;"
        )
        self._name = QLabel(data["name"])
        self._name.setStyleSheet("font-weight:600; border:none;")
        self._name.setWordWrap(False)
        # 右侧类型徽标（图片/视频/语音）
        badge = QLabel(data["badge"])
        badge.setStyleSheet(
            f"padding:1px 5px; font-size:10px; font-weight:600; "
            f"border-radius:2px; {BADGE_STYLE[data['badge']]}"
        )

        grid.addWidget(self._dot, 0, 0)
        grid.addWidget(self._name, 0, 1)
        grid.addWidget(badge, 0, 2, alignment=Qt.AlignmentFlag.AlignRight)
        grid.setColumnStretch(1, 1)

    def set_selected(self, on: bool) -> None:
        """切换选中态：圆点变蓝实心、整行浅蓝背景。

        参数：on: True=选中，False=取消选中。
        """
        self._dot.setStyleSheet(
            "border:1.5px solid #0078d4; border-radius:6px;"
            " background:transparent;"
            if not on else
            "border:1.5px solid #0078d4; border-radius:6px;"
            " background:qradialgradient(cx:0.5, cy:0.5, radius:0.4,"
            " fx:0.5, fy:0.5, stop:0 #0078d4, stop:0.55 transparent, stop:1 transparent);"
        )
        self.setStyleSheet(self._base + ("QFrame#row{background:#e5f1fb;}" if on else ""))


class SettingsPage(QWidget):
    """模型设置页：脚本管理 + API KEY 注入 + 代码查看编辑。"""

    def __init__(self, main_window, registry: ScriptRegistry,
                 parent=None) -> None:
        """构造模型设置页。

        参数：
            main_window: 主窗口引用（状态栏提示 / 联动刷新生成页）
            registry: 脚本注册表（列表数据来源）
        """
        super().__init__(parent)
        self._main = main_window
        self._registry = registry
        self._scripts: list[dict] = []  # 脚本数据列表（见 _collect_scripts）
        self._current = 0               # 当前选中索引
        self._code_open = False         # 代码编辑区是否展开
        self._filter = "全部"           # 当前类别筛选

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        outer.addWidget(self._build_toolbar())

        # 左右分栏：左列表（1）右编辑区（2）
        split = QSplitter(Qt.Orientation.Horizontal)
        split.addWidget(self._build_list())
        split.addWidget(self._build_editor())
        split.setStretchFactor(0, 1)
        split.setStretchFactor(1, 2)
        split.setHandleWidth(1)
        outer.addWidget(split, stretch=1)

        self._rebuild_list()
        self._load_script(0)

    def refresh(self) -> None:
        """导入新脚本后重建列表（由 import_page 导入完成后调用）。"""
        self._rebuild_list()
        self._load_script(0)

    # ------------------------------------------------------------------
    # 数据（注册表 + 脚本文件实时构建）
    # ------------------------------------------------------------------

    def _collect_scripts(self) -> list[dict]:
        """从注册表 + 脚本文件构建真实列表（含当前 KEY 与代码内容）。

        每个脚本一条字典：路径/绝对路径/模板版本/KEY/名称/徽标/代码全文。
        返回：脚本数据字典列表。
        """
        if self._registry is None:
            return []
        data: list[dict] = []
        for meta in self._registry.all:
            abs_path = paths.SCRIPTS_DIR / meta.file_path
            if not abs_path.exists():
                continue
            data.append({
                "path": meta.file_path,
                "abs_path": str(abs_path),
                "tpl": meta.template_version,
                "key": keys.read_key(abs_path),
                "name": meta.display_name,
                "badge": BADGE_MAP.get(meta.category.value, "图片"),
                "code": abs_path.read_text(encoding="utf-8", errors="replace"),
            })
        return data

    # ------------------------------------------------------------------
    # 构建
    # ------------------------------------------------------------------

    def _build_toolbar(self) -> QWidget:
        """构建顶部工具栏：新增/删除/脚本目录/刷新按钮 + 脚本计数。

        返回：工具栏 QWidget。
        """
        bar = QWidget()
        bar.setFixedHeight(34)
        bar.setStyleSheet("background:#f6f6f6; border-bottom:1px solid #d4d4d4;")
        row = QHBoxLayout(bar)
        row.setContentsMargins(7, 0, 7, 0)
        row.setSpacing(4)

        add = QPushButton("＋ 新增")
        add.setStyleSheet("font-size:11px; padding:2px 9px;")
        # 信号槽：点新增 → 跳转到智能导入页（§3.4"引导走智能导入"）
        add.clicked.connect(lambda: self._main.switch_tab(self._main.TAB_IMPORT))
        dele = QPushButton("✕ 删除")
        dele.setProperty("class", "danger")
        dele.setStyleSheet("font-size:11px; padding:2px 9px;")
        dele.clicked.connect(self._confirm_delete)
        sep = QFrame()
        sep.setFixedSize(1, 13)
        sep.setStyleSheet("background:#d4d4d4; border:none;")
        folder = QPushButton("📁 脚本目录")
        folder.setStyleSheet("font-size:11px; padding:2px 9px;")
        folder.clicked.connect(self._open_scripts_dir)
        refresh = QPushButton("🔄 刷新")
        refresh.setStyleSheet("font-size:11px; padding:2px 9px;")
        refresh.clicked.connect(self._refresh)
        self._count_label = QLabel("共 0 个脚本")
        self._count_label.setStyleSheet("font-size:11px; color:#888; border:none;")

        row.addWidget(add)
        row.addWidget(dele)
        row.addWidget(sep)
        row.addWidget(folder)
        row.addWidget(refresh)
        row.addStretch(1)
        row.addWidget(self._count_label)
        return bar

    def _build_list(self) -> QWidget:
        """构建左侧脚本列表：类别筛选页签 + 表头 + 可滚动行区。

        返回：左栏 QWidget。
        """
        col = QWidget()
        v = QVBoxLayout(col)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0)

        # 类别筛选页签（全部/图片/视频/语音）
        tabs = QWidget()
        th = QHBoxLayout(tabs)
        th.setContentsMargins(0, 0, 0, 0)
        self._tab_btns = []
        for name in FILTERS:
            t = QPushButton(name)
            t.setCheckable(True)
            t.setChecked(name == "全部")
            t.clicked.connect(lambda _=False, n=name: self._set_filter(n))
            self._tab_btns.append(t)
            th.addWidget(t)
        tabs.setStyleSheet("background:#f6f6f6; border-bottom:1px solid #d4d4d4;")
        v.addWidget(tabs)

        # 表头
        hdr = QWidget()
        hdr.setFixedHeight(24)
        hdr.setStyleSheet("background:#f0f0f0;")
        hh = QHBoxLayout(hdr)
        hh.setContentsMargins(8, 0, 8, 0)
        lab = QLabel("脚本名称")
        lab.setStyleSheet("font-size:11px; color:#666; font-weight:600; border:none;")
        hh.addWidget(lab, stretch=1)
        hh.addWidget(QLabel("类型"))
        v.addWidget(hdr)

        # 可滚动的脚本行容器
        self._list_scroll = QScrollArea()
        self._list_scroll.setWidgetResizable(True)
        self._list_scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        inner = QWidget()
        self._list_inner = QVBoxLayout(inner)
        self._list_inner.setContentsMargins(0, 0, 0, 0)
        self._list_inner.setSpacing(0)
        self._rows: list[_ScriptRow] = []
        self._list_scroll.setWidget(inner)
        v.addWidget(self._list_scroll, stretch=1)
        return col

    def _build_editor(self) -> QWidget:
        """构建右侧编辑区：KEY 面板 + 折叠按钮 + 代码区 + KEY 状态栏。

        返回：右栏 QWidget。
        """
        col = QWidget()
        v = QVBoxLayout(col)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0)

        # API KEY 输入面板（确认后真写入脚本文件）
        self._key_panel = KeyInputPanel()
        # 信号槽：点确定 → 调 core/keys 写入 KEY
        self._key_panel.key_confirmed.connect(self._confirm_key)
        v.addWidget(self._key_panel)

        # 折叠条：展开/收起代码编辑区 + 保存按钮
        fold = QWidget()
        fold.setFixedHeight(32)
        fold.setStyleSheet("background:#f6f6f6; border-bottom:1px solid #e0e0e0;")
        fh = QHBoxLayout(fold)
        fh.setContentsMargins(12, 0, 12, 0)
        fh.setSpacing(8)
        self._fold_btn = QPushButton("▶ 展开脚本代码")
        self._fold_btn.setStyleSheet("font-size:11px; padding:2px 9px;")
        self._fold_btn.clicked.connect(self._toggle_code)
        fh.addWidget(self._fold_btn)
        fh.addWidget(QLabel("默认折叠 · 高级用户可展开编辑"))
        fh.addStretch(1)
        self._save_btn = QPushButton("💾 保存")
        self._save_btn.setProperty("class", "primary")
        self._save_btn.setStyleSheet("font-size:11px; padding:2px 9px;")
        self._save_btn.clicked.connect(self._save_code)
        self._save_btn.hide()
        fh.addWidget(self._save_btn)
        v.addWidget(fold)

        # 代码编辑区（深色主题等宽字体，默认隐藏）
        self._code = QPlainTextEdit()
        self._code.setStyleSheet(
            "background:#1e1e1e; color:#d4d4d4; border:none;"
            " font-family:Consolas, monospace; font-size:12px;"
        )
        self._code.hide()
        v.addWidget(self._code, stretch=1)

        # 底部状态栏：KEY 是否已填写
        foot = QWidget()
        foot.setFixedHeight(24)
        foot.setStyleSheet("background:#f6f6f6; border-top:1px solid #d4d4d4;")
        fh2 = QHBoxLayout(foot)
        fh2.setContentsMargins(10, 0, 10, 0)
        self._key_status = QLabel("⚠ API KEY 尚未填写")
        self._key_status.setStyleSheet("font-weight:600; color:#e65100; border:none;")
        fh2.addWidget(self._key_status)
        fh2.addStretch(1)
        fh2.addWidget(QLabel("Python · UTF-8"))
        v.addWidget(foot)
        return col

    # ------------------------------------------------------------------
    # 列表
    # ------------------------------------------------------------------

    def _rebuild_list(self) -> None:
        """重建行 + 更新计数 + 应用当前筛选。

        先清空旧行再逐条重建；无脚本时显示引导文案。
        """
        self._scripts = self._collect_scripts()
        self._count_label.setText(f"共 {len(self._scripts)} 个脚本")

        # 清空旧行控件
        while self._list_inner.count():
            item = self._list_inner.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self._rows = []
        # 逐条重建；通过子类化回调绑定点击（不再覆盖实例事件方法）
        for i, data in enumerate(self._scripts):
            row = _ScriptRow(data)
            row.clicked_callback = (lambda idx=i: self._pick(idx))
            self._rows.append(row)
            self._list_inner.addWidget(row)
        self._list_inner.addStretch(1)

        if self._scripts:
            self._apply_filter()
        else:
            empty = QLabel("scripts/ 目录暂无脚本\n请使用「智能导入」添加")
            empty.setStyleSheet("color:#999; font-size:12px; border:none; padding:12px;")
            self._list_inner.insertWidget(0, empty)

    def _apply_filter(self) -> None:
        """按当前筛选（全部/图片/视频/语音）显隐各行。"""
        for i, data in enumerate(self._scripts):
            self._rows[i].setVisible(
                self._filter == "全部" or data["badge"] == self._filter)

    def _set_filter(self, name: str) -> None:
        """切换筛选页签：高亮被点页签并应用筛选。

        参数：name: 页签文字（"全部"/"图片"/"视频"/"语音"）。
        """
        self._filter = name
        for b in self._tab_btns:
            b.setChecked(b.text() == name)
            b.setStyleSheet(
                "font-size:12px; font-weight:600; border:none; border-bottom:2px solid "
                + ("#0078d4;" if b.text() == name else "transparent;")
                + " background:" + ("#ffffff;" if b.text() == name else "#f6f6f6;")
                + " color:" + ("#0078d4;" if b.text() == name else "#555;")
            )
        if self._scripts:
            self._apply_filter()

    def _pick(self, index: int) -> None:
        """点击某行：选中高亮并加载该脚本到右侧编辑区。

        代码区已展开且有未保存修改时先询问是否丢弃（没改过不打扰）。

        参数：index: 行索引。
        """
        if self._code_open and self._code_dirty():
            if QMessageBox.question(
                self, "确认", "代码区有未保存修改，切换将丢弃？"
            ) != QMessageBox.StandardButton.Yes:
                return
            self._toggle_code()
        for i, row in enumerate(self._rows):
            row.set_selected(i == index)
        self._load_script(index)

    def _code_dirty(self) -> bool:
        """代码区当前内容是否相对已加载脚本有修改（未保存）。"""
        if not self._scripts or self._current >= len(self._scripts):
            return False
        return self._code.toPlainText() != self._scripts[self._current]["code"]

    def _load_script(self, index: int) -> None:
        """把指定脚本加载到右侧：KEY 面板回显 + 代码区填充。

        参数：index: 脚本索引（越界自动收敛到有效范围）。
        """
        if not self._scripts:
            self._key_panel.load_script("（无脚本）", "-", False, "")
            self._code.clear()
            self._key_status.setText("⚠ 无脚本可配置")
            self._key_status.setStyleSheet("font-weight:600; color:#e65100; border:none;")
            return
        index = max(0, min(index, len(self._scripts) - 1))
        self._current = index
        data = self._scripts[index]
        filled = bool(data["key"].strip())
        self._key_panel.load_script(
            data["path"], data["tpl"], filled, current_key=data["key"])
        self._code.setPlainText(data["code"])
        self._refresh_key_status()

    def _refresh_key_status(self) -> None:
        """刷新底部 KEY 状态文字与颜色（已填=绿，未填=橙）。"""
        if not self._scripts:
            return
        data = self._scripts[self._current]
        filled = bool(data["key"].strip())
        self._key_status.setText(self._key_panel.status_text(filled))
        self._key_status.setStyleSheet(
            f"font-weight:600; color:{self._key_panel.status_color(filled)}; border:none;"
        )

    # ------------------------------------------------------------------
    # KEY 注入（M4：真落盘）
    # ------------------------------------------------------------------

    def _confirm_key(self, value: str) -> None:
        """KEY 面板点确定：调用 core/keys.inject_key 真正写入脚本文件。

        写入后同步更新内存数据与代码区显示；空值表示清空 KEY。

        参数：value: 用户输入的 KEY（可为空=清空）。
        """
        if not self._scripts:
            return
        data = self._scripts[self._current]
        ok = keys.inject_key(data["abs_path"], value)
        if not ok:
            QMessageBox.warning(self, "写入失败", f"无法写入脚本：{data['path']}")
            return
        # 更新内存数据 + 界面
        data["key"] = value.strip()
        data["code"] = Path(data["abs_path"]).read_text(
            encoding="utf-8", errors="replace")
        self._code.setPlainText(data["code"])
        self._refresh_key_status()
        msg = ("✅ API KEY 已写入脚本（无需展开代码）" if value.strip()
               else "✅ 已清空脚本内 API KEY")
        self._main.show_status(f"API KEY 已更新：{data['name']}", 3000)
        QMessageBox.information(self, "AI Creative Studio", msg)

    # ------------------------------------------------------------------
    # 代码编辑（M4：真保存）
    # ------------------------------------------------------------------

    def _toggle_code(self) -> None:
        """展开/收起代码编辑区，按钮文字与保存按钮同步显隐。"""
        self._code_open = not self._code_open
        self._code.setVisible(self._code_open)
        self._fold_btn.setText("▼ 折叠脚本代码" if self._code_open else "▶ 展开脚本代码")
        self._save_btn.setVisible(self._code_open)

    def _save_code(self) -> None:
        """把代码编辑区内容写回脚本文件，并重读 KEY 状态（可能改了 KEY 行）。"""
        if not self._scripts:
            return
        data = self._scripts[self._current]
        try:
            Path(data["abs_path"]).write_text(
                self._code.toPlainText(), encoding="utf-8")
        except OSError as exc:
            QMessageBox.warning(self, "保存失败", str(exc))
            return
        # 代码可能改了 KEY 行，重读 KEY 状态
        data["key"] = keys.read_key(data["abs_path"])
        data["code"] = self._code.toPlainText()
        self._refresh_key_status()
        self._main.show_status(f"✅ 脚本已保存：{data['name']}", 3000)

    # ------------------------------------------------------------------
    # 删除 / 刷新 / 目录
    # ------------------------------------------------------------------

    def _confirm_delete(self) -> None:
        """删除当前脚本：确认后移入回收站目录 data/trash/（软删除，可恢复）。"""
        if not self._scripts:
            return
        data = self._scripts[self._current]
        if QMessageBox.question(
            self, "确认",
            f"删除脚本「{data['name']}」？\n将移入回收站目录 data/trash/，可手动恢复。",
        ) != QMessageBox.StandardButton.Yes:
            return
        TRASH_DIR.mkdir(parents=True, exist_ok=True)
        try:
            dest = TRASH_DIR / Path(data["abs_path"]).name
            shutil.move(data["abs_path"], dest)
        except OSError as exc:
            QMessageBox.warning(self, "删除失败", str(exc))
            return
        self._main.show_status(f"已删除（移入回收站）：{data['name']}", 3000)
        self._refresh()
        # 同步刷新三个生成页的脚本下拉
        main = self._main
        for tab in (main.TAB_IMAGE, main.TAB_VIDEO, main.TAB_AUDIO):
            page = main.tab_widget.widget(tab)
            if hasattr(page, "refresh_scripts"):
                page.refresh_scripts()

    def _refresh(self) -> None:
        """重扫 scripts/ 更新注册表，重建列表，同步刷新生成页下拉。"""
        self._registry.load(scan_scripts_dir(paths.SCRIPTS_DIR))
        self._rebuild_list()
        if self._scripts:
            self._load_script(0)
        # 同步刷新三个生成页的脚本下拉
        main = self._main
        for tab in (main.TAB_IMAGE, main.TAB_VIDEO, main.TAB_AUDIO):
            page = main.tab_widget.widget(tab)
            if hasattr(page, "refresh_scripts"):
                page.refresh_scripts()
        # 状态栏右侧"脚本：N 个"同步刷新（删除/刷新后数字会变化）
        main.refresh_status_info()
        self._main.show_status("已刷新脚本列表", 2000)

    def _open_scripts_dir(self) -> None:
        """用系统文件管理器打开 scripts/ 目录。"""
        paths.SCRIPTS_DIR.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(paths.SCRIPTS_DIR)))
