"""§26 回归钉子：超时链路治本（脚本预算共享 + 模板防短上限），计入 v0.5.1。

背景：v0.5 用户反馈「生成视频 → ✕ NETWORK：request timed out」。
根因不是网络，而是视频脚本把"提交请求"的超时写成 min(30, timeout) 死限，
而接口单次响应需 30~48 秒——连接建好、服务端没在 30 秒内回，就被判超时。

治本分三层：
1. 脚本层：timeout 是"整个任务总预算"（提交+轮询+下载共享同一份 deadline），
   各阶段只在剩余预算内取值，不再给单次请求设远小于总预算的硬上限；
2. 参数层 / 外壳层：视频预算 600 秒、外壳强杀 660 秒，层层留余量；
3. 模板层：LLM 生成新脚本时，模板必须明确"禁止短上限"，否则源源不断
   生出同样有病的脚本。

本文件把这三层一起钉住，并扫描全脚本确认没有漏网的硬编码数字超时。
"""
from __future__ import annotations

import inspect
import re
from pathlib import Path

from core.runner.params import (
    build_audio_params,
    build_image_params,
    build_video_params,
)

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"
TEMPLATES = ROOT / "templates"

# urlopen(...) 里直接写死数字超时（如 timeout=30）即为病态写法
_NUMERIC_TIMEOUT = re.compile(r"urlopen\([^)]*timeout\s*=\s*[0-9]", re.S)


def _read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


# ----------------------------------------------------------------------
# 第 1 层：脚本不再有硬编码数字超时，视频脚本用 deadline 预算共享
# ----------------------------------------------------------------------

def test_no_script_hardcodes_numeric_urlopen_timeout():
    """全脚本扫描：不得出现 urlopen(..., timeout=<数字>) 的硬编码写法。"""
    bad = []
    for f in SCRIPTS.rglob("*.py"):
        if _NUMERIC_TIMEOUT.search(f.read_text(encoding="utf-8")):
            bad.append(f.relative_to(ROOT).as_posix())
    assert bad == [], f"仍有硬编码短超时的脚本：{bad}"


def test_video_scripts_share_deadline_budget():
    """两个视频脚本都必须用 deadline 把提交/轮询/下载绑到同一份预算上。"""
    for rel in (
        "scripts/video_scripts/dmxapi_wan2_6_t2v_py.py",
        "scripts/video_scripts/wan2_6_t2v_py.py",
    ):
        assert "deadline" in _read(rel), f"{rel} 缺少 deadline 预算共享"


def test_video_scripts_default_budget_is_six_hundred():
    assert "DEFAULT_TIMEOUT = 600.0" in _read("scripts/video_scripts/minimax_h3_video.py")
    assert re.search(r"timeout\s*=\s*600\b", _read("scripts/video_scripts/wan2_6_t2v_py.py"))


def test_all_scripts_read_params_timeout():
    """minimax / grok / mimo 都必须从参数字典读取 timeout，不能自定了事。"""
    for rel in (
        "scripts/video_scripts/minimax_h3_video.py",
        "scripts/image_scripts/grok_3_image.py",
        "scripts/audio_scripts/mimo_tts.py",
    ):
        assert 'params.get("timeout")' in _read(rel), f"{rel} 未读取 params timeout"


def test_image_audio_scripts_still_use_budget_variable():
    """图像/语音脚本的 urlopen 必须用变量 timeout，而非数字。"""
    for rel in (
        "scripts/image_scripts/grok_3_image.py",
        "scripts/audio_scripts/mimo_tts.py",
    ):
        assert "urlopen(req, timeout=timeout)" in _read(rel), f"{rel} 未使用预算变量"


# ----------------------------------------------------------------------
# 第 2 层：参数层与外壳层的默认预算层层对齐
# ----------------------------------------------------------------------

def _default(func, name: str):
    return inspect.signature(func).parameters[name].default


def test_params_layer_defaults():
    assert _default(build_image_params, "timeout") == 300
    assert _default(build_audio_params, "timeout") == 300
    assert _default(build_video_params, "timeout") == 600


def test_shell_kill_timeout_exceeds_script_budget():
    """外壳强杀上限必须大于脚本预算，留出收尾余量。"""
    from ui.workers import GenerateWorker

    shell_default = _default(GenerateWorker.__init__, "timeout")
    assert shell_default > 300, "外壳默认超时必须大于图像/语音预算 300"

    video_page = _read("ui/pages/video_page.py")
    m = re.search(r"timeout\s*=\s*([0-9.]+)\s*,", video_page)
    assert m, "视频页未显式下发超时"
    assert float(m.group(1)) > 600, "视频页强杀上限必须大于视频预算 600"


# ----------------------------------------------------------------------
# 第 3 层：模板必须给出"总预算 + 禁止短上限"的强规则（防未来脚本再犯）
# ----------------------------------------------------------------------

def test_templates_state_total_budget_and_ban_short_cap():
    tpls = sorted(TEMPLATES.glob("prompt_*.txt"))
    assert tpls, "未找到脚本生成模板"
    for t in tpls:
        text = t.read_text(encoding="utf-8")
        assert "总预算" in text, f"{t.name} 未说明 timeout 是任务总预算"
        assert "严禁" in text, f"{t.name} 缺少禁止短上限的强规则"
        assert "min(" in text, f"{t.name} 未举例点明 min(x, timeout) 这类反模式"
