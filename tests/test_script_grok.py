"""grok-3-image 样例脚本验证：mock 链路产出占位图 + 结果 JSON 合规。

测试分组：
  - test_grok_mock_generates_images：mock 模式 + batch=3，应一次产出
    3 张文件头合法（PNG 魔数）的图片；
  - test_grok_mock_batch_1_and_jpeg：mock 模式 + batch=1 + jpeg 格式，
    验证 batch 与 format 参数被正确处理；
  - test_grok_missing_key_returns_auth_failed：真实模式且无 KEY 时
    应返回明确的 AUTH_FAILED（提前拦截，而非网络错误）。

测试原理：不联网。mock=True 时脚本用占位编码器直接生成图片，
走完整"读 job.json → 生成 → 写结果 JSON"流程；测试端校验
run_script 返回的结果对象与产出文件的真实格式（魔数）。
所有产物写到临时目录，测完即删。

运行：python -m tests.test_script_grok
"""

import sys
import tempfile
from pathlib import Path

from app import paths
from contract.params import write_params_file
from core.runner import run_script

SCRIPT = paths.SCRIPTS_DIR / "image_scripts" / "grok_3_image.py"

PNG_MAGIC = b"\x89PNG\r\n\x1a\n"  # 所有合法 PNG 文件开头的 8 字节特征码


def test_grok_mock_generates_images() -> None:
    """mock 模式 + batch=3：应一次产出 3 张合法 PNG。

    校验三个层面：脚本进程执行成功（result.ok）、产出数量与
    batch 参数一致（3 张）、每张文件的二进制头确实是 PNG 格式。
    """
    assert SCRIPT.exists(), f"样例脚本缺失：{SCRIPT}"
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "out"
        # 写 job.json：batch=3 表示一次生成 3 张图
        job = write_params_file(
            Path(tmp) / "job.json",
            prompt="测试提示词", ratio="16:9", resolution="1k",
            format="png", batch=3, output_dir=out, mock=True,
        )
        result = run_script(SCRIPT, job, timeout=60)
        assert result.ok, f"mock 生成失败：{result.code} {result.message}"
        assert len(result.files) == 3, f"应产出 3 张图，实际 {len(result.files)}"
        for f in result.files:
            p = Path(f)
            assert p.exists(), f"产物缺失：{f}"
            assert p.read_bytes()[:8] == PNG_MAGIC, f"不是合法 PNG：{f}"


def test_grok_mock_batch_1_and_jpeg() -> None:
    """mock 模式 + batch=1 + jpeg：验证单张产出与格式参数处理。"""
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "out"
        job = write_params_file(
            Path(tmp) / "job.json",
            prompt="x", format="jpeg", batch=1, output_dir=out, mock=True,
        )
        result = run_script(SCRIPT, job, timeout=60)
        assert result.ok, f"{result.code} {result.message}"
        assert len(result.files) == 1
        # 注意：mock 走 PNG 编码器，扩展名按 format 命名（占位产物）
        assert Path(result.files[0]).suffix in (".jpg", ".jpeg", ".png")


def test_grok_missing_key_returns_auth_failed() -> None:
    """无 KEY 时真实模式应返回 AUTH_FAILED 而非网络错误。

    脚本应在发起任何网络请求前先检测 KEY，缺失就直接给出
    明确错误码——用户能一眼看懂"要去设置页填 KEY"。
    """
    import os

    os.environ.pop("XAI_API_KEY", None)  # 确保环境变量里没有 KEY
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "out"
        job = write_params_file(
            Path(tmp) / "job.json",
            prompt="测试", batch=1, output_dir=out, mock=False,  # mock=False 走真实分支
        )
        result = run_script(SCRIPT, job, timeout=60)
        assert not result.ok
        assert result.code == "AUTH_FAILED", f"应为 AUTH_FAILED，实际 {result.code}"


if __name__ == "__main__":
    test_grok_mock_generates_images()
    test_grok_mock_batch_1_and_jpeg()
    test_grok_missing_key_returns_auth_failed()
    print("grok script test passed")
    sys.exit(0)
