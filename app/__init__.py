"""装配层：把各模块组装成可运行程序。

app 包是程序的"启动与系统级事务"层：进程怎么起、日志怎么配、
文件放哪里、如何防止重复打开，都归它管。它向下引用 infra（基础
设施）和 core 等模块，向上被 main.py 调用；与 domain/contract
的纯定义不同，本包允许 import PySide6（因为创建 QApplication 必须用它）。

职责边界：application（入口装配）、single_instance（单实例）、
logger_setup（日志）、paths（路径常量）。本包允许 import PySide6。
"""

from app.application import run

# __all__ 声明对外只暴露 run()：外部写 `from app import run` 即可启动程序
__all__ = ["run"]
