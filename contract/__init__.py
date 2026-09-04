"""契约层：外壳与制式脚本共用的稳定定义。

"契约"指本程序（外壳）与一个个制式脚本之间约定好的"对话规则"——
脚本头部要写什么元数据、外壳传什么参数、脚本怎么汇报结果。
只要双方都遵守契约，脚本可以随时增删，外壳不用改一行代码。

子模块：
- fields：ACS_META 元数据块的解析与校验（脚本头部）
- version：template_version 模板版本比较与兼容性结论（§5.4）
- params：入参 JSON 的键名与组装（外壳 → 脚本）
- result：出参 JSON 的解析与错误码（脚本 → 外壳）

契约只增不改（老脚本长期可用）；字段变更必须同步《脚本契约规范》文档。
本层与 domain 层一样是 headless 的，不依赖任何界面库。
"""

from contract.fields import TEMPLATE_VERSION
from contract.params import K_MOCK
from contract.result import (
    ERR_API_ERROR,
    ERR_AUTH_FAILED,
    ERR_BLOCKED,
    ERR_INTERNAL,
    ERR_INVALID_PARAMS,
    ERR_NETWORK,
    ERR_TIMEOUT,
)
from contract.version import check_template_version, parse_version

# __all__ 声明对外提供的名字：其他模块写 `from contract import ERR_NETWORK`
# 即可使用，不必关心具体定义在哪个子文件里
__all__ = [
    "TEMPLATE_VERSION",
    "K_MOCK",
    "ERR_API_ERROR",
    "ERR_AUTH_FAILED",
    "ERR_BLOCKED",
    "ERR_INTERNAL",
    "ERR_INVALID_PARAMS",
    "ERR_NETWORK",
    "ERR_TIMEOUT",
    "check_template_version",
    "parse_version",
]
