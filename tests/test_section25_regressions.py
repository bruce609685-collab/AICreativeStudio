"""§25 回归钉子：pip 依赖占位词清洗 + 内嵌库文案纠偏（计入 v0.5）。

背景：v0.5 打包后用户发现「关于 → 安装依赖项」里出现一行 “none”。
根因是某脚本把 pip_requires 写成 none 表示“无依赖”，解析层原样保留，
界面遂把它当成真实包名列出，还带可点击的安装按钮（pip install none）。
本文件把三层防御（源头 / 契约层 / 兜底层）与文案纠偏钉住。
"""
from __future__ import annotations

from pathlib import Path

from contract.fields import normalize_pip_requires, parse_meta_block
from core.deps import install_pip, list_missing

ROOT = Path(__file__).resolve().parent.parent
NL = chr(10)


def test_normalize_drops_placeholders():
    assert normalize_pip_requires(["none", "null", "无", "-", "n/a", ""]) == []


def test_normalize_keeps_valid_keeps_order_and_lowercases():
    got = normalize_pip_requires(["Pillow", "none", "requests", "my-pkg"])
    assert got == ["pillow", "requests", "my-pkg"]


def test_normalize_drops_invalid_names():
    assert normalize_pip_requires(["bad name", "a/b", "x y z"]) == []


def test_meta_pip_requires_none_is_cleaned_at_contract_layer():
    text = NL.join([
        "# [ACS_META_START]",
        "# category=video",
        "# function=t2v",
        "# pip_requires=none",
        "# [ACS_META_END]",
    ]) + NL
    assert parse_meta_block(text).get("pip_requires") == []


def test_list_missing_never_returns_placeholder():
    assert list_missing(["none", "null", "无", "-"]) == []


def test_install_pip_refuses_invalid_package():
    assert install_pip("none") is False
    assert install_pip("") is False


def test_shipped_scripts_clean_after_parse():
    bad = []
    for f in (ROOT / "scripts").rglob("*.py"):
        meta = parse_meta_block(f.read_text(encoding="utf-8"))
        for pkg in meta.get("pip_requires", []):
            if pkg in ("none", "null", "无") or pkg != pkg.strip().lower():
                bad.append((f.name, pkg))
    assert bad == []


def test_about_page_has_no_false_embedded_lib_claim():
    text = (ROOT / "ui" / "pages" / "about_page.py").read_text(encoding="utf-8")
    assert "已随程序提供（内嵌）" not in text
    assert "requests / httpx / Pillow" not in text
