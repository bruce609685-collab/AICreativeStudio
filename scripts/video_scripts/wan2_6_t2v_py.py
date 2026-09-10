#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# [ACS_META_START]
# category       = video
# function       = t2v
# key_env        = DMXAPI_KEY
# resolutions    = 720p,1080p
# ratios         = 16:9,9:16,1:1,4:3,3:4
# qualities      = standard
# modes          = single,multi
# need_image     = false
# seed           = true
# sound          = true
# pip_requires   = 
# durations     = 2-15
# [ACS_META_END]

import argparse
import json
import os
import struct
import sys
import time
import urllib.error
import urllib.request

API_KEY = ""  # 安全：不内置密钥，运行时从环境变量 DMXAPI_KEY 或模型设置写入
API_ENDPOINT = 'https://www.dmxapi.cn/v1/responses'
MODEL_T2V = 'wan2.6-t2v'
MODEL_GET = 'wan2.6-get'


class ScriptError(Exception):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code
        self.message = message


def resolve_size(ratio, resolution):
    ratio = str(ratio).strip().lower()
    res = str(resolution).strip().lower()
    if res in ('720', '1080'):
        res += 'p'
    if ('*' in res or 'x' in res) and res.replace('*', '').replace('x', '').isdigit():
        return res.replace('x', '*')
    size_map = {
        ('720p', '16:9'): '1280*720',
        ('720p', '9:16'): '720*1280',
        ('720p', '1:1'): '960*960',
        ('720p', '4:3'): '1088*832',
        ('720p', '3:4'): '832*1088',
        ('1080p', '16:9'): '1920*1080',
        ('1080p', '9:16'): '1080*1920',
        ('1080p', '1:1'): '1440*1440',
        ('1080p', '4:3'): '1632*1248',
        ('1080p', '3:4'): '1248*1632',
    }
    size = size_map.get((res, ratio))
    if size is None:
        raise ScriptError('INVALID_PARAMS', f'Unsupported ratio/resolution combination: {resolution} {ratio}. Supported ratios 16:9, 9:16, 1:1, 4:3, 3:4 with 720p or 1080p')
    return size


def api_request(payload, timeout):
    body = json.dumps(payload).encode('utf-8')
    req = urllib.request.Request(API_ENDPOINT, data=body, headers={
        'Content-Type': 'application/json',
        'Authorization': API_KEY,
    }, method='POST')
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode('utf-8')
    except urllib.error.HTTPError as e:
        msg = e.read().decode('utf-8', errors='replace')
        if e.code in (401, 403):
            raise ScriptError('AUTH_FAILED', f'API auth failed: HTTP {e.code} {msg}')
        raise ScriptError('API_ERROR', f'API request failed: HTTP {e.code} {msg}')
    except urllib.error.URLError as e:
        raise ScriptError('NETWORK', f'Network error: {e.reason}')
    except TimeoutError:
        raise ScriptError('NETWORK', 'Request timeout')
    except (ConnectionError, OSError) as e:
        raise ScriptError('NETWORK', f'Network error: {e}')
    if not raw.strip():
        raise ScriptError('API_ERROR', 'Empty response body')
    try:
        return json.loads(raw)
    except json.JSONDecodeError as e:
        raise ScriptError('API_ERROR', f'Invalid JSON response: {e}')


def extract_output_text(data):
    try:
        output = data.get('output') or []
        for item in output:
            content = item.get('content') or []
            for c in content:
                if isinstance(c, dict) and c.get('type') == 'output_text':
                    text = c.get('text')
                    if isinstance(text, str) and text.strip():
                        return text.strip()
    except Exception:
        pass
    return None


def parse_inner_json(text):
    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        raise ScriptError('API_ERROR', f'Cannot parse task info: {e}')


def submit_task(payload, timeout):
    data = api_request(payload, timeout)
    text = extract_output_text(data)
    if text is None:
        raise ScriptError('API_ERROR', 'Missing output_text in submit response')
    inner = parse_inner_json(text)
    task_id = inner.get('task_id')
    if not task_id:
        raise ScriptError('API_ERROR', f'task_id missing in submit response: {inner}')
    return task_id


def query_task(task_id, timeout):
    data = api_request({'model': MODEL_GET, 'input': task_id}, timeout)
    text = extract_output_text(data)
    if text is None:
        raise ScriptError('API_ERROR', 'Missing output_text in query response')
    return parse_inner_json(text)


