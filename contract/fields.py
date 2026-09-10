"""ACS_META 元数据块的解析与校验（契约层，headless）。

每个制式脚本的源码头部都写有一段 [ACS_META_START] ... [ACS_META_END]
标记包裹的元数据，声明这个脚本"叫什么、能做什么、支持哪些参数"。
本文件负责把这段文本读出来、检查是否合法、转换成 Python 字典，
供外壳（本程序的界面部分）决定如何展示和调用该脚本。

"headless"指本模块不依赖任何图形界面库，既能在外壳里运行，
也能在无界面的命令行环境运行。

字段全集见《脚本契约规范-v1.0.0.md》。解析只认本文件的字段表，
未知字段一律忽略——这是"契约只增不改"的落点：老外壳遇到新字段不炸，
新外壳读老脚本也兼容。
"""

from __future__ import annotations

import re

# 模板版本：写进每个脚本头部，外壳据此做版本门闸
# （版本不匹配时可以提示用户"脚本模板过旧/过新"）
TEMPLATE_VERSION = "1.0.0"

# 元数据块的起止标记：脚本头部必须恰好包含这一对标记，缺一不可
META_START = "[ACS_META_START]"
META_END = "[ACS_META_END]"

# ------------------------------------------------------------------
# 字段表：新增字段 = 在这里加一行 + 更新规范文档（契约只增不改）
# ------------------------------------------------------------------

# 布尔字段（true / false）
BOOL_FIELDS = {"stream", "web_search", "seed", "need_image", "sound"}
# 逗号分隔列表字段
LIST_FIELDS = {
    "resolutions", "ratios", "qualities", "formats", "durations", "voices",
    "modes", "pip_requires",
}
# 字符串字段
STR_FIELDS = {
    "display_name", "category", "function", "template_version", "key_env",
}
# 整数字段
INT_FIELDS = {"max_text_len"}

# 全部合法字段 = 四类字段表的并集（| 表示集合合并）；
# 解析时只认这个总表，表外的字段一律跳过
ALL_FIELDS = BOOL_FIELDS | LIST_FIELDS | STR_FIELDS | INT_FIELDS

# category（媒体类别）和 function（功能类型）的合法取值；
# 解析时会校验脚本写的值是否在范围内，防止拼错的值混进系统
CATEGORIES = {"image", "video", "audio"}
FUNCTIONS = {"t2i", "i2i", "t2v", "i2v", "tts", "voice_design"}

# pip 依赖字段的占位词：脚本作者想表达“无依赖”时常写成这些词，
# 它们不是真实包名。若不清洗，界面会列出可点击的“假包”，
# 点下去真的执行 pip install none，污染环境或直接报错。
PIP_PLACEHOLDERS = {
    "none", "null", "nil", "n/a", "na", "nan", "nothing",
    "no", "-", "--", "无", "无依赖", "无需", "空", "不需要",
}
# pip 包名规则（PEP 508）：字母数字开头结尾，中间可含 . _ -
PIP_NAME_RE = re.compile(r"^[A-Za-z0-9]([A-Za-z0-9._-]*[A-Za-z0-9])?$")


def normalize_pip_requires(items: list[str]) -> list[str]:
    """清洗 pip 依赖列表：剔除占位词与不符合包名规则的脏值。

    参数 items：原始字符串列表（META 里逗号拆分的产物）。
    返回值：干净的包名列表（小写、去重、保持原顺序）。
    """
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        name = item.strip().lower()
        if not name or name in PIP_PLACEHOLDERS:
            continue
        if not PIP_NAME_RE.match(name) or name in seen:
            continue
        seen.add(name)
        result.append(name)
    return result


class MetaParseError(ValueError):
    """ACS_META 解析失败（缺标记 / 字段值非法）。

    继承自 ValueError，调用方可以用 except ValueError 统一捕获，
    也可以单独捕获本类以区分"元数据坏了"和"其他值错误"。
    """


