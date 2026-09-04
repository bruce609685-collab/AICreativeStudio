"""完备性门闸（headless）：检查 API 文档是否含生成脚本的必要/非必要信息。

在导入流程中，本模块站在"第一道关卡"的位置：用户粘贴完 API 文档、
还没调用 LLM 之前，先用简单的正则快速扫一遍文档内容。这样设计的好处是
——如果文档缺了关键信息，立刻就能告诉用户"缺什么、去补什么"，
而不是等 LLM 白白生成一个跑不通的脚本之后才发现问题。

检查分两档：
- 必要项（接口地址 / 认证方式 / 模型 ID）：缺一个就无法生成可用脚本
  → 阻断导入（UI 弹 GapRequiredDialog，让用户补文档）；
- 非必要项（seed / stream / web_search）：缺了也能生成，只是部分
  功能用不了 → 使用默认约定继续（UI 弹 GapOptionalDialog 知会一声）。

对应项目文档 §6.2：
- 必要项缺失 → 阻断导入（UI 弹 GapRequiredDialog）
- 非必要项缺失 → 使用默认约定继续（UI 弹 GapOptionalDialog）
"""

from __future__ import annotations

import re

# (中文名, 正则) —— 文档里出现即视为满足
# 必要项：缺了就肯定写不出能跑的脚本
REQUIRED_CHECKS = [
    # 接口地址：文档里出现任意 http/https 链接即认为给了 endpoint
    ("API 接口地址", r"https?://[^\s\"'<>]+"),
    # 认证方式：出现常见认证关键词（大小写不敏感）即可
    ("认证方式", r"(?i)(authorization|bearer|api[\s_-]?key|x-goog-api-key)"),
    # 模型 ID：出现 models/model 字样或中文"模型 ID/模型名"
    ("模型 ID", r"(?i)\bmodels?\b|模型\s*ID|模型名"),
]

# 非必要项：缺了不影响脚本生成，只是对应功能不可用（按默认约定关闭）
OPTIONAL_CHECKS = [
    ("随机种子（seed）", r"(?i)\bseed\b|种子"),
    ("流式输出（stream）", r"(?i)\bstream\b|流式"),
    ("联网搜索（web_search）", r"(?i)(web[\s_-]?search|grounding)|联网"),
]


def check_document(text: str) -> dict:
    """返回 {"required_missing": [名称], "optional_missing": [名称]}。

    用上面两组正则逐项扫描文档文本，凡是没有匹配到的条目就归入
    对应的 missing 列表。

    Args:
        text: 用户粘贴的 API 文档全文（纯文本）。

    Returns:
        dict，两个键都是"缺失项中文名"列表：
        - "required_missing"：缺失的必要项（非空则应阻断导入）；
        - "optional_missing"：缺失的非必要项（仅提示，可继续）。
        空文档视为全部缺失（UI 层先拦截空输入，这里兜底）。
    """
    required_missing = [
        name for name, pattern in REQUIRED_CHECKS
        if not re.search(pattern, text)
    ]
    optional_missing = [
        name for name, pattern in OPTIONAL_CHECKS
        if not re.search(pattern, text)
    ]
    return {
        "required_missing": required_missing,
        "optional_missing": optional_missing,
    }
