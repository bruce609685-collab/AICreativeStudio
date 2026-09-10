"""界面图标：把 emoji / 符号渲染成 PNG 图片，规避"字体缺字形显示成方块"。

背景：页签和按钮上的 🖼 ⚙ ℹ ✨ ▶ ⏮ ⏭ 🖥 等符号依赖系统字体里的
对应字形。开发机上实测：QSS 里 font-family 指定 "Microsoft YaHei UI"
后，Qt 对这批符号的回退不稳定，页签上的 🖼 ⚙ ℹ 会渲染成空心方块
（俗称豆腐块）。

方案：用 QRawFont 精确检测"哪个字体真的有这个字形"，挑中了再用
QPainter 画到透明底 QPixmap，转成 QIcon 挂到按钮/页签。全部字体都
没有该字形时，降级为几何图形（圆角方框），保证任何机器上都不出现方块。

生成的 PNG 缓存在 data/cache/icons/ 下（同一符号只渲染一次），
既省去重复绘制开销，也方便排查"图标到底画成了什么"。
"""

from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import (
    QColor, QFont, QFontDatabase, QIcon, QPainter, QPen, QPixmap, QRawFont,
)

_logger = logging.getLogger(__name__)

# 候选字体：按优先级排列，用 QRawFont 逐个验字形，谁有就用谁
_FONT_CANDIDATES = [
    "Segoe UI Emoji",      # Windows 彩色 emoji（覆盖面最广）
    "Segoe UI Symbol",     # Windows 几何符号（seguiemj 缺失时的补充）
    "Segoe UI",
    "Microsoft YaHei UI",
]

# 图标缓存目录：延迟解析（见 _cache_dir）。
# 原因：ui/icons 被 ui.main_window 导入，而 app/__init__ 又会反向导入
# ui.main_window；若在模块顶层 `from app import paths`，直接
# `import ui.main_window` 会触发循环导入报错。
_CACHE_DIR: Path | None = None


def _cache_dir() -> Path:
    """返回图标缓存目录，首次调用时才解析 app.paths（避免循环导入）。

    返回：data/cache/icons 目录路径（可能尚不存在）。
    """
    global _CACHE_DIR
    if _CACHE_DIR is None:
        from app import paths  # 延迟导入：此处 app 已完成初始化
        _CACHE_DIR = paths.CACHE_DIR / "icons"
    return _CACHE_DIR

# 单个图标的渲染尺寸（比显示尺寸大一圈，缩放后边缘更干净）
_RENDER_PX = 64

# 字形查询结果缓存：symbol → 能画出它的字体族名（None 表示都没有）
_GLYPH_FONT_CACHE: dict[str, str | None] = {}


def _font_has_glyph(family: str, symbol: str) -> bool:
    """判断某字体是否真的包含该符号的字形。

    用 QRawFont 查字形索引：索引为 0 表示"没有这个字形"
    （注意不能用 QFontMetrics.inFontUcs4——它会把回退字体也算进去，
    导致每种字体都报 True，没法用来挑字体）。

    参数：family: 字体族名；symbol: 单个符号字符。
    返回：字体包含该字形返回 True。
    """
    try:
        raw = QRawFont.fromFont(QFont(family, 14))
        if not raw.isValid():
            return False
        indexes = raw.glyphIndexesForString(symbol)
        return bool(indexes) and indexes[0] != 0
    except Exception:
        return False


def _pick_family(symbol: str) -> str | None:
    """挑出能渲染该符号的字体族名（带缓存）。

    参数：symbol: 单个符号字符。
    返回：字体族名；所有候选都没有该字形时返回 None。
    """
    if symbol in _GLYPH_FONT_CACHE:
        return _GLYPH_FONT_CACHE[symbol]
    available = set(QFontDatabase.families())
    chosen: str | None = None
    for name in _FONT_CANDIDATES:
        if name in available and _font_has_glyph(name, symbol):
            chosen = name
            break
    _GLYPH_FONT_CACHE[symbol] = chosen
    return chosen


