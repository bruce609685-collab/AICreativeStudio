"""视频/语音样例脚本验证：mock 链路产出真实可读产物 + 结果 JSON 合规。

测试分组：
  - test_video_mock_generates_gif：视频脚本 mock 模式应产出一张
    文件头合法（GIF8 魔数）、体积够大的 GIF；
  - test_video_mock_missing_key_auth_failed：真实模式且无 KEY 时
    应返回明确的 AUTH_FAILED（而不是模糊的网络错误）；
  - test_audio_mock_generates_wav：语音脚本 mock 模式应产出单声道、
    24000Hz、时长足够的合法 WAV（用标准库 wave 模块校验）；
  - test_audio_mock_over_length_rejected：语音超长（>1000 字）时
    应被参数校验拦下，返回 INVALID_PARAMS。

测试原理：不联网。用 write_params_file 写一份 job.json（mock=True
走占位产物分支），再用 run_script 真实执行脚本进程，最后校验
退出结果 JSON 和产出文件的"文件头魔数"（文件开头几个特征字节）。
所有产物都写到临时目录，测完即删。

运行：python -m tests.test_script_av
"""

import os
import sys
import tempfile
import wave
from pathlib import Path

from app import paths
from contract.params import write_params_file
from core.runner import run_script

VIDEO_SCRIPT = paths.SCRIPTS_DIR / "video_scripts" / "minimax_h3_video.py"
AUDIO_SCRIPT = paths.SCRIPTS_DIR / "audio_scripts" / "mimo_tts.py"

GIF_MAGIC = b"GIF8"   # 所有合法 GIF 文件开头都是这 4 个字节
WAV_MAGIC = b"RIFF"   # 所有合法 WAV 文件开头都是这 4 个字节


def test_video_mock_generates_gif() -> None:
    """mock 模式的视频脚本应产出一张合法且足够大的 GIF。

    "魔数"（magic number）是文件开头几个字节的特征码，用来
    识别文件真实格式——比只看扩展名可靠得多。GIF 的魔数是 GIF8。
    """
    assert VIDEO_SCRIPT.exists(), f"视频脚本缺失：{VIDEO_SCRIPT}"
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "out"
        # 写 job.json：mock=True 让脚本走占位产物分支，不调真 API
        job = write_params_file(
            Path(tmp) / "job.json",
            prompt="测试视频", ratio="16:9", resolution="720p",
            duration=5, mode="std", output_dir=out, mock=True,
        )
        result = run_script(VIDEO_SCRIPT, job, timeout=60)
        assert result.ok, f"mock 失败：{result.code} {result.message}"
        assert len(result.files) == 1  # 单次生成 1 个视频
        p = Path(result.files[0])
        assert p.exists()
        assert p.read_bytes()[:4] == GIF_MAGIC, f"不是合法 GIF：{p}"
        assert p.stat().st_size > 1000, "GIF 太小，疑似生成失败"


def test_video_mock_missing_key_auth_failed() -> None:
    """真实模式 + 无 KEY：脚本应先查 KEY，返回 AUTH_FAILED。

    这是"提前拦截"测试——脚本不该等真正调 API 撞了 401 才报错，
    而是在启动时检测到没有 KEY 就直接给出明确的错误码。
    """
    os.environ.pop("MINIMAX_API_KEY", None)  # 确保环境变量里没有 KEY
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "out"
        job = write_params_file(Path(tmp) / "job.json", prompt="x",
                                output_dir=out, mock=False)  # mock=False 走真实分支
        result = run_script(VIDEO_SCRIPT, job, timeout=60)
        assert not result.ok and result.code == "AUTH_FAILED"


def test_audio_mock_generates_wav() -> None:
    """mock 模式的语音脚本应产出单声道 24000Hz 的合法 WAV。

    这里除了魔数检查，还用标准库 wave 模块真正打开文件，
    读取声道数 / 采样率 / 总帧数——比只看文件头更严格。
    """
    assert AUDIO_SCRIPT.exists(), f"语音脚本缺失：{AUDIO_SCRIPT}"
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "out"
        job = write_params_file(
            Path(tmp) / "job.json", prompt="你好，测试语音",
            voice="冰糖", format="wav", output_dir=out, mock=True,
        )
        result = run_script(AUDIO_SCRIPT, job, timeout=60)
        assert result.ok, f"mock 失败：{result.code} {result.message}"
        assert len(result.files) == 1
        p = Path(result.files[0])
        assert p.exists()
        assert p.read_bytes()[:4] == WAV_MAGIC, f"不是合法 WAV：{p}"
        with wave.open(str(p), "rb") as w:
            assert w.getnchannels() == 1     # 单声道
            assert w.getframerate() == 24000  # 采样率 24kHz（TTS 标准规格）
            assert w.getnframes() > 1000, "WAV 太短，疑似生成失败"


def test_audio_mock_over_length_rejected() -> None:
    """语音文本超长（>1000 字）应在参数校验阶段被拒绝。

    TTS 服务对单次合成的文本长度有上限，脚本在校验参数时就
    应拦下超长输入，返回 INVALID_PARAMS，而不是白白发起请求。
    """
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "out"
        job = write_params_file(Path(tmp) / "job.json",
                                prompt="字" * 1001, output_dir=out, mock=True)
        result = run_script(AUDIO_SCRIPT, job, timeout=60)
        assert not result.ok and result.code == "INVALID_PARAMS"


if __name__ == "__main__":
    test_video_mock_generates_gif()
    test_video_mock_missing_key_auth_failed()
    test_audio_mock_generates_wav()
    test_audio_mock_over_length_rejected()
    print("av script test passed")
    sys.exit(0)
