"""Grok · 文生图（grok-3-image）——制式脚本样例。

模板版本：1.0.0
依赖：无（纯 Python 标准库，零额外安装）

契约要点：
- 由外壳以 --params <job.json> 传参（键名见《脚本契约规范》§2）
- 结束时向 stdout 打印一行结果 JSON（ok / error）
- mock=true 时不发起网络请求，产出渐变占位 PNG（演示/测试/截图用）
- KEY 优先级：脚本内 API_KEY 常量 → 环境变量 XAI_API_KEY

# [ACS_META_START]
# display_name  = Grok · 文生图（grok-3-image）
# category      = image
# function      = t2i
# stream        = false
# web_search    = false
# seed          = false
# resolutions   = 1k,2k
# ratios        = 1:1,16:9,4:3,3:4,9:16
# qualities     = standard
# formats       = png,jpeg
# need_image    = false
# key_env       = XAI_API_KEY
# pip_requires  =
# [ACS_META_END]
"""

import argparse
import base64
import json
import os
import struct
import sys
import time
import urllib.error
import urllib.request
import zlib
from datetime import datetime
from pathlib import Path

API_KEY = ""  # 由模型设置「确定」写入；为空时回退环境变量 XAI_API_KEY

MODEL_ID = "grok-3-image"
API_URL = "https://api.x.ai/v1/images/generations"

MOCK_BASE_COLORS = [
    (30, 90, 200), (200, 60, 60), (40, 160, 90), (200, 150, 40),
    (120, 60, 190), (30, 160, 180), (220, 100, 150), (90, 140, 60), (160, 90, 50),
]
EXT_MAP = {"jpeg": "jpg", "jpg": "jpg", "png": "png", "webp": "webp"}


# ----------------------------------------------------------------------
# mock：纯标准库生成渐变 PNG（无 Pillow 依赖）
# ----------------------------------------------------------------------

def _png_chunk(tag: bytes, data: bytes) -> bytes:
    return (struct.pack(">I", len(data)) + tag + data
            + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF))


def make_gradient_png(path: Path, width: int, height: int, base: tuple[int, int, int]) -> None:
    """生成一张从 base 渐变到浅色（约 2:1 比例）的占位图。"""
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    raw = bytearray()
    for y in range(height):
        raw.append(0)  # filter: None
        t = y / max(1, height - 1)
        row = bytes((
            min(255, int(base[0] + (255 - base[0]) * t * 0.6)),
            min(255, int(base[1] + (255 - base[1]) * t * 0.6)),
            min(255, int(base[2] + (255 - base[2]) * t * 0.6)),
        ))
        raw.extend(row * width)
    png = (b"\x89PNG\r\n\x1a\n"
           + _png_chunk(b"IHDR", ihdr)
           + _png_chunk(b"IDAT", zlib.compress(bytes(raw), 9))
           + _png_chunk(b"IEND", b""))
    path.write_bytes(png)


# ----------------------------------------------------------------------
# 真实调用（xAI 同步接口）
# ----------------------------------------------------------------------

def _resolve_key() -> str:
    if API_KEY.strip():
        return API_KEY.strip()
    env_key = os.environ.get("XAI_API_KEY", "").strip()
    if env_key:
        return env_key
    return ""


def _call_grok(prompt: str, batch: int, ratio: str, resolution: str) -> dict:
    """POST images/generations，返回响应 JSON；非 200 抛异常带原文。"""
    body: dict = {
        "model": MODEL_ID,
        "prompt": prompt,
        "n": batch,
        "response_format": "b64_json",
        "aspect_ratio": ratio,
    }
    if resolution:  # 1k / 2k
        body["resolution"] = resolution

    req = urllib.request.Request(
        API_URL,
        data=json.dumps(body).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {_resolve_key()}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        detail = ""
        try:
            data = json.loads(raw)
            detail = str(data.get("error") or data)
        except json.JSONDecodeError:
            detail = raw[:300]
        raise RuntimeError(f"API_ERROR|HTTP {exc.code}|{detail}") from None
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise RuntimeError(f"NETWORK|{exc}") from None


# ----------------------------------------------------------------------
# 主流程
# ----------------------------------------------------------------------

def _ext_name(fmt: str) -> str:
    return EXT_MAP.get((fmt or "png").lower(), "png")


def main() -> int:
    parser = argparse.ArgumentParser(description="Grok 文生图制式脚本")
    parser.add_argument("--params", required=True, help="job.json 绝对路径")
    args = parser.parse_args()

    started = time.time()
    try:
        params = json.loads(Path(args.params).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        _emit({"status": "error", "code": "INVALID_PARAMS",
               "message": f"无法读取参数文件：{exc}"})
        return 1

    prompt = str(params.get("prompt", "")).strip()
    if not prompt:
        _emit({"status": "error", "code": "INVALID_PARAMS", "message": "prompt 不能为空"})
        return 1

    output_dir = Path(params.get("output_dir") or ".")
    batch = max(1, min(9, int(params.get("batch", 1) or 1)))
    ratio = str(params.get("ratio", "1:1"))
    resolution = str(params.get("resolution", "")).strip()
    fmt = _ext_name(str(params.get("format", "png")))
    mock = bool(params.get("mock", False))

    try:
        output_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        files: list[str] = []

        if mock:
            # ---- 演示模式：渐变占位图 ----
            width, height = 768, 768
            if ratio == "16:9":
                width, height = 1024, 576
            elif ratio == "9:16":
                width, height = 576, 1024
            elif ratio == "4:3":
                width, height = 896, 672
            elif ratio == "3:4":
                width, height = 672, 896
            for i in range(batch):
                path = output_dir / f"grok_mock_{stamp}_{i + 1:02d}.{fmt}"
                make_gradient_png(path, width, height, MOCK_BASE_COLORS[i % len(MOCK_BASE_COLORS)])
                files.append(str(path.resolve()))
        else:
            # ---- 真实模式 ----
            key = _resolve_key()
            if not key:
                _emit({"status": "error", "code": "AUTH_FAILED",
                       "message": "API KEY 未配置（脚本内 API_KEY 或环境变量 XAI_API_KEY）"})
                return 1
            data = _call_grok(prompt, batch, ratio, resolution)
            items = data.get("data") or []
            if not items:
                reason = data.get("block_reason", "")
                _emit({"status": "error", "code": "BLOCKED" if reason else "API_ERROR",
                       "message": f"未返回图片（block_reason={reason or '未知'}）"})
                return 1
            for i, item in enumerate(items):
                b64 = item.get("b64_json")
                if not b64:
                    continue
                mime = item.get("mime_type", "")
                ext = EXT_MAP.get(mime.split("/")[-1], fmt)
                path = output_dir / f"grok_{stamp}_{i + 1:02d}.{ext}"
                path.write_bytes(base64.b64decode(b64))
                files.append(str(path.resolve()))

        _emit({"status": "ok", "files": files,
               "elapsed": round(time.time() - started, 2)})
        return 0
    except RuntimeError as exc:  # 上游错误：NETWORK|xxx / API_ERROR|xxx
        code, _, message = str(exc).partition("|")
        _emit({"status": "error", "code": code, "message": message})
        return 1
    except Exception as exc:  # noqa: BLE001 —— 脚本兜底，向上游透传
        _emit({"status": "error", "code": "INTERNAL", "message": str(exc)})
        return 1


def _emit(result: dict) -> None:
    """结果 JSON 打印到 stdout（外壳只解析最后一行）。"""
    print(json.dumps(result, ensure_ascii=False))
    sys.stdout.flush()


if __name__ == "__main__":
    sys.exit(main())
