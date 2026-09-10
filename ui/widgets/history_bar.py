"""历史记录控件：缩略图条（图/视频）+ 表格（语音）。

包含两个控件：
  - HistoryStrip：横向缩略图历史条。图片模式 48×48 可点击（回看提示词）；
    视频模式 80×50 + "▶ 播放"按钮（用系统播放器打开产物）。失败记录灰显。
  - HistoryTable：语音历史表格（名称 / 时长·状态 / 操作按钮），
    成功行"▶ 播放"、失败行"详情"。

两个控件都只负责展示与发信号（item_clicked / item_play_requested /
row_clicked / detail_requested），业务处理（播放文件、回显提示词等）
由宿主页面连接信号后实现。

M3：支持 load_records() 从 HistoryDatabase 的记录加载。
每条记录字段：prompt（提示词回看）、files（产物播放）、ok/code/message（失败详情）。
点击/播放时发出索引，宿主页面从 records() 取数据。
"""

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QHeaderView, QLabel, QPushButton, QTableWidget,
    QTableWidgetItem, QVBoxLayout, QWidget,
)

# 占位缩略图的渐变背景色（6 色循环，无图时也有观感）
_PLACEHOLDER = [
    "qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #e8e8e8, stop:1 #c8c8c8)",
    "qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #d5e5f0, stop:1 #a8c8e0)",
    "qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #e0d8e8, stop:1 #c0b0d0)",
    "qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #d8e8d5, stop:1 #b0d0a8)",
    "qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #f0e0d0, stop:1 #d8b898)",
    "qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #e0f0e0, stop:1 #b0d8b0)",
]


def _record_label(record: dict, index: int, prefer_prompt: bool = False) -> str:
    """历史条名称：优先取脚本名，缺省用提示词截断。

    参数：
        record: 历史记录字典；
        index: 记录索引；
        prefer_prompt: 优先用提示词当名称（语音页用——同一脚本会产出
            多条记录，只显示脚本名会全部一样，看不出内容差异）。
    返回：显示用的短名称。
    """
    prompt = record.get("prompt", "") or ""
    if prefer_prompt and prompt:
        return prompt[:12] + "…" if len(prompt) > 12 else prompt
    name = record.get("script_key", "") or ""
    if name:
        # "image_scripts/grok_3_image.py" → "grok_3_image"
        return name.rsplit("/", 1)[-1].replace(".py", "")
    return prompt[:10] + "…" if len(prompt) > 10 else prompt


class _ClickableCell(QFrame):
    """可点击格基类：规范的 mousePressEvent 子类化实现。

    子类设置 clicked_callback，左键点击时触发；事件继续向上传播。
    """

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.clicked_callback = None   # 点击回调（宿主设置）
        self.base_style = ""           # 基础样式（背景渐变等），选中时重建用

    def set_border(self, color: str) -> None:
        """按给定颜色重建边框，保留基础背景样式。

        早期实现用 styleSheet().split("border:") 从当前样式里"抠"出前缀，
        一旦样式串里先出现别的 border 片段就会把背景色整段丢掉
        （表现为选中历史缩略图后背景变白）。改为缓存基础样式后重建。

        参数：color: 边框颜色（如 "#0078d4"）。
        """
        self.setStyleSheet(f"border:1px solid {color}; {self.base_style}")

    def mousePressEvent(self, event) -> None:  # noqa: N802（Qt 命名）
        """左键点击 → 触发宿主注入的回调（Qt 事件回调，规范子类化）。"""
        if event.button() == Qt.MouseButton.LeftButton and self.clicked_callback:
            self.clicked_callback()
        super().mousePressEvent(event)


