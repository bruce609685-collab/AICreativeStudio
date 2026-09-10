"""界面层全局样式（QSS，Qt 样式表）。

本文件集中定义整个程序的外观：所有窗口、按钮、输入框、页签等控件
的颜色、字体、边框都在这里统一设置（类似网页的 CSS）。

还原 UI 预览文档 v0.1.5 的 Windows 浅色风格：
主蓝 #0078d4、微软雅黑 13px、1px 浅灰边框、fieldset 样式分组框。
程序启动时由 app/application.py 调用 apply_global_style(app) 一次性生效。
"""

from PySide6.QtGui import QFont, QFontDatabase
from PySide6.QtWidgets import QApplication

import os

# 与预览文档对应的调色板（其他文件 import style 后引用这些常量保持配色一致）
BLUE = "#0078d4"          # 主蓝色：选中态、主按钮、焦点边框
BLUE_HOVER_BG = "#e5f1fb" # 主蓝的浅色背景：悬停高亮、列表选中
GRAY_BORDER = "#c8c8c8"   # 输入框边框灰
GRAY_PANEL = "#f3f3f3"    # 面板底色灰（页签栏、状态栏）
TEXT_MAIN = "#1a1a1a"     # 正文主色
TEXT_SUB = "#555555"      # 次要文字
WARN_BG = "#fff8e1"       # 警告条背景（淡黄）
WARN_BORDER = "#ffe082"   # 警告条边框
WARN_TEXT = "#e65100"     # 警告条文字（橙）
OK_GREEN = "#2e7d32"      # 成功/已填写（绿）
FAIL_RED = "#d32f2f"      # 失败/危险操作（红）

# 字体回退链：中英文用微软雅黑，符号/emoji 交给 Windows 自带的两款符号字体。
# 只写 "Microsoft YaHei UI" 时，Qt 对 🖼 ⚙ ℹ ✨ ▶ 这类符号的回退不稳定，
# 页签和按钮上会出现空心方块（豆腐块）；把符号字体显式列进来即可解决。
_FONT_STACK = ('"Microsoft YaHei UI", "Segoe UI", "Segoe UI Emoji", '
               '"Segoe UI Symbol", sans-serif')

