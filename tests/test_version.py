"""contract/version.py 契约版本校验单元测试（§5.4）。

覆盖语义化版本解析与三态结论（ok/older/newer）的全部边界：
v 前缀、缺段补零、空串兜底、带后缀宽容处理、逐段比大小。
"""

import pytest

from contract.version import check_template_version, parse_version


class TestParseVersion:
    """parse_version：版本字符串 → (主, 次, 修订) 整数三元组。"""

    def test_plain(self):
        assert parse_version("1.0.0") == (1, 0, 0)

    def test_v_prefix(self):
        assert parse_version("v1.2.3") == (1, 2, 3)
        assert parse_version("V2.0.1") == (2, 0, 1)

    def test_missing_segments_padded(self):
        assert parse_version("1.2") == (1, 2, 0)
        assert parse_version("2") == (2, 0, 0)

    def test_suffix_segment_tolerated(self):
        # "0-beta" 段取前导数字 → 0；超三段截断
        assert parse_version("1.0.0-beta") == (1, 0, 0)
        assert parse_version("1.2.3.4") == (1, 2, 3)

    def test_garbage_is_zero(self):
        assert parse_version("") == (0, 0, 0)
        assert parse_version("abc") == (0, 0, 0)


class TestCheckTemplateVersion:
    """check_template_version：三态兼容结论。"""

    def test_equal_is_ok(self):
        assert check_template_version("1.0.0", "1.0.0") == "ok"

    def test_older_script(self):
        assert check_template_version("0.9.0", "1.0.0") == "older"
        assert check_template_version("0.0.9", "1.0.0") == "older"

    def test_newer_script(self):
        assert check_template_version("1.0.1", "1.0.0") == "newer"
        assert check_template_version("2.0.0-beta", "1.0.0") == "newer"

    def test_v_prefix_equivalent(self):
        assert check_template_version("v1.0.0", "1.0.0") == "ok"

    def test_empty_uses_shell_version(self):
        # 空串按"与外壳同版本"处理（meta_parser 已兜底，这里再验一层）
        assert check_template_version("", "1.0.0") == "ok"

    def test_semantic_ordering(self):
        # 主版本 > 次版本 > 修订号 的比较次序
        assert check_template_version("1.1.0", "1.0.9") == "newer"
        assert check_template_version("1.0.9", "1.1.0") == "older"


class TestScriptMetaVersionCompat:
    """meta_parser → ScriptMeta.version_compat 链路（集成冒烟）。"""

    def test_meta_default_compat_ok(self, tmp_path):
        from core.registry.meta_parser import build_script_meta

        script = tmp_path / "demo.py"
        script.write_text(
            "# [ACS_META_START]\n"
            "# display_name = 测试脚本\n"
            "# category = image\n"
            "# [ACS_META_END]\n",
            encoding="utf-8",
        )
        meta = build_script_meta(script, tmp_path)
        # 未声明 template_version → 默认当前版本 → 结论 ok
        assert meta.version_compat == "ok"
        assert meta.template_version == "1.0.0"

    def test_meta_older_script_flagged(self, tmp_path):
        from core.registry.meta_parser import build_script_meta

        script = tmp_path / "old.py"
        script.write_text(
            "# [ACS_META_START]\n"
            "# display_name = 老脚本\n"
            "# category = image\n"
            "# template_version = 0.9.0\n"
            "# [ACS_META_END]\n",
            encoding="utf-8",
        )
        meta = build_script_meta(script, tmp_path)
        assert meta.version_compat == "older"
