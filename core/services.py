"""core 层统一服务出口（§9.2"包出口收敛"）。

§9.2 依赖规则：ui 层不许直接 import infra（界面层不碰数据层，
一律走 core 服务）。本文件把 ui 需要的 infra 能力收拢为 core 出口：

- HistoryDatabase：历史记录库（infra/persistence 的核心类），
  ui 通过 `from core.services import HistoryDatabase` 取用，
  由 app 装配层创建实例后注入各页。

core 可以 import infra（依赖方向允许），ui 不行——这就是本文件
存在的意义：让"ui 不碰 infra"有物理载体。
"""

from infra.persistence import HistoryDatabase

__all__ = ["HistoryDatabase"]
