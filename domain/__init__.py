"""领域层：纯数据模型，零外部依赖（禁止 import PySide6 / 第三方库）。

domain（领域）层存放的是"程序要处理的数据本身"——比如一个脚本是什么、
一项任务处于什么状态。因为完全不依赖界面库和第三方库，这一层最稳定，
其他所有层（界面、契约、基础设施）都可以安全地引用它；反过来它不
引用任何其他层，避免形成循环依赖。

本文件把层内最常用的几个名字（枚举和数据类）在这里"转发"一次，
外部就可以直接写 `from domain import ScriptMeta`，不用记住具体文件。
"""

from domain.enums import JobStatus, MediaCategory
from domain.models import ScriptMeta

# __all__ 声明"对外提供哪些名字"：既方便阅读，也防止 `import *` 时
# 把不想暴露的内部名字带出去
__all__ = ["JobStatus", "MediaCategory", "ScriptMeta"]