def _split_key_value(line: str) -> tuple[str, str] | None:
    """把一行 "key = value" 文本拆成 (键, 值) 二元组。

    会顺手剥掉行内注释（" # 注释"之后的内容不参与解析）。
    参数 line：待拆分的一行文本。
    返回值：(键, 值) 元组；若该行没有等号或键为空，返回 None（表示跳过此行）。
    """
    if "=" not in line:
        return None
    # partition 按第一个 "=" 切成三段：只切一次，值里再出现等号也安全
    key, _, value = line.partition("=")
    key = key.strip()
    value = value.strip()
    # " #"（井号前有空格）视为行内注释起点，截掉之后的内容
    idx = value.find(" #")
    if idx >= 0:
        value = value[:idx].strip()
    return (key, value) if key else None


def _parse_value(key: str, raw: str):
    """按字段类型把原始字符串转换成对应的 Python 值。

    参数 key：字段名（决定按哪种类型转换）；raw：原始文本值。
    返回值：bool / list / int / str（取决于字段类别）。
    异常：值的格式不符合字段类型要求时抛 MetaParseError。
    """
    raw = raw.strip()
    if key in BOOL_FIELDS:
        # 布尔字段只接受 true/false（不区分大小写），其他写法直接报错，
        # 避免 "yes"/"1" 之类的模糊写法造成歧义
        low = raw.lower()
        if low == "true":
            return True
        if low == "false":
            return False
        raise MetaParseError(f"字段 {key} 必须是 true/false，实际为 {raw!r}")
    if key in LIST_FIELDS:
        # 列表字段按逗号拆分，并过滤掉空项（比如连续逗号、末尾逗号）
        items = [item.strip() for item in raw.split(",") if item.strip()]
        # pip_requires 额外清洗：把 none 之类占位词与非法名挡在入口
        if key == "pip_requires":
            return normalize_pip_requires(items)
        return items
    if key in INT_FIELDS:
        try:
            return int(raw)
        except ValueError:
            # from None：吞掉原始异常链，报错信息只保留我们自己的提示
            raise MetaParseError(f"字段 {key} 必须是整数，实际为 {raw!r}") from None
    return raw


def parse_meta_block(text: str) -> dict:
    """从脚本源码文本中提取并解析 ACS_META 块。

    参数 text：整个脚本文件的源码文本。
    返回值：字典，键为合法字段名，值为转换后的数据（只包含脚本实际写了
    的字段，缺的字段由调用方补默认值——本函数不掺入默认值）。
    异常：找不到起止标记时抛 MetaParseError；category/function 写了
    非法取值同样抛 MetaParseError。
    """
    # 先定位起止标记的位置；find 找不到时返回 -1
    start = text.find(META_START)
    end = text.find(META_END)
    if start < 0 or end < 0 or end <= start:
        raise MetaParseError("缺少 [ACS_META_START]/[ACS_META_END] 标记")

    # 切出两个标记之间的纯元数据文本（跳过 META_START 自身的长度）
    raw = text[start + len(META_START):end]
    meta: dict = {}
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        # 兼容两种写法：纯 "key = value" 或注释态 "# key = value"
        # （注释态常用于"想临时关闭某个字段"的场景）
        if line.startswith("#"):
            line = line.lstrip("#").strip()
        if not line:
            continue
        pair = _split_key_value(line)
        if pair is None:
            continue
        key, value = pair
        if key not in ALL_FIELDS:
            continue  # 未知字段忽略（向前兼容）
        meta[key] = _parse_value(key, value)

    # 枚举校验（必要字段非法 → 阻断注册）
    # 只在脚本"写了"该字段时才校验取值范围；没写则交给调用方补默认值
    category = meta.get("category")
    if category is not None and category not in CATEGORIES:
        raise MetaParseError(f"category 必须是 {sorted(CATEGORIES)}，实际为 {category!r}")
    function = meta.get("function")
    if function is not None and function not in FUNCTIONS:
        raise MetaParseError(f"function 必须是 {sorted(FUNCTIONS)}，实际为 {function!r}")
    return meta
