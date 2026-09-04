"""《AI影音创造工坊》唯一入口（程序的"大门"）。

这个文件是整个桌面程序的启动点——当你双击运行或执行 `python main.py` 时，
操作系统加载的第一个就是它。它的职责刻意保持极简：不写任何业务逻辑，
只负责"选择走哪条路"：

- 普通启动 → 调用 app/application.py 里的 run()，拉起完整的图形界面（UI）；
- 带 `--run-script` 参数启动 → 调用 run_script_only()，不开界面，
  直接后台执行一条制式脚本（这是打包成 exe 后子进程的工作模式）。

真正的初始化工作（日志、数据库、窗口等）都在 app.application 模块里完成，
所以修改启动相关行为时，应去看那个文件，而不是这里。
用法：python main.py
"""

import sys

if __name__ == "__main__":
    # 检查命令行参数里是否带有 --run-script 开关，
    # 以此区分"正常打开软件"和"被父进程叫去后台干活"两种身份。
    if "--run-script" in sys.argv:
        # 打包后子进程模式：不启动 UI，直接执行制式脚本
        from app.application import run_script_only
        # run_script_only() 返回进程退出码（0 表示成功），交给操作系统
        sys.exit(run_script_only())
    else:
        from app.application import run
        # 同样以退出码结束：让打包器/脚本知道程序是正常退出还是出错
        sys.exit(run())