class HistoryStrip(QWidget):
    """缩略图历史条（还原 .hist-section）。

    图片模式：48×48 可点击（更新提示词）；
    视频模式：80×50 不可点 + 下方"▶ 播放"按钮（打开产物）。
    失败记录：灰显 + 工具提示错误信息。
    """

    # 信号：图片模式点击（宿主回看提示词）
    item_clicked = Signal(int)
    # 信号：视频模式点"▶ 播放"（宿主打开产物）
    item_play_requested = Signal(int)

    def __init__(self, title: str, subtitle: str = "", video_mode: bool = False,
                 parent=None) -> None:
        """构建历史条外壳（标题行 + 横向条容器）。

        参数：
            title: 标题；subtitle: 标题旁灰色小字；video_mode: 是否视频模式。
        """
        super().__init__(parent)
        self._video_mode = video_mode
        self._records: list[dict] = []
        self.setStyleSheet("border:1px solid #d4d4d4;")

        outer = QVBoxLayout(self)
        outer.setContentsMargins(8, 6, 8, 6)
        outer.setSpacing(5)

        # 标题行（可带灰色副标题）
        header = QLabel(title)
        header.setStyleSheet("font-size:12px; font-weight:600; border:none;")
        if subtitle:
            sub = QLabel(subtitle)
            sub.setStyleSheet(
                "font-size:11px; color:#888; font-weight:400; border:none;"
            )
            head_row = QHBoxLayout()
            head_row.setSpacing(4)
            head_row.addWidget(header)
            head_row.addWidget(sub)
            head_row.addStretch(1)
            outer.addLayout(head_row)
        else:
            outer.addWidget(header)

        # 横向条容器：末尾 addStretch 兜底，插入条目时插到 stretch 之前
        self._strip = QHBoxLayout()
        self._strip.setSpacing(4)
        self._strip.addStretch(1)
        outer.addLayout(self._strip)

    # ------------------------------------------------------------------

    def load_records(self, records: list[dict], selected: int = 0) -> None:
        """从 HistoryDatabase.list_records 的结果加载。

        逐条重建缩略格；视频模式每格下方带"▶ 播放"按钮；
        失败记录灰显并在工具提示中附带错误信息。

        参数：records: 记录字典列表；selected: 图片模式默认选中索引。
        """
        self._records = list(records)
        # 清空旧条目（保留末尾的 stretch）
        while self._strip.count() > 1:
            item = self._strip.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        if not self._records:
            empty = QLabel("暂无历史记录")
            empty.setStyleSheet("font-size:11px; color:#aaa; border:none;")
            self._strip.insertWidget(0, empty)
            return

        for index, record in enumerate(self._records):
            ok = bool(record.get("ok"))
            # 占位色块：视频模式 80×50（QFrame），图片模式 48×48（可点击格）
            # 图片模式用 _ClickableCell（子类化 mousePressEvent，规范事件）
            cell: QFrame = (
                _ClickableCell() if not self._video_mode else QFrame()
            )
            cell.setFixedSize(80 if self._video_mode else 48,
                              50 if self._video_mode else 48)
            style = _PLACEHOLDER[index % 6]
            if not ok:
                style += "; opacity:0.25;"
            # 缓存基础样式（背景），选中/取消选中时由 set_border 重建边框
            cell.base_style = f"background:{style};"
            cell.setStyleSheet(f"border:1px solid #d4d4d4; {cell.base_style}")

            # 真实缩略图：成功记录且产物存在时，叠加显示缩放后的图片
            # （叠放于色块之上；路径失效/加载失败则保留占位色块，不影响显示。
            #  2026-09-01：历史库里曾因子进程 GBK 编码存入乱码路径，
            #  exists() 恒 False → 只显示占位块。编码修复后新记录恢复正常，
            #  旧乱码记录自然回退为占位块 + 仍可点击回看提示词）
            files = record.get("files") or []
            if ok and files:
                from pathlib import Path as _P
                if files[0] and _P(files[0]).exists():
                    pix = QPixmap(str(files[0]))
                    if not pix.isNull():
                        thumb = QLabel(cell)
                        thumb.setFixedSize(cell.size())
                        thumb.setScaledContents(True)
                        thumb.setPixmap(pix.scaled(
                            cell.size(), Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                            Qt.TransformationMode.SmoothTransformation,
                        ))
                        thumb.setStyleSheet("border:none;")
                        thumb.show()

            # 工具提示：条目名 + 失败时的错误详情
            tip = _record_label(record, index)
            if not ok:
                tip += f"\n失败：{record.get('code', '')} {record.get('message', '')}"
            cell.setToolTip(tip)

            if self._video_mode:
                # 视频模式：色块 + "▶ 播放"按钮（失败记录按钮禁用显示"失败"）
                wrapper = QWidget()
                v = QVBoxLayout(wrapper)
                v.setContentsMargins(0, 0, 0, 0)
                v.setSpacing(4)
                btn = QPushButton("▶ 播放" if ok else "失败")
                btn.setStyleSheet("font-size:11px; padding:2px 4px;")
                btn.setFixedWidth(80)
                btn.setEnabled(ok)
                # 信号槽：点播放 → 发出索引，宿主负责打开产物
                btn.clicked.connect(
                    lambda _=False, i=index: self.item_play_requested.emit(i)
                )
                # 点色块与点按钮等效（成功记录才响应；2026-09-02 补：
                # 原先色块点了没反应，用户易困惑）
                if ok:
                    cell.setCursor(Qt.CursorShape.PointingHandCursor)
                    cell.clicked_callback = (
                        lambda i=index: self.item_play_requested.emit(i)
                    )
                v.addWidget(cell)
                v.addWidget(btn, alignment=Qt.AlignmentFlag.AlignHCenter)
                self._strip.insertWidget(self._strip.count() - 1, wrapper)
            else:
                # 图片模式：整格可点击（_ClickableCell 子类化，规范事件处理）
                cell.setCursor(Qt.CursorShape.PointingHandCursor)
                cell.clicked_callback = (
                    lambda i=index: self._on_cell_clicked(i)
                )
                self._strip.insertWidget(self._strip.count() - 1, cell)

        if not self._video_mode and self._records:
            self._select(selected)

    def records(self) -> list[dict]:
        """返回当前加载的记录列表（宿主按索引取详情）。"""
        return self._records

    def _on_cell_clicked(self, index: int) -> None:
        """点击图片格：高亮选中并发出 item_clicked 信号。

        参数：index: 条目索引。
        """
        self._select(index)
        self.item_clicked.emit(index)

    def _select(self, index: int) -> None:
        """高亮指定格：选中格蓝色边框，其余恢复灰色。

        参数：index: 条目索引。
        """
        widgets = [
            self._strip.itemAt(i).widget()
            for i in range(self._strip.count() - 1)
        ]
        for i, w in enumerate(widgets):
            # 仅图片模式的可点击格需要换边框（视频模式是普通 QFrame 包装层）
            if hasattr(w, "set_border"):
                w.set_border("#0078d4" if i == index else "#d4d4d4")


