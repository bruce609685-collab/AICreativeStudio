"""图片预览宫格（还原 .preview-grid，1/2/4/9 宫格自适应）。

按生成数量自动选择布局：1 张 → 1 宫格，2 张 → 1×2，3-4 张 → 2×2，
5-9 张 → 3×3。多余格显示为半透明占位块。每格可显示真实图片
（QPixmap 等比缩放，随窗口缩放重绘），点击发出 cell_clicked 信号。

M1：占位色块；M2：支持显示真实生成图片（QPixmap 等比缩放）。
"""

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QFrame, QGridLayout, QLabel, QWidget

# 预览文档的占位渐变色（c1–c6，无图时循环使用）
_PLACEHOLDER_STYLES = [
    "qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #e8e8e8, stop:1 #c8c8c8)",
    "qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #d5e5f0, stop:1 #a8c8e0)",
    "qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #e0d8e8, stop:1 #c0b0d0)",
    "qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #d8e8d5, stop:1 #b0d0a8)",
    "qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #f0e0d0, stop:1 #d8b898)",
    "qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #e0f0e0, stop:1 #b0d8b0)",
]


class _Cell(QFrame):
    """单个预览格：占位色块 / 真实图片 + 序号，可点击选中。

    占位 label 与图片 label 叠放在同一格：显示图片时隐藏占位，反之亦然。
    """

    def __init__(self, index: int, enabled: bool, parent=None) -> None:
        """构建单格。

        参数：index: 格序号（0 起）；enabled: 是否启用（多余格禁用半透明）。
        """
        super().__init__(parent)
        self._enabled = enabled
        self._pix: QPixmap | None = None
        self._image_path = ""   # 该格当前显示的图片路径（点击打开用）
        # 启用格显示手型光标，禁用格普通箭头
        self.setCursor(Qt.CursorShape.PointingHandCursor if enabled
                       else Qt.CursorShape.ArrowCursor)
        self.setStyleSheet(
            f"border:1px solid rgba(0,0,0,0.1); background:{_PLACEHOLDER_STYLES[index % 6]};"
        )
        lay = QGridLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        # 占位文字（"图 1"），禁用格不显示
        self._label = QLabel(f"图 {index + 1}" if enabled else "")
        self._label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._label.setStyleSheet(
            "color:rgba(255,255,255,0.8); font-size:11px; border:none;"
        )
        lay.addWidget(self._label, 0, 0)
        # 真实图片标签：与占位 label 同格叠放
        self._img_label = QLabel()
        self._img_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._img_label.setStyleSheet("border:none;")
        self._img_label.hide()
        lay.addWidget(self._img_label, 0, 0)  # 与占位 label 同格叠放
        if not enabled:
            self.setStyleSheet(self.styleSheet() + " opacity:0.2;")
        self.set_selected(False)

    # ------------------------------------------------------------------

    def set_image(self, path: str) -> bool:
        """显示真实图片；成功返回 True。

        参数：path: 图片路径。
        返回：加载是否成功。
        """
        pix = QPixmap(str(path))
        if pix.isNull():
            return False
        self._pix = pix
        self._image_path = str(path)
        self._label.hide()
        self._img_label.show()
        self._update_pix()
        return True

    def clear_image(self) -> None:
        """清除图片，恢复占位色块状态。"""
        self._pix = None
        self._image_path = ""
        self._img_label.hide()
        self._label.show()

    def image_path(self) -> str:
        """返回该格当前显示的图片路径（无图片时为空串）。"""
        return self._image_path

    def _update_pix(self) -> None:
        """按当前控件大小等比缩放图片并显示（窗口缩放时重绘）。"""
        if self._pix is None:
            return
        size = self._img_label.size()
        if size.width() > 4 and size.height() > 4:
            self._img_label.setPixmap(self._pix.scaled(
                size, Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            ))

    def resizeEvent(self, event) -> None:  # noqa: N802（Qt 命名）
        """控件尺寸变化时重新缩放图片（Qt 事件回调）。"""
        super().resizeEvent(event)
        self._update_pix()

    def set_selected(self, selected: bool) -> None:
        """切换选中态边框颜色：选中蓝色，未选半透明黑。

        参数：selected: 是否选中。
        """
        color = "#0078d4" if selected else "rgba(0,0,0,0.1)"
        self.setStyleSheet(self.styleSheet() + f"border:1px solid {color};")

    def mousePressEvent(self, event) -> None:  # noqa: N802（Qt 命名）
        """左键点击：全格取消选中 → 自身选中 → 向上找到 PreviewGrid 发信号。"""
        if self._enabled and event.button() == Qt.MouseButton.LeftButton:
            grid = self.parentWidget()
            for cell in grid.findChildren(_Cell):
                cell.set_selected(False)
            self.set_selected(True)
            # 交给宿主处理（预览文档：调系统看图 + 更新提示词）
            # 修复：从 grid 自己开始向上找（cell 的直接父级就是 PreviewGrid，
            # 原代码从 parentWidget() 起步把自己跳过了，信号永远发不出）
            w = grid
            while w is not None and not isinstance(w, PreviewGrid):
                w = w.parentWidget()
            if isinstance(w, PreviewGrid):
                w.cell_clicked.emit(self)
        super().mousePressEvent(event)


class PreviewGrid(QWidget):
    """按生成数量自适应的宫格：1→1宫格 2→1×2 3-4→2×2 5-9→3×3。"""

    # 信号：某格被点击，参数是被点击的 _Cell
    cell_clicked = Signal(object)

    def __init__(self, parent=None) -> None:
        """初始化网格，默认 4 宫格。"""
        super().__init__(parent)
        outer = QGridLayout(self)
        outer.setContentsMargins(6, 6, 6, 6)
        outer.setSpacing(4)
        self._outer = outer
        self._cells: list[_Cell] = []
        self.set_count(4)

    def set_count(self, n: int) -> None:
        """n∈[1,9]；总格数向上取到 1/2/4/9，多余格半透明占位。

        参数：n: 需要的有效格数。
        """
        n = max(1, min(9, n))
        # 总格数向上取整到 1/2/4/9；列数按总格数决定
        total = 1 if n <= 1 else 2 if n == 2 else 4 if n <= 4 else 9
        cols = 1 if total == 1 else 2 if total <= 4 else 3

        # 清空旧格子
        while self._outer.count():
            item = self._outer.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self._cells = []

        # 重建格子：前 n 格启用，其余占位
        for i in range(total):
            cell = _Cell(i, enabled=i < n)
            self._cells.append(cell)
            self._outer.addWidget(cell, i // cols, i % cols)

        # 行列均分拉伸，让格子填满控件
        for c in range(cols):
            self._outer.setColumnStretch(c, 1)
        for r in range((total + cols - 1) // cols):
            self._outer.setRowStretch(r, 1)

    # ------------------------------------------------------------------

    def set_image_at(self, index: int, path: str) -> None:
        """把第 index 格显示为真实图片（越界/失败静默忽略）。

        参数：index: 格索引；path: 图片路径。
        """
        if 0 <= index < len(self._cells):
            self._cells[index].set_image(path)

    def clear_images(self) -> None:
        """清除所有格子的图片，恢复占位状态。"""
        for cell in self._cells:
            cell.clear_image()

    def image_at(self, index: int) -> str:
        """返回第 index 格显示的图片路径（越界/无图返回空串）。"""
        if 0 <= index < len(self._cells):
            return self._cells[index].image_path()
        return ""
