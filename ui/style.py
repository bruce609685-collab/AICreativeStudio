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

_QSS = f"""
* {{
    font-family: "Microsoft YaHei UI", "Segoe UI", sans-serif;
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
    background: #ffffff;
}}
QCheckBox::indicator:checked {{
    border-color: {BLUE};
    background: {BLUE};
    image: none;
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
    # 注册 emoji 字体（页签图标 🖼🎬 等）
    for path in (
        r"C:\Windows\Fonts\seguiemj.ttf",   # Segoe UI Emoji（页签图标）
        r"C:\Windows\Fonts\seguiemj2.ttf",
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
