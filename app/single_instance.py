"""单实例运行（长期交付约定）：已运行则不再开第二个。

如果不做限制，用户双击两次图标就会开出两个程序窗口，可能同时写
同一个数据库、产生难以排查的冲突。本文件用"命名管道"实现互斥：
第一个实例会占住一个以程序 ID 命名的管道，后续实例一连接就知道
"前面已经有人了"，于是自动退出。

实现：QLocalServer 命名管道。第二次启动时尝试连接同名管道，
连得上说明已有实例 → 激活既有窗口并退出本进程。
"""

import logging

from PySide6.QtNetwork import QLocalServer, QLocalSocket

from about import APP_ID

logger = logging.getLogger(__name__)


class SingleInstance:
    """跨进程单实例守卫。用法：guard = SingleInstance(); guard.try_lock()。

    内部靠一个 QLocalServer（命名管道服务端）实现"占坑"：
    - try_lock() 成功 → 本进程是首个实例，管道被本进程监听；
    - try_lock() 失败 → 管道被占用，说明已有实例在运行。
    程序退出前应调用 release() 把管道释放干净。
    """

    def __init__(self) -> None:
        # _server 保存监听中的管道服务端；None 表示尚未持有锁
        self._server: QLocalServer | None = None

    def try_lock(self) -> bool:
        """尝试占用实例锁。True=本进程是首个实例；False=已有实例。

        无参数；返回值决定调用方（app/application.py 的 run()）是
        继续启动还是弹窗提示后退出。
        """
        # 第一步：以"客户端"身份试着连接同名管道。
        # 能连上 = 有别的实例正在监听 = 程序已经开过了
        socket = QLocalSocket()
        socket.connectToServer(APP_ID)
        if socket.waitForConnected(300):
            socket.disconnectFromServer()
            logger.warning("another instance is running, exit")
            return False

        # 残留的崩溃管道先清掉再监听
        # （上次程序异常退出时管道可能没来得及释放，会误导本次判断）
        QLocalServer.removeServer(APP_ID)
        self._server = QLocalServer()
        self._server.listen(APP_ID)
        logger.debug("single-instance lock acquired")
        return True

    def release(self) -> None:
        """释放实例锁（程序正常退出时调用）。

        关闭并丢弃监听中的管道服务端；若从未成功加锁则什么都不做，
        重复调用也安全。
        """
        if self._server is not None:
            self._server.close()
            self._server = None
