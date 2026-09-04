"""KEY 注入/读取/清空单测：临时脚本文件上的真落盘验证。

测试目的：验证 API KEY 的"写 → 读 → 清 → 检测"闭环——
  - test_inject_and_read：注入后读回一致，且只替换 API_KEY 行；
  - test_clear_key：清空后读回为空；
  - test_inject_escapes_special_chars：KEY 含引号/反斜杠时正确转义；
  - test_inject_append_when_missing_line：脚本没有 API_KEY 行时追加；
  - test_detect_status_follows_inject：detect_key_status 随注入/清空
    变化，环境变量可作为兜底来源。

全部在 tempfile 临时目录中操作真实文件，不碰项目脚本。

运行：python -m tests.test_keys
"""

import os
import sys
import tempfile
from pathlib import Path

from core.keys import clear_key, detect_key_status, inject_key, read_key
from domain.models import ScriptMeta

# 样例脚本：带 META 块（key_env=TEST_API_KEY）+ 空 API_KEY 行
SAMPLE = (
    '# 模板版本：1.0.0\n'
    '# [ACS_META_START]\n'
    '# display_name = 测试脚本\n'
    '# category     = image\n'
    '# key_env      = TEST_API_KEY\n'
    '# [ACS_META_END]\n\n'
    'API_KEY = ""\n'
)


def _write_tmp(text: str) -> Path:
    """把样例文本写入临时目录并返回路径。

    参数：text: 脚本文本。
    返回：临时文件路径。
    """
    with tempfile.TemporaryDirectory() as tmp:
        pass  # 仅确认可用
    path = Path(tempfile.mkdtemp()) / "sample.py"
    path.write_text(text, encoding="utf-8")
    return path


def test_inject_and_read() -> None:
    """注入 → 读回一致；且只有 API_KEY 行被替换，META 注释不受影响。"""
    path = _write_tmp(SAMPLE)
    assert read_key(path) == ""
    assert inject_key(path, "sk-test-123")
    assert read_key(path) == "sk-test-123"
    # 只有 API_KEY 行被替换，其余代码不变
    text = path.read_text(encoding="utf-8")
    assert "display_name = 测试脚本" in text
    assert 'API_KEY = "sk-test-123"' in text
    path.unlink()


def test_clear_key() -> None:
    """清空 KEY：clear_key 后 read_key 返回空串。"""
    path = _write_tmp(SAMPLE)
    inject_key(path, "sk-secret")
    assert read_key(path) == "sk-secret"
    assert clear_key(path)
    assert read_key(path) == ""
    path.unlink()


def test_inject_escapes_special_chars() -> None:
    """KEY 含引号/反斜杠时注入必须转义，保证脚本语法不破。"""
    path = _write_tmp(SAMPLE)
    assert inject_key(path, 'sk-"quoted"\\path')
    text = path.read_text(encoding="utf-8")
    assert 'API_KEY = "sk-\\"quoted\\"\\\\path"' in text
    # read_key 返回脚本行内的字面内容（含转义序列）
    assert read_key(path) == 'sk-\\"quoted\\"\\\\path'
    path.unlink()


def test_inject_append_when_missing_line() -> None:
    """脚本没有 API_KEY 行时，注入会追加一行 API_KEY 赋值。"""
    path = _write_tmp('# 只有注释，没有 API_KEY 行\nprint("hi")\n')
    assert inject_key(path, "sk-appended")
    text = path.read_text(encoding="utf-8")
    assert 'API_KEY = "sk-appended"' in text
    path.unlink()


def test_detect_status_follows_inject() -> None:
    """detect_key_status 随注入/清空变化；环境变量可作兜底 KEY 来源。"""
    path = _write_tmp(SAMPLE)
    meta = ScriptMeta(display_name="测试", file_path=path.name, key_required=True,
                      key_env="TEST_API_KEY")
    os.environ.pop("TEST_API_KEY", None)
    # 未注入且无环境变量 → missing
    assert detect_key_status(path, meta) == "missing"
    # 注入后 → ok；清空后回到 missing
    inject_key(path, "sk-abc")
    assert detect_key_status(path, meta) == "ok"
    clear_key(path)
    assert detect_key_status(path, meta) == "missing"
    # 环境变量兜底：脚本内无 KEY 但环境变量有 → ok
    os.environ["TEST_API_KEY"] = "env-key"
    assert detect_key_status(path, meta) == "ok"
    os.environ.pop("TEST_API_KEY", None)
    path.unlink()


if __name__ == "__main__":
    test_inject_and_read()
    test_clear_key()
    test_inject_escapes_special_chars()
    test_inject_append_when_missing_line()
    test_detect_status_follows_inject()
    print("keys test passed")
    sys.exit(0)
