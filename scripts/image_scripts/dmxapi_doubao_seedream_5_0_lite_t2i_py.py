#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# [ACS_META_START]
# category       = image
# function       = t2i
# key_env        = DMXAPI_API_KEY
# resolutions    = 2K,3K,4K
# ratios         = 1:1,4:3,3:4,16:9,9:16,3:2,2:3,21:9
# qualities      = standard
# formats        = png,jpeg
# need_image     = false
# seed           = false
# stream         = true
# web_search     = true
# pip_requires   = 
# [ACS_META_END]

import argparse
import json
import os
import random
import re
import struct
import sys
import time
import urllib.error
import urllib.request
import zlib

API_KEY = ""  # 安全：不内置密钥，运行时从环境变量 DMXAPI_API_KEY 或模型设置写入
API_URL = "https://www.dmxapi.cn/v1/responses"
MODEL = "doubao-seedream-5.0-lite"
KEY_ENV = "DMXAPI_API_KEY"

PIXELS = {
    "2K": {
        "1:1": (2048, 2048),
        "4:3": (2304, 1728),
        "3:4": (1728, 2304),
        "16:9": (2848, 1600),
        "9:16": (1600, 2848),
        "3:2": (2496, 1664),
        "2:3": (1664, 2496),
        "21:9": (3136, 1344),
    },
    "3K": {
        "1:1": (3072, 3072),
        "4:3": (3456, 2592),
        "3:4": (2592, 3456),
        "16:9": (4096, 2304),
        "9:16": (2304, 4096),
        "3:2": (3744, 2496),
        "2:3": (2496, 3744),
        "21:9": (4704, 2016),
    },
    "4K": {
        "1:1": (4096, 4096),
        "4:3": (4704, 3520),
        "3:4": (3520, 4704),
        "16:9": (5504, 3040),
        "9:16": (3040, 5504),
        "3:2": (4992, 3328),
        "2:3": (3328, 4992),
        "21:9": (6240, 2656),
    },
}

class ScriptError(Exception):
    code = "INTERNAL"

class AuthError(ScriptError):
    code = "AUTH_FAILED"

class APIError(ScriptError):
    code = "API_ERROR"

class NetworkError(ScriptError):
    code = "NETWORK"

class BlockedError(ScriptError):
    code = "BLOCKED"

class InvalidParams(ScriptError):
    code = "INVALID_PARAMS"


def fail(code, msg):
    print(json.dumps({"status": "error", "code": code, "message": msg}, ensure_ascii=False))
    sys.exit(0)


