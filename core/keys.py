"""API KEY 检测/注入/清除。

这个模块解决一个很实际的问题：脚本要调用 AI 服务的 API，就需要一把
"钥匙"（API KEY），但用户是非程序员，不能指望他们打开代码文件手动粘贴。
所以本模块提供了"把 KEY 直接写进脚本文件"的能力。

三个功能：
- 检测（detect_key_status）：判断某个脚本现在有没有可用的 KEY——
  先看脚本文件里有没有写 API_KEY = "..."，再看系统环境变量里有没有；
- 注入（inject_key）：把用户在"模型设置"页面输入的 KEY 写入脚本文件
  （只替换 API_KEY 那一行，其他代码一律不动）；
- 清除（clear_key）：把 KEY 清成空串，等于"忘记"这把钥匙。

在整体架构中的角色：界面层（模型设置页、脚本详情页）调用本模块；
脚本真正运行时（runner 子进程里）会读取自己文件里的 API_KEY 常量。
KEY 是明文落盘的（本地单机场景下可接受），文档须明示这一风险。

M2：detect_key_status —— 检测脚本是否已有可用 KEY（脚本内 API_KEY 或环境变量）。
M4：inject_key / clear_key —— 把模型设置页输入的 KEY 写入脚本文件，
不要求用户打开代码。KEY 明文落盘（本地场景可接受），文档须明示风险。
"""

import logging
import os
import re
from pathlib import Path

from domain.models import ScriptMeta

logger = logging.getLogger(__name__)

# 匹配脚本内的 KEY 常量（支持 \" 转义；优先双引号，兼容单引号）
# 这两个正则都要求 API_KEY = "..." 出现在"行首"（前面只允许空白），
# 这样不会误匹配到注释或字符串里提到 API_KEY 的地方
_API_KEY_PATTERN = re.compile(
    r'^\s*API_KEY\s*=\s*"(?P<key>(?:[^"\\]|\\.)*)"', re.MULTILINE
)
_API_KEY_SINGLE = re.compile(
    r"^\s*API_KEY\s*=\s*'(?P<key>(?:[^'\\]|\\.)*)'", re.MULTILINE
)


def _match_key(text: str):
    """在脚本全文中查找 API_KEY 赋值行。

    Args:
        text: 脚本文件的完整文本。

    Returns:
        匹配到的正则对象（可取 .group("key") 拿到 KEY 值），
        没找到返回 None。双引号写法优先，其次兼容单引号。
    """
    return _API_KEY_PATTERN.search(text) or _API_KEY_SINGLE.search(text)


def detect_key_status(script_path: Path, meta: ScriptMeta) -> str:
    """返回 'ok'（脚本内 KEY 或环境变量可用）或 'missing'。

    检测顺序（找到任意一个可用 KEY 即算 ok）：
    1. 脚本本身声明不需要 KEY（key_required=False，如纯本地生成）→ ok；
    2. META 里指定的环境变量（key_env）在系统里有值 → ok；
    3. 打开脚本文件，看有没有写 API_KEY = "..." 且值非空 → ok；
    4. 都不行 → missing（界面据此提示用户去填 KEY）。

    key_required=False 的脚本（如纯本地生成）恒为 'ok'。
    """
    if not meta.key_required:
        return "ok"
    if meta.key_env and os.environ.get(meta.key_env):
        return "ok"
    try:
        text = Path(script_path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return "missing"
    match = _match_key(text)
    if match and match.group("key"):
        return "ok"
    return "missing"


def read_key(script_path: str | Path) -> str:
    """读取脚本内已写入的 API_KEY 值；未写入/读失败返回空串。"""
    try:
        text = Path(script_path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    match = _match_key(text)
    return match.group("key") if match else ""


def inject_key(script_path: str | Path, api_key: str) -> bool:
    """把 API_KEY 写入脚本文件（只替换 API_KEY 行，不动其他代码）。

    值为空串 = 清空。KEY 明文落盘（本地场景，文档已明示风险）。
    返回是否写入成功。
    """
    path = Path(script_path)
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        logger.error("无法读取脚本 %s：%s", path, exc)
        return False

    # 先把 KEY 里的特殊字符转义（反斜杠和双引号前加 \），
    # 保证写进 Python 字符串字面量后还能原样还原
    escaped = api_key.strip().replace("\\", "\\\\").replace('"', '\\"')
    match = _match_key(text)
    if match:
        # 用 lambda 替换：re.sub 的字符串替换会对反斜杠二次解释，lambda 不会
        new_text = re.sub(
            r'API_KEY\s*=\s*["\'](?:[^"\'\\]|\\.)*["\']',
            lambda _m: f'API_KEY = "{escaped}"', text, count=1,
        )
    else:
        # 脚本没有 API_KEY 行（异常脚本）：在文件末尾追加
        new_text = text.rstrip() + f'\nAPI_KEY = "{escaped}"\n'

    try:
        path.write_text(new_text, encoding="utf-8")
    except OSError as exc:
        logger.error("无法写入脚本 %s：%s", path, exc)
        return False
    logger.info("API KEY 已写入 %s（%d 字符）", path.name, len(api_key))
    return True


def clear_key(script_path: str | Path) -> bool:
    """清空脚本内的 API_KEY（等价于注入空串）。"""
    return inject_key(script_path, "")
