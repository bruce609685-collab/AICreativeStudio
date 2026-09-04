"""界面层。与 app/ 并列，是仅有的两个允许 import PySide6 的层。

本层只负责界面展示与用户交互，业务逻辑在 core/ 中；
对外仅暴露 MainWindow（主窗口是整个界面的入口）。
"""

__all__ = ["MainWindow"]