def get_pixel_size(resolution, ratio):
    res = str(resolution or "").strip().upper()
    rat = str(ratio or "").strip()
    if res in PIXELS and rat in PIXELS[res]:
        return "{0}x{1}".format(*PIXELS[res][rat])
    try:
        if ":" in rat:
            rw, rh = map(float, rat.split(":"))
        elif "x" in rat.lower():
            rw, rh = map(float, rat.lower().split("x"))
        else:
            return None
        if rw <= 0 or rh <= 0:
            return None
        aspect = rw / rh
        res_base = {"2K": 4194304, "3K": 9437184, "4K": 16777216}.get(res)
        if not res_base:
            return None
        width = int((res_base * aspect) ** 0.5)
        height = int(width / aspect)
        width = max(16, (width // 16) * 16)
        height = max(16, (height // 16) * 16)
        total = width * height
        if total < 3686400 or total > 16777216:
            target = min(max(total, 3686400), 16777216)
            scale = (target / total) ** 0.5
            width = int(width * scale)
            height = int(height * scale)
            width = max(16, (width // 16) * 16)
            height = max(16, (height // 16) * 16)
        return "{0}x{1}".format(width, height)
    except Exception:
        return None


def extract_urls(obj):
    urls = []
    err = obj.get("error")
    if err:
        raise APIError("API error: {0}".format(err))
    output = obj.get("output") or []
    for item in output:
        content = item.get("content") or []
        for c in content:
            txt = c.get("text") or ""
            if isinstance(txt, str):
                urls.extend(re.findall(r"https?://[^)\s]+", txt))
    return urls


def call_api(payload, api_key, timeout):
    headers = {"Content-Type": "application/json", "Authorization": api_key}
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(API_URL, data=body, headers=headers, method="POST")
    urls = []
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            ctype = resp.headers.get("Content-Type", "")
            if "text/event-stream" in ctype.lower():
                for raw in resp:
                    line = raw.decode("utf-8", errors="replace").strip()
                    if not line.startswith("data:"):
                        continue
                    data = line[5:].strip()
                    if not data or data == "[DONE]":
                        continue
                    try:
                        obj = json.loads(data)
                    except Exception:
                        continue
                    urls.extend(extract_urls(obj))
            else:
                data = resp.read()
                if not data:
                    raise APIError("empty response body")
                try:
                    obj = json.loads(data.decode("utf-8", errors="replace"))
                except Exception as e:
                    raise APIError("invalid JSON response: {0}".format(e))
                urls.extend(extract_urls(obj))
    except urllib.error.HTTPError as e:
        if e.code in (401, 403):
            raise AuthError("API key invalid or unauthorized")
        else:
            try:
                detail = e.read().decode("utf-8", errors="replace")[:500]
            except Exception:
                detail = ""
            raise APIError("HTTP {0}: {1}".format(e.code, detail))
    except urllib.error.URLError as e:
        raise NetworkError("network error: {0}".format(e.reason))
    except TimeoutError:
        raise NetworkError("timeout after {0}s".format(timeout))
    return urls


def download_image(url, path, timeout):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            with open(path, "wb") as f:
                f.write(resp.read())
    except urllib.error.HTTPError as e:
        raise NetworkError("download failed HTTP {0}".format(e.code))
    except urllib.error.URLError as e:
        raise NetworkError("download failed: {0}".format(e.reason))
    except TimeoutError:
        raise NetworkError("download timeout")


def create_placeholder_png(path, width, height, seed):
    rng = random.Random(seed if seed is not None else 0)
    raw = bytearray()
    for y in range(height):
        raw.append(0)
        for x in range(width):
            raw.append((x * 255 // max(1, width - 1)) if width > 1 else 0)
            raw.append((y * 255 // max(1, height - 1)) if height > 1 else 0)
            raw.append(rng.randint(0, 255))

    def chunk(tag, data):
        c = struct.pack(">I", len(data)) + tag + data
        c += struct.pack(">I", zlib.crc32(tag + data) & 0xffffffff)
        return c

    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    png = bytes([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a])
    png += chunk(b"IHDR", ihdr)
    png += chunk(b"IDAT", zlib.compress(bytes(raw), 9))
    png += chunk(b"IEND", b"")
    with open(path, "wb") as f:
        f.write(png)


def main():
    parser = argparse.ArgumentParser(description="Doubao Seedream 5.0 Lite text-to-image script")
    parser.add_argument("--params", required=True, help="Path to job.json")
    args = parser.parse_args()

    try:
        with open(args.params, "r", encoding="utf-8") as f:
            params = json.load(f)
    except Exception as e:
        fail("INVALID_PARAMS", "cannot read params: {0}".format(e))

    api_key = API_KEY or os.environ.get(KEY_ENV, "")
    if not api_key:
        fail("AUTH_FAILED", "{0} is not set".format(KEY_ENV))

    prompt = str(params.get("prompt") or "").strip()
    if not prompt:
        fail("INVALID_PARAMS", "prompt is required")

    ratio = str(params.get("ratio") or "1:1").strip()
    resolution = str(params.get("resolution") or "2K").strip()
    fmt = str(params.get("format") or "png").strip().lower()
    if fmt not in ("png", "jpeg"):
        fmt = "png"

    seed = params.get("seed")
    if seed is not None and str(seed).strip() != "":
        try:
            seed = int(seed)
        except Exception:
            fail("INVALID_PARAMS", "seed must be an integer")
    else:
        seed = None   # 空串/未提供 = 随机，不传 seed

    batch = params.get("batch", 1)
    try:
        batch = int(batch)
    except Exception:
        fail("INVALID_PARAMS", "batch must be an integer")
    if batch < 1 or batch > 15:
        fail("INVALID_PARAMS", "batch must be in [1, 15]")

    output_dir = str(params.get("output_dir") or ".").strip()
    try:
        timeout = float(params.get("timeout", 120))
    except Exception:
        fail("INVALID_PARAMS", "timeout must be a number")
    stream = bool(params.get("stream", False))
    web_search = bool(params.get("web_search", False))
    mock = bool(params.get("mock", False))

    os.makedirs(output_dir, exist_ok=True)

    pixel = get_pixel_size(resolution, ratio)
    payload = {
        "model": MODEL,
        "input": prompt,
        "output_format": fmt,
        "watermark": False,
        "response_format": "url",
    }

    if pixel:
        payload["size"] = pixel
    else:
        payload["size"] = resolution
        if ratio:
            payload["input"] = "{0}，请生成 {1} 比例的图片。".format(prompt, ratio)

    if batch > 1:
        payload["sequential_image_generation"] = "auto"
        payload["sequential_image_generation_options"] = {"max_images": batch}
    else:
        payload["sequential_image_generation"] = "disabled"

    quality = str(params.get("quality") or "standard").strip()
    if quality == "standard":
        payload.setdefault("optimize_prompt_options", {"mode": "standard"})

    if web_search:
        payload["tools"] = [{"type": "web_search"}]

    if stream:
        payload["stream"] = True

    if mock:
        if pixel:
            w, h = map(int, pixel.split("x"))
        else:
            w, h = 2048, 2048
        files = []
        base_ts = int(time.time())
        for i in range(batch):
            fname = "mock_{0}_{1}.{2}".format(base_ts, i + 1, fmt)
            fpath = os.path.join(output_dir, fname)
            create_placeholder_png(fpath, w, h, (seed or 0) + i)
            files.append(os.path.abspath(fpath))
        print(json.dumps({"status": "ok", "files": files, "elapsed": 0}, ensure_ascii=False))
        return

    start = time.time()
    try:
        urls = call_api(payload, api_key, timeout)
    except ScriptError as e:
        fail(e.code, str(e))
    except Exception as e:
        fail("INTERNAL", "unexpected error: {0}".format(e))

    if not urls:
        fail("API_ERROR", "no image URLs in API response")

    files = []
    base_ts = int(time.time())
    for i, url in enumerate(urls[:batch]):
        fname = "{0}_{1}.{2}".format(base_ts, i + 1, fmt)
        fpath = os.path.join(output_dir, fname)
        try:
            download_image(url, fpath, timeout)
        except NetworkError as e:
            fail(e.code, str(e))
        files.append(os.path.abspath(fpath))

    elapsed = time.time() - start
    print(json.dumps({"status": "ok", "files": files, "elapsed": round(elapsed, 2)}, ensure_ascii=False))


if __name__ == "__main__":
    main()