"""py 脚本文件 → ScriptMeta（registry 域）。

每个脚本文件的 docstring 里都嵌着一段 ACS_META 注释块（形如
"# display_name = xxx"），这是脚本"自报家门"的标准方式。本模块
负责读取单个脚本文件，把这段注释解析成结构化的 ScriptMeta 对象——
它是注册表（script_registry）和扫描器（scanner）之间的桥梁。

解析本身（如何从文本里抠出键值对）在 contract.fields.parse_meta_block
中实现；本模块做的是"组装"：把解析结果填进 ScriptMeta 的各个字段，
缺的字段给默认值（比如类别默认 image）。
"""

from pathlib import Path

from contract.fields import TEMPLATE_VERSION, parse_meta_block
from contract.version import check_template_version
from domain.enums import MediaCategory
from domain.models import ScriptMeta


def build_script_meta(path: Path, base_dir: Path) -> ScriptMeta:
    """读取脚本文件、解析 ACS_META，映射为 ScriptMeta。

    处理流程：读全文 → parse_meta_block 解析注释块 → 逐字段填入
    ScriptMeta（缺省值兜底）。file_path 存的是相对 scripts/ 根目录
    的路径（统一 "/" 分隔），这样换电脑、换系统后注册表依然有效。

    Args:
        path: 脚本文件的绝对/相对路径。
        base_dir: scripts/ 根目录，用于计算相对路径。

    Returns:
        填充完毕的 ScriptMeta 对象。

    Raises:
        MetaParseError: 文件里没有合法的 ACS_META 块；
        ValueError: category 值不在 MediaCategory 枚举内等。
        两者都由调用方（scanner）捕获并跳过该文件。
    """
    text = path.read_text(encoding="utf-8", errors="replace")
    meta = parse_meta_block(text)

    try:
        rel = path.resolve().relative_to(base_dir.resolve())
        rel_str = rel.as_posix()  # 统一 "/" 分隔，跨平台可移植
    except ValueError:
        rel_str = path.name

    # §5.4 契约版本门闸：比较脚本声明版本与外壳支持版本，
    # 结论（ok/older/newer）随 meta 下发，由界面决定怎么提示。
    # 只提示不阻断——契约"只增不改"，旧脚本永远可用。
    declared_version = meta.get("template_version", TEMPLATE_VERSION)
    compat = check_template_version(declared_version)

    return ScriptMeta(
        display_name=meta.get("display_name", path.stem),
        category=MediaCategory(meta.get("category", "image")),
        function=meta.get("function", "t2i"),
        file_path=rel_str,
        template_version=declared_version,
        version_compat=compat,
        seed=meta.get("seed", False),
        stream=meta.get("stream", False),
        web_search=meta.get("web_search", False),
        sound=meta.get("sound", False),
        need_image=meta.get("need_image", False),
        resolutions=meta.get("resolutions", []),
        ratios=meta.get("ratios", []),
        qualities=meta.get("qualities", []),
        formats=meta.get("formats", []),
        durations=meta.get("durations", []),
        modes=meta.get("modes", []),
        voices=meta.get("voices", []),
        max_text_len=meta.get("max_text_len", 1000),
        key_env=meta.get("key_env", ""),
        key_required=True,
        pip_requires=meta.get("pip_requires", []),
    )