_QSS = f"""
* {{
    font-family: {_FONT_STACK};
    font-size: 13px;
    color: {TEXT_MAIN};
}}

QMainWindow, QDialog {{
    background: #ffffff;
}}

/* ---------- 页签栏（还原 .tab-bar） ---------- */
QTabWidget::pane {{
    border: none;
    top: -1px;
}}
QTabBar::tab {{
    padding: 8px 18px;
    font-size: 13px;
    color: {TEXT_SUB};
    background: {GRAY_PANEL};
    border: none;
    border-bottom: 2px solid transparent;
    margin-right: 0px;
}}
QTabBar::tab:hover {{
    color: {TEXT_MAIN};
    background: #ececec;
}}
QTabBar::tab:selected {{
    color: {BLUE};
    border-bottom-color: {BLUE};
    background: #ffffff;
    font-weight: 600;
}}

/* ---------- 输入控件 ---------- */
QLineEdit, QPlainTextEdit, QTextEdit, QSpinBox {{
    padding: 4px 8px;
    border: 1px solid {GRAY_BORDER};
    border-radius: 1px;
    background: #ffffff;
    selection-background-color: {BLUE};
    selection-color: #ffffff;
}}
QLineEdit:focus, QPlainTextEdit:focus, QTextEdit:focus, QSpinBox:focus {{
    border-color: {BLUE};
}}
QComboBox {{
    padding: 3px 7px;
    min-height: 22px;
    border: 1px solid {GRAY_BORDER};
    border-radius: 1px;
    background: #ffffff;
}}
QComboBox:hover {{
    border-color: {BLUE};
}}
QComboBox:disabled {{
    color: #999999;
    background: #f5f5f5;
}}
QComboBox::drop-down {{
    border: none;
    width: 20px;
}}
QComboBox QAbstractItemView {{
    border: 1px solid {GRAY_BORDER};
    background: #ffffff;
    selection-background-color: {BLUE_HOVER_BG};
    selection-color: {BLUE};
}}

/* ---------- 按钮（还原 .btn / .btn-p） ---------- */
QPushButton {{
    padding: 4px 13px;
    border: 1px solid #b0b0b0;
    border-radius: 1px;
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                stop:0 #f6f6f6, stop:1 #e5e5e5);
    color: {TEXT_MAIN};
}}
QPushButton:hover {{
    border-color: {BLUE};
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                stop:0 #ecf6fd, stop:1 #dcecfc);
    color: {BLUE};
}}
QPushButton:pressed {{
    background: #dcecfc;
}}
QPushButton:disabled {{
    color: #999999;
    background: #f0f0f0;
    border-color: #d0d0d0;
}}
QPushButton[class="primary"] {{
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                stop:0 {BLUE}, stop:1 #006cbd);
    border-color: #005a9e;
    color: #ffffff;
    font-weight: 600;
}}
QPushButton[class="primary"]:hover {{
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                stop:0 #1a86dd, stop:1 #0078d4);
    color: #ffffff;
}}
QPushButton[class="danger"]:hover {{
    border-color: {FAIL_RED};
    color: {FAIL_RED};
    background: #fff5f5;
}}

/* ---------- 分组框（还原 fieldset + legend） ---------- */
QGroupBox {{
    border: 1px solid #d4d4d4;
    border-radius: 1px;
    margin-top: 8px;
    padding: 7px 9px 4px 9px;
}}
QGroupBox::title {{
    subcontrol-origin: margin;
    subcontrol-position: top left;
    left: 6px;
    padding: 0 4px;
    font-size: 12px;
    font-weight: 600;
    color: #333333;
    background: #ffffff;
}}

/* ---------- 滚动区 / 表格 ---------- */
QScrollArea {{
    border: none;
}}
QTableWidget {{
    border: none;
    background: transparent;
}}
QTableWidget::item {{
    padding: 4px 0px;
    border: none;
}}
QHeaderView::section {{
    background: transparent;
    border: none;
}}

/* ---------- 状态栏 ---------- */
QStatusBar {{
    background: {GRAY_PANEL};
    border-top: 1px solid #d4d4d4;
    color: #666666;
    font-size: 11px;
}}
QStatusBar::item {{
    border: none;
}}

/* ---------- 复选框 ---------- */
QCheckBox {{
    font-size: 12px;
    spacing: 6px;
}}
QCheckBox::indicator {{
    width: 14px;
    height: 14px;
    border: 1px solid #b0b0b0;
    border-radius: 2px;
    background: #ffffff;
}}
QCheckBox::indicator:hover {{
    border-color: {BLUE};
}}
QCheckBox::indicator:checked {{
    border-color: {BLUE};
    background: {BLUE};
    /* 勾选态画一个白色对勾：原实现只填充蓝底没有对勾，远看像"半选" */
    image: url("data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' width='12' height='12' viewBox='0 0 12 12'><path d='M2.5 6.2l2.4 2.4 4.6-5' stroke='white' stroke-width='1.8' fill='none' stroke-linecap='round' stroke-linejoin='round'/></svg>");
}}
QCheckBox::indicator:disabled {{
    border-color: #d0d0d0;
    background: #f0f0f0;
}}

/* ---------- 滚动条（统一浅色风格，替代系统默认的深灰粗条） ---------- */
QScrollBar:vertical {{
    background: transparent;
    width: 10px;
    margin: 0px;
}}
QScrollBar::handle:vertical {{
    background: #c8c8c8;
    border-radius: 5px;
    min-height: 28px;
}}
QScrollBar::handle:vertical:hover {{
    background: #a8a8a8;
}}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
    height: 0px;
}}
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{
    background: transparent;
}}
QScrollBar:horizontal {{
    background: transparent;
    height: 10px;
    margin: 0px;
}}
QScrollBar::handle:horizontal {{
    background: #c8c8c8;
    border-radius: 5px;
    min-width: 28px;
}}
QScrollBar::handle:horizontal:hover {{
    background: #a8a8a8;
}}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{
    width: 0px;
}}
QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {{
    background: transparent;
}}

/* ---------- 进度条（还原 .gen-progress：浅蓝底 + 主蓝进度） ---------- */
QProgressBar {{
    border: 1px solid #b3d9f7;
    border-radius: 1px;
    background: #f0f7ff;
    text-align: center;
    font-size: 11px;
    color: {TEXT_SUB};
 min-height: 14px;
    max-height: 16px;
}}
QProgressBar::chunk {{
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
            stop:0 #2b8ee0, stop:1 {BLUE});
    border-radius: 0px;
}}

/* ---------- 滑块（播放器进度 / 音量，主蓝圆钮） ---------- */
QSlider::groove:horizontal {{
    height: 4px;
    background: #dcdcdc;
    border-radius: 2px;
}}
QSlider::sub-page:horizontal {{
    background: {BLUE};
    border-radius: 2px;
}}
QSlider::handle:horizontal {{
    width: 12px;
    height: 12px;
    margin: -4px 0;
    border-radius: 6px;
    background: #ffffff;
    border: 2px solid {BLUE};
}}
QSlider::handle:horizontal:hover {{
    background: {BLUE_HOVER_BG};
}}
QSlider::handle:horizontal:disabled {{
    border-color: #b0b0b0;
}}
QSlider::sub-page:horizontal:disabled {{
    background: #b0b0b0;
}}

/* ---------- 工具提示（浅色，替代系统黑底黄字/深色默认） ---------- */
QToolTip {{
    background: #ffffff;
  color: {TEXT_MAIN};
    border: 1px solid {GRAY_BORDER};
    padding: 4px 8px;
    font-size: 12px;
}}

/* ---------- 分隔条（设置页左右分栏） ---------- */
QSplitter::handle {{
    background: #e6e6e6;
}}
QSplitter::handle:horizontal {{
    width: 3px;
}}
QSplitter::handle:vertical {{
    height: 3px;
}}
QSplitter::handle:hover {{
    background: {BLUE};
}}

/* ---------- 右键菜单（输入框复制/粘贴等） ---------- */
QMenu {{
    background: #ffffff;
    border: 1px solid {GRAY_BORDER};
  padding: 4px 0;
}}
QMenu::item {{
    padding: 5px 24px 5px 16px;
    color: {TEXT_MAIN};
}}
QMenu::item:selected {{
    background: {BLUE_HOVER_BG};
    color: {BLUE};
}}
QMenu::item:disabled {{
  color: #999999;
}}
QMenu::separator {{
    height: 1px;
  background: #e6e6e6;
    margin: 4px 8px;
}}

/* ---------- 列表 / 树（设置页脚本列表） ---------- */
QListWidget, QTreeWidget, QListView, QTreeView {{
    border: 1px solid {GRAY_BORDER};
    background: #ffffff;
    outline: none;
}}
QListWidget::item, QTreeWidget::item, QListView::item, QTreeView::item {{
    padding: 4px 6px;
}}
QListWidget::item:hover, QTreeWidget::item:hover,
QListView::item:hover, QTreeView::item:hover {{
 background: #f3f8fd;
}}
QListWidget::item:selected, QTreeWidget::item:selected,
QListView::item:selected, QTreeView::item:selected {{
    background: {BLUE_HOVER_BG};
    color: {BLUE};
}}

/* ---------- 单选框（与复选框同风格） ---------- */
QRadioButton {{
    font-size: 12px;
    spacing: 6px;
}}
QRadioButton::indicator {{
    width: 14px;
    height: 14px;
    border: 1px solid #b0b0b0;
    border-radius: 7px;
    background: #ffffff;
}}
QRadioButton::indicator:hover {{
border-color: {BLUE};
}}
QRadioButton::indicator:checked {{
    border: 4px solid {BLUE};
    background: #ffffff;
}}
"""


