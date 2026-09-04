#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# [ACS_META_START]
# category       = video
# function       = t2v
# key_env        = HAPPYHORSE_API_KEY
# resolutions    = 720P,1080P
# ratios         = 16:9,9:16,1:1,4:3,3:4,4:5,5:4,9:21,21:9
# qualities      = standard
# modes          = t2v
# need_image     = false
# seed           = true
# sound          = false
# durations     = 2-15
# [ACS_META_END]

import argparse
import json
import os
import sys
import time
import urllib.request
import urllib.error
import uuid

API_KEY = ""  # 安全：不内置密钥，运行时从环境变量 HAPPYHORSE_API_KEY 注入

API_BASE = "https://www.dmxapi.cn/v1/responses"
MODEL_SUBMIT = "happyhorse-1.0-t2v"
MODEL_GET = "happyhorse-get"
DEFAULT_TIMEOUT = 300
POLL_INTERVAL = 15


def _bit_writer_write(bits, value, width):
    for i in range(width):
        bits.append((value >> i) & 1)


def _lzw_encode(data, min_code_size):
    clear = 1 << min_code_size
    end = clear + 1
    next_code = end + 1
    code_width = min_code_size + 1
    dictionary = {bytes([i]): i for i in range(clear)}
    bits = []
    _bit_writer_write(bits, clear, code_width)
    current = b""
    for byte in data:
        b = bytes([byte])
        if current == b"":
            current = b
        else:
            nxt = current + b
            if nxt in dictionary:
                current = nxt
            else:
                _bit_writer_write(bits, dictionary[current], code_width)
                if next_code < 4096:
                    dictionary[nxt] = next_code
                    next_code += 1
                    if next_code == (1 << code_width) and code_width < 12:
                        code_width += 1
                current = b
    if current:
        _bit_writer_write(bits, dictionary[current], code_width)
    _bit_writer_write(bits, end, code_width)
    compressed = bytearray()
    for i in range(0, len(bits), 8):
        byte = 0
        for j, bit in enumerate(bits[i:i+8]):
            byte |= bit << j
        compressed.append(byte)
    result = bytearray([min_code_size])
    for i in range(0, len(compressed), 255):
        chunk = compressed[i:i+255]
        result.append(len(chunk))
        result.extend(chunk)
    result.append(0)
    return bytes(result)


def _generate_mock_gif(path, duration=5):
    width, height = 32, 32
    palette = [
        (255, 0, 0),
        (0, 255, 0),
        (0, 0, 255),
        (255, 255, 0),
        (0, 255, 255),
        (255, 0, 255),
    ]
    frames_count = len(palette)
    delay = max(1, int((duration * 100) / frames_count))
    gif = bytearray()
    gif.extend(b"GIF89a")
    gif.extend(width.to_bytes(2, "little"))
    gif.extend(height.to_bytes(2, "little"))
    packed = 0x80 | 0x70 | 0x02
    gif.append(packed)
    gif.append(0)
    gif.append(0)
    for i in range(8):
        if i < len(palette):
            gif.extend(palette[i])
        else:
            gif.extend((0, 0, 0))
    for frame_idx in range(frames_count):
        gif.append(0x21)
        gif.append(0xF9)
        gif.append(0x04)
        gif.append(0x00)
        gif.append(delay & 0xFF)
        gif.append((delay >> 8) & 0xFF)
        gif.append(0x00)
        gif.append(0x00)
        gif.append(0x2C)
        gif.extend((0).to_bytes(2, "little"))
        gif.extend((0).to_bytes(2, "little"))
        gif.extend(width.to_bytes(2, "little"))
        gif.extend(height.to_bytes(2, "little"))
        gif.append(0x00)
        indices = [frame_idx] * (width * height)
        gif.extend(_lzw_encode(indices, 3))
    gif.append(0x3B)
    with open(path, "wb") as f:
        f.write(gif)


def _http_post(url, headers, payload, timeout):
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8")