class HistoryTable(QTableWidget):
    """语音历史表格：名称 / 时长·状态 / 操作。

    成功行尝试读 WAV 元数据显示时长；操作按钮成功行"▶ 播放"、
    失败行"详情"，点击发出对应信号（携带行索引）。
    """

    # 信号：成功行点击（宿主播放/回看提示词）
    row_clicked = Signal(int)
    # 信号：失败行点"详情"（宿主显示错误信息）
    detail_requested = Signal(int)

    def __init__(self, parent=None) -> None:
        """构建三列表格并设置表头/样式。"""
        super().__init__(0, 3, parent)
        self._records: list[dict] = []
        self.setHorizontalHeaderLabels(["名称", "时长 · 状态", ""])
        self.verticalHeader().setVisible(False)
        self.setShowGrid(False)
        self.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.setColumnWidth(0, 260)
        self.setColumnWidth(1, 180)
        self.horizontalHeader().setStretchLastSection(True)
        self.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.Stretch
        )
        self.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)

    def load_records(self, records: list[dict]) -> None:
        """records：HistoryDatabase.list_records(category="audio") 的结果。

        每行尝试用 wave 模块读真实时长（读失败留空）；
        失败记录名称灰显、状态红显。

        参数：records: 记录字典列表。
        """
        self._records = list(records)
        rows = []
        for i, r in enumerate(self._records):
            ok = bool(r.get("ok"))
            dur = ""
            files = r.get("files") or []
            # 成功且产物存在：尝试读 WAV 帧数换算秒数
            if ok and files:
                try:
                    import wave

                    with wave.open(str(files[0]), "rb") as w:
                        dur = f"{w.getnframes() // w.getframerate()}秒"
                except (wave.Error, OSError, IndexError):
                    dur = ""
            meta = f"{dur} · 成功" if ok else f"失败 · {r.get('code', '')}"
            # 语音页同一脚本会产生多条记录，名称优先用提示词区分内容
            rows.append({
                "name": _record_label(r, i, prefer_prompt=True),
                "meta": meta, "ok": ok,
            })

        # 填充表格
        self.setRowCount(len(rows))
        for i, row in enumerate(rows):
            name = QTableWidgetItem(row["name"])
            if not row["ok"]:
                name.setForeground(Qt.GlobalColor.gray)
            self.setItem(i, 0, name)

            meta = QTableWidgetItem(row["meta"])
            meta.setForeground(Qt.GlobalColor.gray if row["ok"] else Qt.GlobalColor.red)
            meta.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            self.setItem(i, 1, meta)

            # 操作按钮：成功"▶ 播放"，失败"详情"（lambda 固定行索引）
            btn = QPushButton("▶ 播放" if row["ok"] else "详情")
            btn.setStyleSheet("font-size:11px; padding:2px 9px;")
            btn.clicked.connect(
                lambda _=False, idx=i: (
                    self.detail_requested.emit(idx)
                    if not rows[idx]["ok"]
                    else self.row_clicked.emit(idx)
                )
            )
            self.setCellWidget(i, 2, btn)

        # 表格高度随行数自适应（含表头余量）
        self.setFixedHeight(max(70, 38 * len(rows) + 30))

    def records(self) -> list[dict]:
        """返回当前加载的记录列表（宿主按索引取详情）。"""
        return self._records
