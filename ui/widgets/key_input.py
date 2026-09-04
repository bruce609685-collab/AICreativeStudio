"""API KEY 相关控件：生成页警告条见 param_panel.KeyWarnBar；本文件为设置页输入面板。

KeyInputPanel 是模型设置页右侧的 KEY 配置面板：显示脚本路径与
模板版本，提供密码输入框（可显隐切换），点"确定"发出
key_confirmed 信号，由设置页负责真正把 KEY 写入脚本文件。
"""

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QHBoxLayout, QLabel, QLineEdit, QPushButton, QVBoxLayout, QWidget,
)

from ui import style


class KeyInputPanel(QWidget):
    """模型设置页的 API KEY 面板：路径/模板版本元信息 + 密码框 + 显示切换 + 确定。

    M1 演示：确定后仅更新界面状态并发出信号；
    M4 接入 core/keys.py 后真正把 KEY 写入脚本文件。
    """

    # 信号：点确定，参数是用户输入的 KEY（可为空=清空）
    key_confirmed = Signal(str)

    def __init__(self, parent=None) -> None:
        """构建面板：元信息两行 + 标题行 + 输入行。"""
        super().__init__(parent)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(12, 10, 12, 10)
        outer.setSpacing(6)

        # 脚本路径 / 模板版本 元信息（load_script 时更新）
        self._path_label = QLabel("路径：")
        self._tpl_label = QLabel("模板版本：")
        for lab in (self._path_label, self._tpl_label):
            lab.setStyleSheet("font-size:11px; color:#888; border:none;")
            lab.setWordWrap(True)

        title = QLabel("API KEY")
        title.setStyleSheet("font-size:12px; font-weight:600; border:none;")
        hint = QLabel("（无需编辑 py，确定后自动写入脚本）")
        hint.setStyleSheet("font-size:12px; color:#888; border:none;")

        # 输入行：密码框 + 显示切换 + 确定按钮
        row = QHBoxLayout()
        row.setSpacing(6)
        self._edit = QLineEdit()
        self._edit.setPlaceholderText("在此粘贴 API Key")
        self._edit.setEchoMode(QLineEdit.EchoMode.Password)
        self._toggle = QPushButton("显示")
        self._toggle.setStyleSheet("font-size:11px; padding:2px 9px;")
        # 信号槽：点显示/隐藏 → 切换密码框回显模式
        self._toggle.clicked.connect(self._toggle_visibility)
        confirm = QPushButton("确定")
        confirm.setProperty("class", "primary")
        confirm.setStyleSheet("font-size:11px; padding:2px 9px;")
        # 信号槽：点确定 → 发出 key_confirmed（写入逻辑在宿主页面）
        confirm.clicked.connect(self._confirm)
        row.addWidget(self._edit, stretch=1)
        row.addWidget(self._toggle)
        row.addWidget(confirm)

        outer.addWidget(self._path_label)
        outer.addWidget(self._tpl_label)
        title_row = QHBoxLayout()
        title_row.addWidget(title)
        title_row.addWidget(hint)
        title_row.addStretch(1)
        outer.addLayout(title_row)
        outer.addLayout(row)

    # ------------------------------------------------------------------

    def _toggle_visibility(self) -> None:
        """切换 KEY 输入框的显示/隐藏，按钮文字同步变化。"""
        hidden = self._edit.echoMode() == QLineEdit.EchoMode.Password
        self._edit.setEchoMode(
            QLineEdit.EchoMode.Normal if hidden else QLineEdit.EchoMode.Password
        )
        self._toggle.setText("隐藏" if hidden else "显示")

    def _confirm(self) -> None:
        """点确定：发出 key_confirmed 信号，携带当前输入的 KEY。"""
        self.key_confirmed.emit(self._edit.text())

    # ------------------------------------------------------------------

    def load_script(self, path: str, template_version: str, key_filled: bool,
                    current_key: str = "") -> None:
        """切换脚本时复位面板状态；current_key 回显已填 KEY（密码圆点）。

        参数：
            path: 脚本相对路径；template_version: 模板版本；
            key_filled: 是否已填 KEY（当前仅用于宿主状态栏刷新）；
            current_key: 已保存的 KEY（回显用）。
        """
        self._path_label.setText(f"路径：{path}")
        self._tpl_label.setText(f"模板版本：{template_version}")
        self._edit.clear()
        if current_key:
            self._edit.setText(current_key)
        # 恢复密码回显模式与按钮文字
        self._edit.setEchoMode(QLineEdit.EchoMode.Password)
        self._toggle.setText("显示")

    def status_text(self, key_filled: bool) -> str:
        """底部状态行文本。

        参数：key_filled: 是否已填 KEY。
        返回：状态描述文字。
        """
        if key_filled:
            return "✅ API KEY 已填写"
        return "⚠ API KEY 尚未填写"

    def status_color(self, key_filled: bool) -> str:
        """底部状态行颜色：已填绿色，未填警告橙。

        参数：key_filled: 是否已填 KEY。
        返回：CSS 颜色值。
        """
        return style.OK_GREEN if key_filled else style.WARN_TEXT