def download_file(url, dest_path, timeout):
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            with open(dest_path, 'wb') as f:
                while True:
                    chunk = resp.read(65536)
                    if not chunk:
                        break
                    f.write(chunk)
    except urllib.error.HTTPError as e:
        raise ScriptError('API_ERROR', f'Download failed: HTTP {e.code}')
    except urllib.error.URLError as e:
        raise ScriptError('NETWORK', f'Download failed: {e.reason}')
    except TimeoutError:
        raise ScriptError('NETWORK', 'Download timeout')


class BitWriter:
    def __init__(self):
        self.bits = []

    def write_code(self, code, code_size):
        for i in range(code_size):
            self.bits.append((code >> i) & 1)

    def get_bytes(self):
        out = bytearray()
        for i in range(0, len(self.bits), 8):
            byte = 0
            for j in range(8):
                if i + j < len(self.bits):
                    byte |= self.bits[i + j] << j
            out.append(byte)
        return bytes(out)


def lzw_encode(indices, min_code_size):
    clear = 1 << min_code_size
    end = clear + 1
    code_size = min_code_size + 1
    next_code = end + 1
    table = {}
    for i in range(clear):
        table[(i,)] = i
    writer = BitWriter()
    writer.write_code(clear, code_size)
    prefix = (indices[0],)
    for pixel in indices[1:]:
        key = prefix + (pixel,)
        if key in table:
            prefix = key
        else:
            writer.write_code(table[prefix], code_size)
            if next_code < 4096:
                table[key] = next_code
                next_code += 1
                if next_code == (1 << code_size) and code_size < 12:
                    code_size += 1
            else:
                writer.write_code(clear, code_size)
                table = {}
                for i in range(clear):
                    table[(i,)] = i
                next_code = end + 1
                code_size = min_code_size + 1
            prefix = (pixel,)
    writer.write_code(table[prefix], code_size)
    writer.write_code(end, code_size)
    data = writer.get_bytes()
    chunks = []
    for i in range(0, len(data), 255):
        chunk = data[i:i + 255]
        chunks.append(bytes([len(chunk)]) + chunk)
    chunks.append(bytes([0]))
    return b''.join(chunks)


def build_gif(width, height, frame_count):
    header = b'GIF89a'
    lsd = struct.pack('<HHBBB', width, height, 0xF0, 0, 0)
    palette = bytes([0, 0, 0, 255, 255, 255])
    netscape = bytes([0x21, 0xff, 0x0b]) + b'NETSCAPE2.0' + bytes([0x03, 0x01, 0x00, 0x00, 0x00])
    frames = b''
    radius = min(width, height) // 5
    center_y = height // 2
    for idx in range(frame_count):
        frame = [0] * (width * height)
        center_x = int((width + 2 * radius) * idx / max(1, frame_count - 1)) - radius
        for y in range(height):
            dy = (y - center_y) ** 2
            for x in range(width):
                if (x - center_x) ** 2 + dy <= radius * radius:
                    frame[y * width + x] = 1
        gce = bytes([0x21, 0xF9, 0x04, 0x04, 0x0A, 0x00, 0x00, 0x00])
        desc = struct.pack('<BHHHHB', 0x2C, 0, 0, width, height, 0)
        lzw_min = 2
        lzw_data = lzw_encode(frame, lzw_min)
        frames += gce + desc + bytes([lzw_min]) + lzw_data
    return header + lsd + palette + netscape + frames + bytes([0x3b])


def create_mock_gif(path):
    with open(path, 'wb') as f:
        f.write(build_gif(160, 90, 10))


