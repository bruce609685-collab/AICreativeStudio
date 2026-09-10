"""§23 回归钉子：二次梳理修复的底层 BUG 不再复发。

每个测试对应问题收集 §23 的一条编号，命名即编号，出问题一眼定位。
"""

import json
import sys
import tempfile
import threading
from pathlib import Path

from core import deps
from core.importer import config as llmcfg
from core.importer.pipeline import _inject_default_caps, _sanitize_filename
from infra.persistence import HistoryDatabase


def test_b1_sanitize_filename_no_double_py() -> None:
    """LLM 给的名字自带 .py 时不能洗成 xxx_py.py。"""
    assert _sanitize_filename("demo_mock_t2i.py") == "demo_mock_t2i.py"
    assert _sanitize_filename("Grok 3 Image.PY") == "grok_3_image.py"
    assert _sanitize_filename("   ") == "imported_script.py"


def test_b2_b3_inject_caps_keeps_chinese_name_and_outer_comments() -> None:
    """中文 display_name 与 META 块外注释都不能被当垃圾删掉；真垃圾仍替换。"""
    code = (
        '"""\n# [ACS_META_START]\n'
        "# display_name = 演示 · 文生图\n"
        "# category = image\n"
        "# resolutions = 720p-1080p高清\n"
        "# formats = png\n"
        '# [ACS_META_END]\n"""\n'
        "# 默认超时 = 30秒，可改\nTIMEOUT = 30\n"
    )
    out = _inject_default_caps(code, "image")
    assert "# display_name = 演示 · 文生图" in out
    assert "# 默认超时 = 30秒，可改" in out
    assert "720p-1080p高清" not in out
    assert "resolutions   = 1k,2k" in out
    assert out.count("formats") == 1


def test_b4_load_llm_config_ignores_unknown_keys() -> None:
    """config.json 多写字段不能让启动崩溃。"""
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "config.json"
        p.write_text(json.dumps({"llm": {"api_url": "u", "api_key": "k",
                                    "model": "m", "mock": True,
                                    "temperature": 0.2}}), encoding="utf-8")
        cfg = llmcfg.load_llm_config(p)
        assert cfg.api_url == "u" and cfg.mock is True
        p.write_text(json.dumps({"llm": "not-a-dict"}), encoding="utf-8")
        assert llmcfg.load_llm_config(p).api_url == llmcfg.LLMConfig().api_url


def test_b8_history_db_cross_thread_writes() -> None:
    """QThread 回调写历史库：并发写不抛 ProgrammingError、不丢记录。"""
    with tempfile.TemporaryDirectory() as d:
        db = HistoryDatabase(Path(d) / "h.db")
        errors: list[str] = []

        def worker(i: int) -> None:
            try:
                db.add_record(category="image", script_key=f"k{i}", prompt="p")
            except Exception as exc:  # noqa: BLE001
                errors.append(repr(exc))

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(16)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert errors == []
        assert db.count() == 16
        db.close()


def test_b9_resolve_python_dev_and_frozen() -> None:
    """dev 态用当前解释器；frozen 态不能再返回主程序 exe。"""
    assert deps._resolve_python() == sys.executable
    sys.frozen = True  # type: ignore[attr-defined]
    try:
        got = deps._resolve_python()
    finally:
        del sys.frozen  # type: ignore[attr-defined]
    assert got != sys.executable
