"""脚本注册域：扫描 scripts/ + 解析 ACS_META + 内存注册表。

每个脚本文件头部都有一段 ACS_META 注释块（# 键 = 值 的形式），
声明它的名字、类别（图/视频/音频）、支持的能力（分辨率、比例、
是否支持种子等）。本包的工作就是把这些信息"登记造册"：

- scanner.py：递归扫描 scripts/ 目录找出所有 .py 脚本；
- meta_parser.py：读取单个脚本、解析 ACS_META 注释块，转成统一的
  ScriptMeta 数据对象；
- script_registry.py：内存注册表，把所有 ScriptMeta 按类别索引，
  供界面查询（如"列出所有图片脚本"）和运行器查参数。

程序启动时加载一次，导入新脚本后重新加载。对外只暴露
ScriptRegistry 和 scan_scripts_dir 两个入口。
"""

from core.registry.scanner import scan_scripts_dir
from core.registry.script_registry import ScriptRegistry

__all__ = ["ScriptRegistry", "scan_scripts_dir"]
