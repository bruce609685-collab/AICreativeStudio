"""装配层：把各模块组装成可运行程序。

app 包是程序的"启动与系统级事务"层：进程怎么起、日志怎么配、
文件放哪里、如何防止重复打开，都归它管。它向下引用 infra（基础
设施）和 core 等模块，向上被 main.py 调用；与 domain/contract
的纯定义不同，本包允许 import PySide6（因为创建 QApplication 必须用它）。

职责边界：application（入口装配）、single_instance（单实例）、
logger_setup（日志）、paths（路径常量）。本包允许 import PySide6。
"""

def run(*args, **kwargs):
    """启动程序入口（延迟导入 application）。

    为何延迟：application 会 import ui.main_window，而 ui 各页面又需要
    `from app import paths`。若在包顶层直接 `from app.application import run`，
    就会出现 app → application → ui → app 的循环导入，直接
    `import ui.main_window` 会报 partially initialized module 错误。
    改成函数内导入后，`from app import paths` 不再连带加载 application。

    参数：透传给 app.application.run（argv 等）。
    返回：app.application.run 的返回值（进程退出码）。
    """
    from app.application import run as _run
    return _run(*args, **kwargs)


# __all__ 声明对外只暴露 run()：外部写 `from app import run` 即可启动程序
__all__ = ["run"]