def run(params):
    output_dir = params.get('output_dir') or '.'
    output_dir = os.path.abspath(output_dir)
    if not os.path.isdir(output_dir):
        try:
            os.makedirs(output_dir, exist_ok=True)
        except OSError as e:
            raise ScriptError('INVALID_PARAMS', f'Cannot create output_dir: {e}')

    task_id = params.get('task_id') or f'task_{int(time.time())}'
    if params.get('mock') in (True, 'true', 'True', '1'):
        dest = os.path.join(output_dir, f'{task_id}.gif')
        create_mock_gif(dest)
        return [dest]

    global API_KEY
    API_KEY = os.environ.get('DMXAPI_KEY', '').strip() or API_KEY.strip()
    if not API_KEY:
        raise ScriptError('AUTH_FAILED', 'DMXAPI_KEY environment variable is not set')

    prompt = params.get('prompt')
    if prompt is None or not str(prompt).strip():
        raise ScriptError('INVALID_PARAMS', 'prompt is required')
    prompt = str(prompt).strip()

    ratio = params.get('ratio') or '16:9'
    resolution = params.get('resolution') or '1080p'
    size = resolve_size(ratio, resolution)

    duration = 5
    if 'duration' in params and params.get('duration') not in (None, ''):
        try:
            duration = int(params.get('duration'))
        except (TypeError, ValueError):
            raise ScriptError('INVALID_PARAMS', 'duration must be an integer')
    if duration < 2 or duration > 15:
        raise ScriptError('INVALID_PARAMS', 'duration must be between 2 and 15')

    mode = params.get('mode') or 'single'
    shot_type = 'multi' if str(mode).lower() == 'multi' else 'single'

    seed = params.get('seed')
    if seed is not None and seed != '':
        try:
            seed = int(seed)
        except (TypeError, ValueError):
            raise ScriptError('INVALID_PARAMS', 'seed must be an integer')
        if seed < 0 or seed > 2147483647:
            raise ScriptError('INVALID_PARAMS', 'seed must be in [0, 2147483647]')

    timeout = 600
    if 'timeout' in params and params.get('timeout') not in (None, ''):
        try:
            timeout = float(params.get('timeout'))
        except (TypeError, ValueError):
            raise ScriptError('INVALID_PARAMS', 'timeout must be a number')
    if timeout <= 0:
        raise ScriptError('INVALID_PARAMS', 'timeout must be positive')

    negative_prompt = params.get('negative_prompt') or ''
    sound = params.get('sound')
    prompt_extend = params.get('prompt_extend', True)
    if isinstance(prompt_extend, str):
        prompt_extend = prompt_extend.lower() in ('true', '1')

    input_data = {
        'prompt': prompt,
        'negative_prompt': negative_prompt,
    }
    if sound:
        input_data['audio_url'] = str(sound)

    parameters = {
        'size': size,
        'prompt_extend': prompt_extend,
        'duration': duration,
        'shot_type': shot_type,
        'watermark': False,
    }
    if seed is not None and seed != '':
        parameters['seed'] = seed

    payload = {
        'model': MODEL_T2V,
        'input': input_data,
        'parameters': parameters,
    }

    # 全局预算：提交 + 轮询 + 下载共享；提交接口实测需 30~48 秒，上限 120 秒
    deadline = time.time() + timeout
    submit_timeout = min(120.0, max(1.0, deadline - time.time()))
    task_id = submit_task(payload, submit_timeout)

    poll_interval = 3.0
    while True:
        remaining = deadline - time.time()
        if remaining <= 0:
            raise ScriptError('NETWORK', 'Task polling timeout')
        inner = query_task(task_id, min(60.0, remaining))
        status = inner.get('task_status')
        if status == 'SUCCEEDED':
            video_url = inner.get('video_url')
            if not video_url:
                raise ScriptError('API_ERROR', f'SUCCEEDED but video_url missing: {inner}')
            ext = '.mp4'
            path_part = str(video_url).split('?')[0]
            lower_path = path_part.lower()
            for known_ext in ('.mp4', '.mov', '.webm'):
                if lower_path.endswith(known_ext):
                    ext = known_ext
                    break
            dest = os.path.join(output_dir, f'{task_id}{ext}')
            download_file(video_url, dest, min(60.0, remaining))
            return [dest]
        if status == 'FAILED':
            raise ScriptError('API_ERROR', f'Task failed: {inner.get("message")}')
        if status not in ('PENDING', 'RUNNING'):
            raise ScriptError('API_ERROR', f'Unknown task_status: {status}')
        time.sleep(min(poll_interval, max(0.1, remaining - 0.1)))


def main():
    parser = argparse.ArgumentParser(description='wan2.6 text-to-video script')
    parser.add_argument('--params', required=True, help='path to job params JSON')
    args = parser.parse_args()

    if not os.path.isfile(args.params):
        print(json.dumps({'status': 'error', 'code': 'INVALID_PARAMS', 'message': 'params file not found'}, ensure_ascii=False))
        sys.exit(0)
    try:
        with open(args.params, 'r', encoding='utf-8') as f:
            params = json.load(f)
    except Exception as e:
        print(json.dumps({'status': 'error', 'code': 'INVALID_PARAMS', 'message': f'failed to read params: {e}'}, ensure_ascii=False))
        sys.exit(0)
    if not isinstance(params, dict):
        print(json.dumps({'status': 'error', 'code': 'INVALID_PARAMS', 'message': 'params must be a JSON object'}, ensure_ascii=False))
        sys.exit(0)

    start = time.time()
    try:
        files = run(params)
        print(json.dumps({'status': 'ok', 'files': files, 'elapsed': round(time.time() - start, 3)}, ensure_ascii=False))
    except ScriptError as e:
        print(json.dumps({'status': 'error', 'code': e.code, 'message': e.message}, ensure_ascii=False))
    except Exception as e:
        print(json.dumps({'status': 'error', 'code': 'INTERNAL', 'message': f'{e}'}, ensure_ascii=False))


if __name__ == '__main__':
    main()