"""契约模板版本校验（contract 层，headless）。

脚本头部 ACS_META 声明 template_version（如 "1.0.0"），外壳加载时
要拿它和自己支持的版本（TEMPLATE_VERSION）比一比：
- 相等 → 兼容，放行；
- 脚本版本更旧 → 提示"脚本模板过旧"（容错放行：契约"只增不改"，
  旧脚本永远可用，只是给用户一句提醒）；
- 脚本版本更新 → 提示"请升级主程序"（同样放行，未知字段会被
  解析器忽略，但新字段对应的能力界面可能没跟上，提醒用户升级）。

三种情况都不阻断注册——门闸只负责"告诉用户实话"，不负责把脚本
拒之门外。真正会阻断注册的（META 缺失、category 非法）在
parse_meta_block 里已处理。

版本比较按语义化版本（Semantic Versioning）三段式：
主版本.次版本.修订号，逐段比大小，缺段按 0 处理（"1.2" == "1.2.0"）。
"""

from contract.fields import TEMPLATE_VERSION

# 语义化版本前缀：允许脚本写 "v1.0.0" / "V1.0.0"，比较时剥掉
_VER_PREFIXES = ("v", "V")


def parse_version(text: str) -> tuple[int, ...]:
    """把版本字符串解析成可比较的整数元组。

    规则：
    - 剥掉可选的 v/V 前缀（"v1.0.0" → "1.0.0"）；
    - 按 "." 切分，每段转 int；非数字段按 0 处理（如 "1.0.0-beta" 的
      "0-beta" → 0，宽容处理不抛异常）；
    - 缺段按 0 补齐到三段（"1.2" → (1, 2, 0)）；
    - 超过三段只取前三段（主.次.修订之外的段忽略）。

    参数 text：版本字符串（如 "1.0.0"）。
    返回值：(主, 次, 修订) 整数三元组。
    """
    text = (text or "").strip()
    if text.startswith(_VER_PREFIXES):
        text = text[1:]
    parts: list[int] = []
    for seg in text.split(".")[:3]:
        # 每段只取开头的连续数字（"0-beta" → 0）
        digits = ""
        for ch in seg:
            if ch.isdigit():
                digits += ch
            else:
                break
        parts.append(int(digits) if digits else 0)
    while len(parts) < 3:
        parts.append(0)
    return (parts[0], parts[1], parts[2])


def check_template_version(script_version: str,
                           shell_version: str = TEMPLATE_VERSION) -> str:
    """比较脚本模板版本与外壳支持版本，返回兼容性结论。

    Args:
        script_version: 脚本 ACS_META 声明的 template_version
            （空串按与外壳同版本处理——meta_parser 已对缺省字段
            填了当前版本，这里再兜一层底）。
        shell_version: 外壳支持的版本（默认取 contract 当前版本）。

    Returns:
        三选一的结论字符串：
        - "ok"：版本一致，完全兼容；
        - "older"：脚本模板比外壳旧（提示"脚本模板过旧"）；
        - "newer"：脚本模板比外壳新（提示"请升级主程序"）。
    """
    script_v = parse_version(script_version) if script_version \
        else parse_version(shell_version)
    shell_v = parse_version(shell_version)
    if script_v == shell_v:
        return "ok"
    return "older" if script_v < shell_v else "newer"
