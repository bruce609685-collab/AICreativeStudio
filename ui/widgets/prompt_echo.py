"""提示词回看条（v0.1.5 新增：只读、可复制）。

预览区下方的一行小条：显示"点击历史或预览格后当时的提示词"，
内容只读、可一键复制，避免用户翻记录找回提示词。
"""

from PySide6.QtWidgets import QHBoxLayout, QLabel, QLineEdit, QPushButton, QWidget


class PromptEcho(QWidget):
    """label + 只读输入框 + 复制按钮（还原 .prompt-reveal）。"""

    def __init__(self, initial: str = "", parent=None) -> None:
        """构建回看条。

        参数：initial: 初始显示的文本。
        """
        super().__init__(parent)
        self.setStyleSheet(
            "border:1px solid #d4d4d4; background:#fafafa;"
        )
        row = QHBoxLayout(self)
        row.setContentsMargins(8, 6, 8, 6)
        row.setSpacing(6)

        label = QLabel("提示词")
        label.setStyleSheet(
            "font-size:11px; font-weight:600; color:#555; border:none; background:transparent;"
        )
        # 只读输入框：显示回看的提示词
        self._edit = QLineEdit(initial)
        self._edit.setReadOnly(True)
        self._edit.setToolTip("点击历史或预览格后显示当时提示词，可复制")
        self._edit.setStyleSheet("font-size:12px; border:none; background:#ffffff;")
        btn = QPushButton("复制")
        btn.setStyleSheet("font-size:11px; padding:2px 9px;")
        # 信号槽：点复制 → 全选并复制到剪贴板
        btn.clicked.connect(self._copy)

        row.addWidget(label)
        row.addWidget(self._edit, stretch=1)
        row.addWidget(btn)

    def _copy(self) -> None:
        """全选内容并复制到系统剪贴板。"""
        self._edit.selectAll()
        self._edit.copy()

    def set_text(self, text: str) -> None:
        """更新显示的提示词；空文本显示占位说明。

        参数：text: 提示词文本。
        """
        self._edit.setText(text or "（无提示词记录）")

    def text(self) -> str:
        """返回当前显示的提示词文本。"""
        return self._edit.text()