def _setup_fonts(app: QApplication) -> None:
    """设置中英文主字体并加载 emoji 字体兜底，避免方块。

    页签上有 🖼🎬🎙 等表情符号，若系统缺少对应字体会显示成方块（豆腐块），
    所以这里把 Windows 自带的微软雅黑和 Segoe UI Emoji 注册进 Qt 字体库。

    路径覆盖 Windows / 开发机；非 Windows 平台字体不存在则自动 skip，
    setFont 找不到字体会 fallback 到系统默认（Mac = PingFang SC 等）。
    """
    # 注册中文字体（微软雅黑常规体和粗体）
    for path in (
        r"C:\Windows\Fonts\msyh.ttc",        # 微软雅黑
        r"C:\Windows\Fonts\msyh.ttf",
        r"C:\Windows\Fonts\msyhbd.ttc",     # 微软雅黑 Bold
    ):
        if os.path.exists(path):
            QFontDatabase.addApplicationFont(path)
    # 注册符号/emoji 字体（页签与按钮上的 🖼🎬⚙ℹ✨▶ 等）
    # seguiemj=彩色 emoji；seguisym=几何符号。两款都要注册——
    # 少了 seguisym，⚙ ℹ ▶ ⏮ ⏭ 这类符号在部分系统上仍会变方块。
    for path in (
        r"C:\Windows\Fonts\seguiemj.ttf",   # Segoe UI Emoji
        r"C:\Windows\Fonts\seguiemj2.ttf",
        r"C:\Windows\Fonts\seguisym.ttf",   # Segoe UI Symbol
        r"C:\Windows\Fonts\seguisym2.ttf",
    ):
        if os.path.exists(path):
            QFontDatabase.addApplicationFont(path)
    # 设置全局默认字体：9 磅微软雅黑（QSS 里的 13px 会覆盖具体控件的字号）
    app.setFont(QFont("Microsoft YaHei UI", 9))


def apply_global_style(app: QApplication) -> None:
    """应用全局 QSS（唯一调用点：app.application.run）。

    程序启动时调用一次：先注册字体，再把整份样式表挂到 QApplication 上，
    之后所有窗口控件自动套用这套外观。
    """
    _setup_fonts(app)
    app.setStyleSheet(_QSS)
