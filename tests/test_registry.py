"""注册表单测：ACS_META 解析 + 扫描跳过坏脚本 + 分类索引。

测试目的：验证"脚本 → 注册表"这条链路——
  - test_parse_meta_block：合法 ACS_META 注释块被正确解析成字段；
  - test_parse_meta_missing_marker / test_parse_meta_bad_category：
    无标记块、非法类别应抛 MetaParseError；
  - test_scan_skips_bad_scripts：扫描目录时坏脚本被跳过不注册；
  - test_registry_by_category：注册表按类别索引/按 key 查询正确；
  - test_real_scripts_dir：真实 scripts/ 目录里 grok 样例脚本已注册。

运行：python -m tests.test_registry
"""

import sys
import tempfile
from pathlib import Path

from contract.fields import MetaParseError, parse_meta_block
from core.registry.scanner import scan_scripts_dir
from core.registry.script_registry import ScriptRegistry
from domain.enums import MediaCategory

# 三份样例脚本源码：合法 / 无 META 块 / 非法类别
GOOD_SCRIPT = '''# [ACS_META_START]
# display_name = 测试脚本
# category     = image
# function     = t2i
# resolutions  = 1k,2k
# ratios       = 1:1,16:9
# qualities    = standard
# formats      = png
# seed         = false
# key_env      = TEST_KEY
# [ACS_META_END]

API_KEY = ""
'''

NO_META_SCRIPT = 'print("no meta")\n'

BAD_CATEGORY = '''# [ACS_META_START]
# category = flying
# [ACS_META_END]
'''


def test_parse_meta_block() -> None:
    """合法脚本：ACS_META 块各字段解析正确（列表/布尔/字符串）。"""
    meta = parse_meta_block(GOOD_SCRIPT)
    assert meta["category"] == "image"
    assert meta["function"] == "t2i"
    assert meta["resolutions"] == ["1k", "2k"]
    assert meta["formats"] == ["png"]
    assert meta["seed"] is False
    assert meta["key_env"] == "TEST_KEY"


def test_parse_meta_missing_marker() -> None:
    """无 [ACS_META_START] 标记的脚本应抛 MetaParseError。"""
    try:
        parse_meta_block(NO_META_SCRIPT)
        raise AssertionError("应当抛 MetaParseError")
    except MetaParseError:
        pass


def test_parse_meta_bad_category() -> None:
    """类别值不在 MediaCategory 枚举内应抛 MetaParseError。"""
    try:
        parse_meta_block(BAD_CATEGORY)
        raise AssertionError("应当抛 MetaParseError")
    except MetaParseError:
        pass


def test_scan_skips_bad_scripts() -> None:
    """扫描目录：坏脚本（无 META/非法类别/__init__）被跳过，只注册合法脚本。"""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp) / "scripts"
        (root / "image_scripts").mkdir(parents=True)
        (root / "image_scripts" / "good.py").write_text(GOOD_SCRIPT, encoding="utf-8")
        (root / "image_scripts" / "no_meta.py").write_text(NO_META_SCRIPT, encoding="utf-8")
        (root / "image_scripts" / "bad_cat.py").write_text(BAD_CATEGORY, encoding="utf-8")
        (root / "image_scripts" / "__init__.py").write_text("", encoding="utf-8")

        metas = scan_scripts_dir(root)
        assert len(metas) == 1, f"坏脚本应被跳过，实际注册 {len(metas)} 个"
        assert metas[0].display_name == "测试脚本"
        assert metas[0].file_path == "image_scripts/good.py"


def test_registry_by_category() -> None:
    """注册表：按类别索引正确，按 key 查询存在/不存在返回正确结果。"""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp) / "scripts"
        (root / "image_scripts").mkdir(parents=True)
        (root / "image_scripts" / "a.py").write_text(GOOD_SCRIPT, encoding="utf-8")

        audio = GOOD_SCRIPT.replace("category     = image", "category     = audio")
        (root / "audio_scripts").mkdir(parents=True)
        (root / "audio_scripts" / "b.py").write_text(audio, encoding="utf-8")

        reg = ScriptRegistry()
        reg.load(scan_scripts_dir(root))
        assert reg.count() == 2
        assert len(reg.by_category(MediaCategory.IMAGE)) == 1
        assert len(reg.by_category(MediaCategory.VIDEO)) == 0
        assert reg.get("image_scripts/a.py") is not None
        assert reg.get("nope.py") is None


def test_real_scripts_dir() -> None:
    """真实 scripts/ 目录至少注册 grok 样例脚本（M2 验收前置）。"""
    from app import paths

    metas = scan_scripts_dir(paths.SCRIPTS_DIR)
    keys = {m.file_path for m in metas}
    assert "image_scripts/grok_3_image.py" in keys, "grok 样例脚本未注册"
    assert any(m.category is MediaCategory.IMAGE for m in metas)


if __name__ == "__main__":
    test_parse_meta_block()
    test_parse_meta_missing_marker()
    test_parse_meta_bad_category()
    test_scan_skips_bad_scripts()
    test_registry_by_category()
    test_real_scripts_dir()
    print("registry test passed")
    sys.exit(0)
