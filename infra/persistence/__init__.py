"""历史记录库（M3 起为权威来源，headless）。

persistence（持久化）子包负责"把数据存到磁盘并随时取回"，目前
包含 SQLite 历史记录库。所谓 headless，指本包不依赖任何界面库，
界面代码怎么改都不影响数据存取逻辑，反之亦然。

外部通过 `from infra.persistence import HistoryDatabase` 引用即可，
不必关心实现细节在哪个文件里。
"""

from infra.persistence.database import HistoryDatabase

# __all__ 声明本包对外提供的名字
__all__ = ["HistoryDatabase"]
