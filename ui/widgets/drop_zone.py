"""素材上传区（参考图 / 首帧图），还原 .drop-zone 虚线框。

一个 64px 高的虚线框区域：主文案 + 格式说明两行。点击弹出系统
文件选择框（QFileDialog），选择后做三重校验：
  1. 扩展名 ∈ {jpg, jpeg, png, webp}；
  2. 文件大小 ≤ 30MB（参考图上限，见需求 §3.1）；
  3. QPixmap 能正常加载（防扩展名伪装的坏文件）。
校验通过后显示已选文件名并发出 file_selected 信号，宿主页面
在生成前通过 selected_file() 取路径做必填校验。

M1：点击弹出演示提示；M2+：真实文件选择与校验（本版实现）。
"""

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QLabel, QFileDialog, QVBoxLayout, QWidget

# 参考图 / 首帧图大小上限（30MB，需求文档 §3.1/§11）
MAX_IMAGE_BYTES = 30 * 1024 * 1024
# 允许的图片扩展名（小写，不含点）
ALLOWED_SUFFIXES = {"jpg", "jpeg", "png", "webp"}

# 默认外观与选中后的恢复外观（相同样式，避免残留高亮）
_STYLE_IDLE = (
    "border:2px dashed #c0c0c0; background:#fafafa; border-radius:2px;"
)


class DropZone(QWidget):
    """虚线拖放区。caption 主文案，hint 格式说明。

    点击弹出文件选择框；选中合法文件后显示文件名并发出
    file_selected 信号。clear() 可清空已选。
    """

    # 信号：用户选定一个合法文件，参数为绝对路径字符串
    file_selected = Signal(str)

    def __init__(self, caption: str, hint: str, parent=None) -> None:
        """构建虚线上传框。

        参数：caption: 主文案（如"点击选择或拖放图片"）；
              hint: 格式说明（如"JPG / PNG / WebP · 最大 30MB"）。
        """
        super().__init__(parent)
        self._caption = caption
        self._file = ""   # 已选文件绝对路径（空串=未选）
        self.setFixedHeight(64)
        self.setStyleSheet(_STYLE_IDLE)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        v = QVBoxLayout(self)
        v.setContentsMargins(8, 8, 8, 8)
        v.setSpacing(2)
        # 主文案：未选文件时显示 caption，选好后显示文件名
        self._main = QLabel(caption)
        self._main.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        self._main.setStyleSheet(
            "color:#333; font-size:12px; font-weight:600;"
            " border:none; background:transparent;"
        )
        sub = QLabel(hint)
        sub.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        sub.setStyleSheet(
            "color:#aaa; font-size:11px; border:none; background:transparent;"
        )
        v.addWidget(self._main)
        v.addWidget(sub)

    # ------------------------------------------------------------------

    def mousePressEvent(self, event) -> None:  # noqa: N802（Qt 命名）
        """左键点击：弹出文件选择框并执行校验（Qt 事件回调）。"""
        if event.button() == Qt.MouseButton.LeftButton:
            self._pick_file()
        super().mousePressEvent(event)

    def _pick_file(self) -> None:
        """打开系统文件选择框，选中后做格式/大小/可读性三重校验。"""
        filters = "图片文件 (*.jpg *.jpeg *.png *.webp)"
        path, _ = QFileDialog.getOpenFileName(self, self._caption, "", filters)
        if not path:
            return   # 用户取消选择，保持原状
        p = Path(path)
        # 校验 1：扩展名白名单
        if p.suffix.lower().lstrip(".") not in ALLOWED_SUFFIXES:
            self._warn(f"不支持的图片格式：{p.suffix or '（无扩展名）'}\n"
                       f"仅支持 JPG / PNG / WebP。")
            return
        # 校验 2：大小 ≤ 30MB
        try:
            size = p.stat().st_size
        except OSError as exc:
            self._warn(f"无法读取文件：{exc}")
            return
        if size > MAX_IMAGE_BYTES:
            self._warn(f"图片超过 30MB 上限（当前 {size / 1024 / 1024:.1f}MB），"
                       "请压缩后再试。")
            return
        # 校验 3：QPixmap 能正常解码（防伪装扩展名的坏文件）
        pix = QPixmap(str(p))
        if pix.isNull():
            self._warn("图片文件无法解析，可能已损坏，请更换文件。")
            return
        # 全部通过：记录并显示
        self._file = str(p)
        self._main.setText(f"✅ {p.name}")
        self._main.setStyleSheet(
            "color:#2e7d32; font-size:12px; font-weight:600;"
            " border:none; background:transparent;"
        )
        self.setStyleSheet(
            "border:2px solid #2e7d32; background:#f0fff0; border-radius:2px;"
        )
        self.file_selected.emit(self._file)

    def _warn(self, msg: str) -> None:
        """校验失败弹窗，并恢复虚线框默认外观。"""
        from PySide6.QtWidgets import QMessageBox

        QMessageBox.warning(self, "图片校验未通过", msg)
        self.setStyleSheet(_STYLE_IDLE)

    # ------------------------------------------------------------------

    def selected_file(self) -> str:
        """返回已选文件路径；未选择时为空串（宿主做必填校验用）。"""
        return self._file

    def clear(self) -> None:
        """清空已选文件，恢复初始文案与外观。"""
        self._file = ""
        self._main.setText(self._caption)
        self._main.setStyleSheet(
            "color:#333; font-size:12px; font-weight:600;"
            " border:none; background:transparent;"
        )
        self.setStyleSheet(_STYLE_IDLE)