def _draw_fallback(painter: QPainter, color: QColor, px: int) -> None:
    """字体缺失时的几何兜底：画一个圆角方框，至少不像"缺字"。

    参数：painter: 画笔；color: 描边颜色；px: 画布边长。
    """
    pen = QPen(color)
    pen.setWidth(max(2, px // 16))
    painter.setPen(pen)
    painter.setBrush(Qt.BrushStyle.NoBrush)
    inset = px // 8
    painter.drawRoundedRect(
        QRectF(inset, inset, px - 2 * inset, px - 2 * inset),
        px // 8, px // 8,
    )


def render_symbol_pixmap(symbol: str, color: str = "#333333",
                         px: int = _RENDER_PX) -> QPixmap:
    """把单个符号渲染成透明底 QPixmap。

    参数：
        symbol: 要绘制的符号（如 "🖼"、"⚙"）；
        color: 文字颜色（单色符号用；彩色 emoji 保持字体自带配色）；
        px: 渲染边长（像素，正方形）。
    返回：渲染好的 QPixmap（透明底）。
    """
    pix = QPixmap(px, px)
    pix.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pix)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    painter.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
    painter.setPen(QColor(color))

    family = _pick_family(symbol) if symbol else None
    if family is None:
        # 没有字体能画 → 几何兜底。
        # 同时打日志：这类符号应尽早换成系统有字形的替代品，
        # 否则界面上会长期挂着一个"方框"而无人察觉。
        _logger.warning("符号 %r (U+%04X) 无可用字体，已降级为几何方框",
                        symbol, ord(symbol) if symbol else 0)
        _draw_fallback(painter, QColor(color), px)
    else:
        font = QFont(family)
        font.setPixelSize(int(px * 0.78))
        painter.setFont(font)
        painter.drawText(QRectF(0, 0, px, px),
                         Qt.AlignmentFlag.AlignCenter, symbol)
    painter.end()
    return pix


def symbol_icon(symbol: str, color: str = "#333333", px: int = _RENDER_PX,
                cache: bool = True) -> QIcon:
    """把符号转成 QIcon（带磁盘缓存，同一符号只渲染一次）。

    参数：
        symbol: 符号文本；
        color: 颜色（十六进制字符串）；
        px: 渲染边长；
        cache: 是否使用磁盘缓存。
    返回：可直接挂到 QPushButton.setIcon / QTabWidget.setTabIcon 的 QIcon。
    """
    key = f"{symbol}|{color}|{px}"
    name = f"{abs(hash(key)):x}.png"
    cache_dir = _cache_dir()
    path = cache_dir / name
    if cache and path.exists():
        pix = QPixmap(str(path))
        if not pix.isNull():
            return QIcon(pix)
    pix = render_symbol_pixmap(symbol, color, px)
    if cache:
        try:
            cache_dir.mkdir(parents=True, exist_ok=True)
            pix.save(str(path), "PNG")
        except OSError:
            pass   # 缓存写不进去不影响功能（磁盘只读/权限问题时静默降级）
    return QIcon(pix)


def apply_tab_icon(tabs, index: int, symbol: str, color: str = "#333333") -> None:
    """给页签设置图标（字体缺失时也不会出现方块）。

    参数：
        tabs: QTabWidget；
        index: 页签下标；
        symbol: 符号文本；
        color: 颜色。
    """
    tabs.setTabIcon(index, symbol_icon(symbol, color))


def set_button_icon(button, symbol: str, color: str = "#333333") -> None:
    """给按钮设置前置图标。

    参数：
        button: QPushButton；
        symbol: 符号文本；
        color: 颜色。
    """
    button.setIcon(symbol_icon(symbol, color))


def has_glyph(symbol: str) -> bool:
    """该符号在当前系统上是否有字体能画出来（诊断用）。

    参数：symbol: 符号字符。
    返回：有字体能画返回 True。
    """
    return _pick_family(symbol) is not None


__all__ = [
    "apply_tab_icon", "has_glyph", "render_symbol_pixmap",
    "set_button_icon", "symbol_icon",
]
