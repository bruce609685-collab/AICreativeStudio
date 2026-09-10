"""小米 · 预置音色 TTS（mimo-v2.5-tts）——制式脚本样例。

模板版本：1.0.0
依赖：无（纯 Python 标准库，mock 用 wave 产真实 WAV）

契约要点：
- 同步调用（POST 直接返回音频），OpenAI 兼容接口
- mock=true 时不发起网络请求，用 wave 标准库产真实 WAV（正弦包络语音占位）
- KEY 优先级：脚本内 API_KEY 常量 → 环境变量 MIMO_API_KEY
- 超时：timeout 是"整个任务总预算"，由外壳下发；严禁给单次请求设
  远小于总预算的硬性上限（例如写死 timeout=30）
- 真实接口字段以小米 MiMo 开放平台官方文档为准（本脚本为 OpenAI 兼容骨架）

# [ACS_META_START]
# display_name  = 小米 MiMo · 预置音色 TTS
# category      = audio
# function      = tts
# stream        = false
# web_search    = false
# seed          = false
# voices        = 冰糖,茉莉,苏打,白桦
# formats       = wav,pcm16
# need_image    = false
# max_text_len  = 1000
# key_env       = MIMO_API_KEY
# pip_requires  =
# [ACS_META_END]
"""

import argparse
import base64
import json
import math
import os
import struct
import sys
import time
import urllib.error
import urllib.request
import wave
from datetime import datetime
from pathlib import Path

API_KEY = ""  # 由模型设置「确定」写入；为空时回退环境变量 MIMO_API_KEY

MODEL_ID = "mimo-v2.5-tts"
API_URL = "https://api.mimo.ai/v1/chat/completions"
MAX_TEXT_LEN = 1000
SAMPLE_RATE = 24000


# ----------------------------------------------------------------------
# mock：wave 标准库产真实 WAV（正弦包络占位语音）
# ----------------------------------------------------------------------

def make_mock_wav(path: Path, text: str) -> None:
    """按文本长度估计时长，生成带包络的合成语音占位 WAV。"""
    duration = max(1.0, min(30.0, len(text) * 0.18))
    n = int(SAMPLE_RATE * duration)
    frames = bytearray()
    for i in range(n):
        t = i / SAMPLE_RATE
        env = min(1.0, i / (SAMPLE_RATE * 0.06), (n - i) / (SAMPLE_RATE * 0.06))
        # 基频 180Hz + 二次谐波 + 缓慢颤音，形成"语音感"占位声
        v = (math.sin(2 * math.pi * 180 * t) * 0.40
             + math.sin(2 * math.pi * 360 * t) * 0.18
             + math.sin(2 * math.pi * 181.5 * t) * 0.10)
        frames += struct.pack("<h", int(v * env * 32767 * 0.45))
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SAMPLE_RATE)
        w.writeframes(bytes(frames))


# ----------------------------------------------------------------------
# 真实调用（OpenAI 兼容同步接口）
# ----------------------------------------------------------------------

def _resolve_key() -> str:
    if API_KEY.strip():
        return API_KEY.strip()
    return os.environ.get("MIMO_API_KEY", "").strip()


def _call_mimo(text: str, voice: str, format_: str, key: str,
               timeout: float) -> bytes:
    body = {
        "model": MODEL_ID,
        "messages": [
            {"role": "system", "content": "你是专业的语音合成助手，请朗读用户给出的文本。"},
            {"role": "assistant", "content": text},
        ],
        "audio": {"voice": voice or "default", "format": format_ or "wav"},
    }
    req = urllib.request.Request(
        API_URL,
        data=json.dumps(body).encode("utf-8"),
        headers={"Authorization": f"Bearer {key}",
                 "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"API_ERROR|HTTP {exc.code}|{raw[:300]}") from None
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise RuntimeError(f"NETWORK|{exc}") from None

    audio = (data.get("audio") or {}).get("data")
    if not audio:
        # 兼容直接返回 base64 的响应形态
        audio = data.get("data")
    if not audio:
        raise RuntimeError(f"API_ERROR|响应缺少音频数据：{str(data)[:300]}")
    return base64.b64decode(audio)


# ----------------------------------------------------------------------
# 主流程
# ----------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(description="小米 MiMo TTS 制式脚本")
    parser.add_argument("--params", required=True, help="job.json 绝对路径")
    args = parser.parse_args()

    started = time.time()
    try:
        params = json.loads(Path(args.params).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        _emit({"status": "error", "code": "INVALID_PARAMS",
               "message": f"无法读取参数文件：{exc}"})
        return 1

    text = str(params.get("prompt", "")).strip()
    if not text:
        _emit({"status": "error", "code": "INVALID_PARAMS", "message": "prompt 不能为空"})
        return 1
    if len(text) > MAX_TEXT_LEN:
        _emit({"status": "error", "code": "INVALID_PARAMS",
               "message": f"文本超过上限 {MAX_TEXT_LEN} 字"})
        return 1

    output_dir = Path(params.get("output_dir") or ".")
    voice = str(params.get("voice", "")).strip()
    format_ = str(params.get("format", "wav")).strip().lower() or "wav"
    mock = bool(params.get("mock", False))

    # 请求超时：由外壳按任务总预算下发，缺省 300 秒
    timeout = 300.0
    try:
        if params.get("timeout") not in (None, ""):
            timeout = float(params.get("timeout"))
    except (TypeError, ValueError):
        timeout = 300.0
    if timeout <= 0:
        timeout = 300.0

    try:
        output_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        ext = "wav" if format_ == "pcm16" else format_

        if mock:
            path = output_dir / f"mimo_mock_{stamp}.wav"
            make_mock_wav(path, text)
            files = [str(path.resolve())]
        else:
            key = _resolve_key()
            if not key:
                _emit({"status": "error", "code": "AUTH_FAILED",
                       "message": "API KEY 未配置（脚本内 API_KEY 或环境变量 MIMO_API_KEY）"})
                return 1
            audio_bytes = _call_mimo(text, voice, format_, key, timeout)
            path = output_dir / f"mimo_{stamp}.{ext}"
            path.write_bytes(audio_bytes)
            files = [str(path.resolve())]

        _emit({"status": "ok", "files": files,
               "elapsed": round(time.time() - started, 2)})
        return 0
    except RuntimeError as exc:
        code, _, message = str(exc).partition("|")
        _emit({"status": "error", "code": code, "message": message})
        return 1
    except Exception as exc:  # noqa: BLE001 —— 脚本兜底
        _emit({"status": "error", "code": "INTERNAL", "message": str(exc)})
        return 1


def _emit(result: dict) -> None:
    print(json.dumps(result, ensure_ascii=False))
    sys.stdout.flush()


if __name__ == "__main__":
    sys.exit(main())
