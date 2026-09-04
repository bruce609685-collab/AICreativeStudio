"""内存注册表：按类别索引 ScriptMeta，提供查询（registry 域）。

扫描器把 scripts/ 目录翻出来的所有脚本元信息，最终都存进这里。
它是整个应用认识"我有哪些脚本"的唯一数据源：界面左侧的脚本列表、
创建任务时可选的分辨率/比例选项、运行时查脚本路径，全都查它。

数据在启动时一次性加载，运行期只读不写——这样界面随便查都不会
有并发问题；导入新脚本后会重新扫描并 load() 一遍完成"上架"。
"""

from domain.enums import MediaCategory
from domain.models import ScriptMeta


class ScriptRegistry:
    """脚本内存注册表。

    代表"当前应用里登记在册的所有脚本"，内部维护两份数据：
    一份全量列表 _all，一份按类别分组的索引 _by_category，
    两份数据在 load() 时同步建立。

    关键属性：
    - _all: 所有 ScriptMeta 的列表（按扫描顺序，即文件名序）；
    - _by_category: {MediaCategory: [ScriptMeta]} 的类别索引。

    使用场景：启动时 load() 一次；界面用 by_category()/all 展示
    列表，运行器用 get() 按路径查脚本详情。
    """

    def __init__(self) -> None:
        self._all: list[ScriptMeta] = []
        self._by_category: dict[MediaCategory, list[ScriptMeta]] = {}

    def load(self, metas: list[ScriptMeta]) -> None:
        """（重新）加载脚本列表并重建类别索引。

        每次调用都是整体替换（不是追加），因此导入新脚本后
        重新扫描一遍再 load 即可完成刷新。

        Args:
            metas: scan_scripts_dir 扫出的 ScriptMeta 列表。
        """
        self._all = list(metas)
        self._by_category = {}
        for meta in self._all:
            self._by_category.setdefault(meta.category, []).append(meta)

    def by_category(self, category: MediaCategory) -> list[ScriptMeta]:
        """该类别的脚本列表（按扫描顺序，即文件名序）。

        Args:
            category: 脚本类别枚举（IMAGE/VIDEO/AUDIO）。

        Returns:
            该类别下所有 ScriptMeta 的副本列表（外部改不动内部数据）。
        """
        return list(self._by_category.get(category, []))

    def get(self, file_path: str) -> ScriptMeta | None:
        """按相对 scripts/ 的路径查脚本。

        Args:
            file_path: 相对路径（如 "image_scripts/xxx.py"）。

        Returns:
            匹配的 ScriptMeta；不存在返回 None。
        """
        for meta in self._all:
            if meta.file_path == file_path:
                return meta
        return None

    def count(self) -> int:
        """在册脚本总数。"""
        return len(self._all)

    @property
    def all(self) -> list[ScriptMeta]:
        """全部脚本列表的副本（按扫描顺序）。"""
        return list(self._all)
