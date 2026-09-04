"""生成计时器：长任务期间周期性回报"已等待秒数"（§3.1 计时进度需求）。

三个生成页（图/视/音）共用：生成开始时 start()，每 0.5 秒回调一次
on_tick(已等待秒数)，生成结束 stop()。本身不持有任何界面控件，
只负责计时与回调——显示成什么样由宿主页面决定（保持控件与业务分离）。

约定：长任务必须有实时反馈，不允许界面静默干等。
"""

import time

from PySide6.QtCore import QTimer


class ElapsedTimer:
    """轻量计时器：QTimer + monotonic 时钟，周期性回报等待秒数。

    关键属性：
    - _timer: 底层 QTimer（0.5 秒一跳）；
    - _t0: 计时起点（time.monotonic，不受系统改时间影响）；
    - _on_tick: 宿主注入的回调，参数为已等待秒数（float）。
    """

    def __init__(self, parent, on_tick) -> None:
        """绑定宿主与回调。

        参数：
            parent: Qt 父对象（QTimer 生命周期跟随它，页面销毁自动清理）；
            on_tick: 回调函数 on_tick(elapsed_seconds: float)。
        """
        self._on_tick = on_tick
        self._t0 = 0.0
        self._timer = QTimer(parent)
        self._timer.setInterval(500)   # 半秒一跳：肉眼可见的"活着"感，又不刷屏
        self._timer.timeout.connect(self._tick)

    def start(self) -> None:
        """开始计时：立即回调一次 0 秒，随后每 0.5 秒回调。"""
        self._t0 = time.monotonic()
        self._timer.start()
        self._on_tick(0.0)

    def stop(self) -> None:
        """停止计时（生成成功/失败收尾时调用）。"""
        self._timer.stop()

    def _tick(self) -> None:
        """QTimer 到点回调：换算成已等待秒数发给宿主。"""
        self._on_tick(time.monotonic() - self._t0)
