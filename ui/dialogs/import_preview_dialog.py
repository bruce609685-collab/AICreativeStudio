"""智能导入预览弹窗（还原预览文档 imp-modal）。

导入管线解析完成后、脚本落盘前的确认环节：列出每个将生成的脚本
（类别徽标 + 文件名 + 能力名 + 依赖提示），可逐个展开查看脚本代码，
用户勾选确认后点"确认导入"（exec() 返回 True）才真正写盘。

M5：由 core/importer 的真实解析结果填充。
scripts 参数：list[dict]，每项含 badge / name / ability / deps / warn / code。
"""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox, QDialog, QFrame, QHBoxLayout, QLabel, QPushButton,
    QScrollArea, QTextEdit, QVBoxLayout, QWidget,
)

# 类别徽标配色（与设置页一致）
BADGE_STYLE = {
    "图片": "background:#e3f2fd; color:#1565c0;",
    "视频": "background:#f3e5f5; color:#6a1b9a;",
    "语音": "background:#e8f5e9; color:#2e7d32;",
}
BADGE_MAP = {"image": "图片", "video": "视频", "audio": "语音"}


def scripts_to_preview(scripts) -> list[dict]:
    """ImportedScript 列表 → 预览弹窗数据。scripts 元素需有
    file_name / display_name / category / code / warn_deps。

    参数：scripts: 导入管线产出的脚本对象列表。
    返回：预览弹窗所需的数据字典列表。
    """
    out = []
    for s in scripts:
        # 无外部依赖默认文案；有依赖时给出黄色警告
        deps = "无外部依赖 · 模板版本 1.0.0"
        warn = False
        if getattr(s, "warn_deps", False):
            deps = "⚠ 依赖安装：请在「关于 → 安装依赖项」安装后再使用"
            warn = True
        out.append({
            "badge": BADGE_MAP.get(getattr(s, "category", "image"), "图片"),
            "name": s.file_name,
            "ability": s.display_name,
            "deps": deps,
            "warn": warn,
            "code": s.code,
        })
    return out


class ImportPreviewDialog(QDialog):
    """导入预览。exec() 返回 True=用户确认导入。"""

    def __init__(self, parent=None, scripts: list[dict] | None = None) -> None:
        """构建预览弹窗。

        参数：parent: 父窗口；scripts: 预览数据（scripts_to_preview 的结果）。
        """
        super().__init__(parent)
        self.setWindowTitle("智能导入预览")
        self.setMinimumWidth(620)
        self._items = scripts if scripts is not None else []
        self._build()

    def _build(self) -> None:
        """组装弹窗：摘要行 + 脚本条目滚动区 + 安全提示 + 底部按钮。"""
        v = QVBoxLayout(self)
        v.setContentsMargins(14, 13, 14, 13)
        v.setSpacing(10)

        # 摘要：脚本数量 + 模板版本
        summary = QLabel(
            f"共解析到 <b>{len(self._items)}</b> 个脚本 · 模板版本 <b>1.0.0</b>"
        )
        summary.setStyleSheet("color:#555;")
        v.addWidget(summary)

        # 脚本条目区（可滚动）
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        inner = QWidget()
        iv = QVBoxLayout(inner)
        iv.setContentsMargins(0, 0, 0, 0)
        iv.setSpacing(7)
        if not self._items:
            iv.addWidget(QLabel("没有可预览的脚本。"))
        for data in self._items:
            iv.addWidget(self._build_item(data))
        scroll.setWidget(inner)
        v.addWidget(scroll, stretch=1)

        # 安全提示：导入后去哪里填 KEY、勿提交真实 KEY
        warn = QLabel(
            "导入后请在「模型设置」用 API KEY 输入框填写密钥；勿在公开仓库提交真实 KEY。"
        )
        warn.setStyleSheet(
            "background:#fff8e1; border:1px solid #ffe082;"
            " color:#e65100; font-size:11px; padding:7px 10px;"
        )
        warn.setWordWrap(True)
        v.addWidget(warn)

        # 取消 / 确认按钮
        btn_row = QHBoxLayout()
        btn_row.addStretch(1)
        cancel = QPushButton("取消")
        cancel.clicked.connect(self.reject)
        confirm_btn = QPushButton(f"✅ 确认导入（{len(self._items)}个）")
        confirm_btn.setProperty("class", "primary")
        confirm_btn.clicked.connect(self.accept)
        btn_row.addWidget(cancel)
        btn_row.addWidget(confirm_btn)
        v.addLayout(btn_row)

    def _build_item(self, data: dict) -> QFrame:
        """构建单个脚本条目：勾选框 + 徽标 + 名称 + 能力 + 展开代码。

        参数：data: 预览数据字典（badge/name/ability/deps/warn/code）。
        返回：条目 QFrame。
        """
        item = QFrame()
        item.setStyleSheet("border:1px solid #d4d4d4; border-radius:1px;")
        wrap = QVBoxLayout(item)
        wrap.setContentsMargins(0, 0, 0, 0)
        wrap.setSpacing(0)

        # 头部行：勾选框（默认勾上）+ 类别徽标 + 文件名 + 能力名 + 展开箭头
        head = QWidget()
        hh = QHBoxLayout(head)
        hh.setContentsMargins(10, 7, 10, 7)
        hh.setSpacing(7)
        chk = QCheckBox()
        chk.setChecked(True)
        badge = QLabel(data["badge"])
        badge.setStyleSheet(
            f"padding:1px 5px; font-size:10px; font-weight:600; border-radius:2px;"
            f" {BADGE_STYLE[data['badge']]}"
        )
        name = QLabel(data["name"])
        name.setStyleSheet("font-weight:600;")
        ability = QLabel(data["ability"])
        ability.setStyleSheet("font-size:11px; color:#888;")
        arrow = QPushButton("▶")
        arrow.setStyleSheet("border:none; font-size:11px;")
        arrow.setCheckable(True)
        hh.addWidget(chk)
        hh.addWidget(badge)
        hh.addWidget(name, stretch=1)
        hh.addWidget(ability)
        hh.addWidget(arrow)
        wrap.addWidget(head)

        # 依赖提示行（有外部依赖时黄色警告样式）
        deps = QLabel(data["deps"])
        deps.setStyleSheet(
            "padding:5px 10px; font-size:11px; color:#555;"
            " background:#fafafa; border-top:1px solid #eee;"
            + (" background:#fff8e1; color:#e65100; font-weight:600;" if data["warn"] else "")
        )
        wrap.addWidget(deps)

        # 代码预览区（深色等宽，默认折叠，点箭头展开/收起）
        code = QTextEdit()
        code.setPlainText(data["code"])
        code.setReadOnly(True)
        code.setFixedHeight(90)
        code.setStyleSheet(
            "font-family:Consolas, monospace; font-size:11px;"
            " background:#1e1e1e; color:#d4d4d4; border:none; border-top:1px solid #eee;"
        )
        code.hide()
        wrap.addWidget(code)

        def toggle():
            """切换代码区显隐，箭头文字 ▶/▼ 同步翻转。"""
            code.setVisible(not code.isVisible())
            arrow.setText("▼" if code.isVisible() else "▶")
        arrow.clicked.connect(toggle)
        return item