def _download_file(url, path, timeout=300):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        with open(path, "wb") as f:
            while True:
                chunk = resp.read(8192)
                if not chunk:
                    break
                f.write(chunk)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--params", required=True)
    args = parser.parse_args()

    try:
        with open(args.params, "r", encoding="utf-8") as f:
            params = json.load(f)
    except Exception as e:
        print(json.dumps({"status": "error", "code": "INVALID_PARAMS", "message": f"cannot read params file: {e}"}))
        return

    prompt = params.get("prompt", "")
    if not prompt:
        print(json.dumps({"status": "error", "code": "INVALID_PARAMS", "message": "prompt is required"}))
        return

    ratio = params.get("ratio", "16:9")
    resolution = params.get("resolution", "1080P")
    duration = params.get("duration", 5)
    seed = params.get("seed", None)
    output_dir = params.get("output_dir", ".")
    task_id = params.get("task_id", "")
    mock = params.get("mock", False)
    timeout = params.get("timeout", DEFAULT_TIMEOUT)
    watermark = params.get("watermark", False)

    if isinstance(mock, str):
        mock = mock.lower() in ("true", "1", "yes")
    if isinstance(watermark, str):
        watermark = watermark.lower() in ("true", "1", "yes")

    try:
        duration = int(duration)
        if seed is not None and seed != '':
            seed = int(seed)
        timeout = int(timeout)
    except (TypeError, ValueError) as e:
        print(json.dumps({"status": "error", "code": "INVALID_PARAMS", "message": f"numeric param parse error: {e}"}))
        return

    if not 3 <= duration <= 15:
        print(json.dumps({"status": "error", "code": "INVALID_PARAMS", "message": "duration must be between 3 and 15"}))
        return
    if ratio not in ["16:9", "9:16", "1:1", "4:3", "3:4", "4:5", "5:4", "9:21", "21:9"]:
        print(json.dumps({"status": "error", "code": "INVALID_PARAMS", "message": f"unsupported ratio: {ratio}"}))
        return
    if resolution not in ["720P", "1080P"]:
        print(json.dumps({"status": "error", "code": "INVALID_PARAMS", "message": f"unsupported resolution: {resolution}"}))
        return

    os.makedirs(output_dir, exist_ok=True)

    if mock:
        out_file = os.path.join(output_dir, f"mock_{task_id or uuid.uuid4().hex}.gif")
        try:
            _generate_mock_gif(out_file, duration=duration)
        except Exception as e:
            print(json.dumps({"status": "error", "code": "INTERNAL", "message": f"mock gif generation failed: {e}"}))
            return
        print(json.dumps({"status": "ok", "files": [out_file], "elapsed": 0.0}))
        return

    api_key = os.environ.get("HAPPYHORSE_API_KEY", "") or API_KEY
    if not api_key:
        print(json.dumps({"status": "error", "code": "AUTH_FAILED", "message": "API key is missing (set env HAPPYHORSE_API_KEY)"}))
        return

    headers = {"Content-Type": "application/json", "Authorization": api_key}
    start_time = time.time()

    submit_payload = {
        "model": MODEL_SUBMIT,
        "input": [{"prompt": prompt}],
        "parameters": {
            "resolution": resolution,
            "ratio": ratio,
            "duration": duration,
            "watermark": watermark,
        },
    }
    if seed is not None:
        submit_payload["parameters"]["seed"] = seed

    try:
        resp_text = _http_post(API_BASE, headers, submit_payload, timeout)
        submit_data = json.loads(resp_text)
    except urllib.error.HTTPError as e:
        if e.code in (401, 403):
            print(json.dumps({"status": "error", "code": "AUTH_FAILED", "message": f"authentication failed: HTTP {e.code}"}))
        else:
            print(json.dumps({"status": "error", "code": "API_ERROR", "message": f"submit failed: HTTP {e.code} {e.reason}"}))
        return
    except urllib.error.URLError as e:
        print(json.dumps({"status": "error", "code": "NETWORK", "message": f"network error: {e.reason}"}))
        return
    except Exception as e:
        print(json.dumps({"status": "error", "code": "API_ERROR", "message": f"submit response parse error: {e}"}))
        return

    try:
        text = submit_data["output"][0]["content"][0]["text"]
        inner = json.loads(text)
        task_id = inner["task_id"]
        task_status = inner.get("task_status", "")
    except (KeyError, IndexError, json.JSONDecodeError) as e:
        print(json.dumps({"status": "error", "code": "API_ERROR", "message": f"submit response invalid structure: {e}"}))
        return

    if task_status not in ("PENDING", "RUNNING"):
        print(json.dumps({"status": "error", "code": "API_ERROR", "message": f"unexpected initial task status: {task_status}"}))
        return

    deadline = start_time + timeout
    video_url = None
    while True:
        remaining = deadline - time.time()
        if remaining <= 0:
            print(json.dumps({"status": "error", "code": "NETWORK", "message": "polling timed out"}))
            return

        query_payload = {"model": MODEL_GET, "input": task_id}
        try:
            resp_text = _http_post(API_BASE, headers, query_payload, timeout)
            data = json.loads(resp_text)
            text = data["output"][0]["content"][0]["text"]
            inner = json.loads(text)
            status = inner.get("task_status", "")

            if status == "SUCCEEDED":
                video_url = inner.get("video_url")
                if not video_url:
                    print(json.dumps({"status": "error", "code": "API_ERROR", "message": "task succeeded but video_url missing"}))
                    return
                break
            elif status in ("FAILED", "CANCELED", "UNKNOWN"):
                print(json.dumps({"status": "error", "code": "API_ERROR", "message": f"task failed with status {status}: {inner}"}))
                return
        except urllib.error.HTTPError as e:
            if e.code in (401, 403):
                print(json.dumps({"status": "error", "code": "AUTH_FAILED", "message": f"authentication failed: HTTP {e.code}"}))
            else:
                print(json.dumps({"status": "error", "code": "API_ERROR", "message": f"query failed: HTTP {e.code} {e.reason}"}))
            return
        except urllib.error.URLError as e:
            print(json.dumps({"status": "error", "code": "NETWORK", "message": f"network error: {e.reason}"}))
            return
        except Exception as e:
            print(json.dumps({"status": "error", "code": "API_ERROR", "message": f"query response parse error: {e}"}))
            return

        wait = min(POLL_INTERVAL, remaining)
        if wait > 0:
            time.sleep(wait)

    out_file = os.path.join(output_dir, f"{task_id}.mp4")
    try:
        _download_file(video_url, out_file, timeout=timeout)
    except urllib.error.URLError as e:
        print(json.dumps({"status": "error", "code": "NETWORK", "message": f"download failed: {e.reason}"}))
        return
    except Exception as e:
        print(json.dumps({"status": "error", "code": "API_ERROR", "message": f"download failed: {e}"}))
        return

    elapsed = time.time() - start_time
    print(json.dumps({"status": "ok", "files": [out_file], "elapsed": round(elapsed, 2)}))


if __name__ == "__main__":
    main()