"""通用确认弹窗 + 完备性门闸两级弹窗（必要缺失 / 非必要缺失）。

包含三个部分：
  - confirm()：通用"是/否"确认框的工具函数；
  - GapRequiredDialog：必要项缺失弹窗——文档缺少关键信息（如接口地址），
    只能关闭去补充文档，导入被阻断；
  - GapOptionalDialog：非必要项缺失弹窗——可以"继续（使用默认参数）"
    或关闭取消导入。
"""

from PySide6.QtWidgets import (
    QDialog, QHBoxLayout, QLabel, QMessageBox, QPushButton, QVBoxLayout, QWidget,
)


def confirm(parent: QWidget, title: str, text: str) -> bool:
    """通用确认对话框，返回 True=用户选了"是"。

    参数：parent: 父窗口；title: 标题；text: 提示正文。
    返回：用户是否确认。
    """
    return QMessageBox.question(parent, title, text) == QMessageBox.StandardButton.Yes


class GapRequiredDialog(QDialog):
    """完备性 - 必要项缺失：阻断导入，仅可关闭。

    gaps：缺口名称列表（如 ["API 接口地址"]）；缺省用内置示例。
    """

    # 内置示例缺口（测试/演示用；实际由导入管线传入真实缺口）
    GAPS = [
        "API 接口地址",
        "认证方式",
        "模型 ID",
    ]

    def __init__(self, parent=None, gaps: list[str] | None = None) -> None:
        """构建阻断弹窗。

        参数：parent: 父窗口；gaps: 缺口名称列表（None 用内置示例）。
        """
        super().__init__(parent)
        self.setWindowTitle("无法完成智能导入")
        self.setMinimumWidth(440)
        v = QVBoxLayout(self)
        v.setContentsMargins(13, 13, 13, 13)
        v.setSpacing(8)

        # 说明 + 逐条列出缺口
        intro = QLabel(
            "API 接入文档未包含下列<b>必要</b>说明，请补充后再导入："
        )
        intro.setWordWrap(True)
        v.addWidget(intro)
        for gap in (gaps if gaps is not None else self.GAPS):
            v.addWidget(QLabel(f"• API 接入文档未包含「{gap}」说明，请补充。"))
        tip = QLabel("建议补充完整请求示例（URL、Header、Body）及成功响应示例。")
        tip.setStyleSheet("font-size:12px; color:#666;")
        tip.setWordWrap(True)
        v.addWidget(tip)

        # 只有"关闭"按钮——必要项缺失不允许继续
        btn_row = QHBoxLayout()
        btn_row.addStretch(1)
        close = QPushButton("关闭")
        close.setProperty("class", "primary")
        close.clicked.connect(self.accept)
        btn_row.addWidget(close)
        v.addLayout(btn_row)


class GapOptionalDialog(QDialog):
    """完备性 - 非必要项缺失：可关闭，也可"继续（使用默认参数）"。

    gaps：缺口名称列表；缺省用内置示例。
    """

    # 内置示例缺口（可被默认约定兜底的项）
    DEFAULTS = [
        "随机种子（seed）",
        "流式输出（stream）",
        "联网搜索（web_search）",
    ]

    def __init__(self, parent=None, on_continue=None,
                 gaps: list[str] | None = None) -> None:
        """构建可选继续弹窗。

        参数：
            parent: 父窗口；on_continue: 用户点"继续"后的回调；
            gaps: 缺口名称列表（None 用内置示例）。
        """
        super().__init__(parent)
        self.setWindowTitle("接入文档部分说明缺失")
        self.setMinimumWidth(440)
        self._on_continue = on_continue

        v = QVBoxLayout(self)
        v.setContentsMargins(13, 13, 13, 13)
        v.setSpacing(8)

        intro = QLabel("已能生成基本可用脚本，但文档未包含下列说明，将使用默认约定：")
        intro.setWordWrap(True)
        v.addWidget(intro)
        for gap in (gaps if gaps is not None else self.DEFAULTS):
            v.addWidget(QLabel(f"• {gap} → 使用默认约定"))

        # "关闭"=放弃导入；"继续"=用默认参数走导入
        btn_row = QHBoxLayout()
        btn_row.addStretch(1)
        close = QPushButton("关闭")
        close.clicked.connect(self.reject)
        cont = QPushButton("继续（使用默认参数）")
        cont.setProperty("class", "primary")
        cont.clicked.connect(self._continue)
        btn_row.addWidget(close)
        btn_row.addWidget(cont)
        v.addLayout(btn_row)

    def _continue(self) -> None:
        """点"继续"：关闭弹窗并触发宿主传入的继续回调。"""
        self.accept()
        if self._on_continue is not None:
            self._on_continue()
