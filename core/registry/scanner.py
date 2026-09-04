"""扫描 scripts/ 目录 → ScriptMeta 列表（registry 域）。

注册表的数据来源就在这里：把 scripts/ 目录整个翻一遍，找出所有
Python 脚本，交给 meta_parser 解析出元信息。它对坏文件的策略很
宽容——单个脚本 META 写错了只记一条警告日志并跳过，绝不让一个
坏文件拖垮整个应用的启动。

扫描完成后把结果列表交给 ScriptRegistry.load() 建立索引。
"""

import logging
from pathlib import Path

from contract.fields import MetaParseError
from core.registry.meta_parser import build_script_meta
from domain.models import ScriptMeta

logger = logging.getLogger(__name__)


def scan_scripts_dir(root: Path) -> list[ScriptMeta]:
    """递归扫描 root 下所有 .py；坏文件跳过并记 warning。

    扫描规则：
    - 递归遍历所有子目录（image_scripts/video_scripts/... 都会扫到）；
    - 下划线开头的文件（如 __init__.py）视为内部文件，跳过；
    - 单个文件解析失败（META 缺失/格式错误）只警告不中断。

    不强制 category 与子目录同名——category 以 ACS_META 声明为准，
    子目录（image_scripts 等）只为人工组织方便。

    Args:
        root: scripts/ 根目录。

    Returns:
        解析成功的 ScriptMeta 列表（按文件名排序）；目录不存在
        返回空列表。
    """
    found: list[ScriptMeta] = []
    if not root.exists():
        logger.warning("脚本目录不存在：%s", root)
        return found
    for path in sorted(root.rglob("*.py")):
        if path.name.startswith("_"):
            continue  # 跳过 __init__.py 等私有文件
        try:
            found.append(build_script_meta(path, root))
        except (MetaParseError, ValueError) as exc:
            # 坏文件不拖垮整体：记警告后继续扫下一个
            logger.warning("跳过脚本 %s：%s", path.name, exc)
    return found
