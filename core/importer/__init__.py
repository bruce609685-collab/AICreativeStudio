"""智能导入域：LLM 客户端 + 完备性门闸 + 配置 + 导入管线。

"智能导入"是这个应用最省心的功能：用户不用会写代码，只要把某家
AI 服务的 API 文档（网页文本/PDF 内容）粘贴进来，程序就会：
1. 先做完备性检查（completeness）——文档里该有的信息（接口地址、
   认证方式、模型 ID）缺没缺，缺了就提示用户补充；
2. 调用 LLM（llm_client）——把文档喂给大模型，让它自动写出一个
   符合本项目规范的脚本（含 ACS_META 头部注释）；
3. 走导入管线（pipeline）——校验 LLM 生成的 META、修格式、补默认
   值、落盘到 scripts/ 目录，最终交给注册表登记上架。

config.py 负责把 LLM 的连接设置（接口地址、KEY、模型名、是否 mock）
持久化到 data/config.json。本包对外只暴露上面这些常用入口。
"""

from core.importer.completeness import check_document
from core.importer.config import load_llm_config, save_llm_config
from core.importer.llm_client import LLMConfig, call_llm, mock_generate_scripts
from core.importer.pipeline import (
    ImportResult,
    ImportedScript,
    import_from_document,
    save_scripts,
)

__all__ = [
    "ImportResult",
    "ImportedScript",
    "LLMConfig",
    "call_llm",
    "check_document",
    "import_from_document",
    "load_llm_config",
    "mock_generate_scripts",
    "save_llm_config",
    "save_scripts",
]
