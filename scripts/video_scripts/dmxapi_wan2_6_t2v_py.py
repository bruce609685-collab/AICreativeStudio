#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# [ACS_META_START]
# category=video
# function=t2v
# key_env=DMXAPI_API_KEY
# resolutions=720p,1080p
# ratios=16:9,9:16,1:1,4:3,3:4
# qualities=standard
# modes=single,multi
# need_image=false
# seed=true
# sound=false
# pip_requires=
# durations     = 2-15
# [ACS_META_END]
# 依赖安装：无（仅标准库）

import argparse
import json
import os
import shutil
import socket
import struct
import time
import urllib.error
import urllib.request

API_KEY = ""
API_BASE = 'https://www.dmxapi.cn/v1/responses'
MODEL_T2V = 'wan2.6-t2v'
MODEL_GET = 'wan2.6-get'
KEY_ENV = 'DMXAPI_API_KEY'

SIZE_MAP = {
    ('1080p', '16:9'): '1920*1080',
    ('1080p', '9:16'): '1080*1920',
    ('1080p', '1:1'): '1440*1440',
    ('1080p', '4:3'): '1632*1248',
    ('1080p', '3:4'): '1248*1632',
    ('720p', '16:9'): '1280*720',
    ('720p', '9:16'): '720*1280',
    ('720p', '1:1'): '960*960',
    ('720p', '4:3'): '1088*832',
    ('720p', '3:4'): '832*1088',
}

class ApiError(Exception):
    def __init__(self, code, message):
        self.code = code
        self.message = message
        super().__init__(message)

def emit(obj):
    print(json.dumps(obj, ensure_ascii=False))

def get_api_key():
    env_key = os.environ.get(KEY_ENV, '').strip()
    return env_key or API_KEY.strip()

def normalize_ratio(ratio):
    r = str(ratio).strip()
    if r in ('16:9', '16/9'):
        return '16:9'
    if r in ('9:16', '9/16'):
        return '9:16'
    if r in ('1:1',):
        return '1:1'
    if r in ('4:3',):
        return '4:3'
    if r in ('3:4',):
        return '3:4'
    raise ApiError('INVALID_PARAMS', 'unsupported ratio: ' + str(ratio))

def normalize_resolution(res):
    r = str(res).strip().lower()
    if r in ('720', '720p'):
        return '720p'
    if r in ('1080', '1080p'):
        return '1080p'
    raise ApiError('INVALID_PARAMS', 'unsupported resolution: ' + str(res))

def parse_duration(dur):
    try:
        d = int(dur)
    except (ValueError, TypeError):
        raise ApiError('INVALID_PARAMS', 'invalid duration: ' + str(dur))
    if d < 2 or d > 15:
        raise ApiError('INVALID_PARAMS', 'duration must be between 2 and 15')
    return d

def parse_seed(raw):
    if raw is None or raw == '':
        return None
    try:
        s = int(raw)
    except (ValueError, TypeError):
        raise ApiError('INVALID_PARAMS', 'invalid seed: ' + str(raw))
    if s < 0 or s > 2147483647:
        raise ApiError('INVALID_PARAMS', 'seed out of range [0, 2147483647]')
    return s

def parse_timeout(raw):
    try:
        return float(raw)
    except (ValueError, TypeError):
        raise ApiError('INVALID_PARAMS', 'invalid timeout: ' + str(raw))

def is_mock(params):
    value = params.get('mock', False)
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() == 'true'

def call_api(headers, payload, timeout):
    data = json.dumps(payload).encode('utf-8')
    req = urllib.request.Request(API_BASE, data=data, headers=headers, method='POST')
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode('utf-8')
    except urllib.error.HTTPError as e:
        if e.code in (401, 403):
            raise ApiError('AUTH_FAILED', 'HTTP ' + str(e.code) + ' ' + str(e.reason))
        raise ApiError('API_ERROR', 'HTTP ' + str(e.code) + ' ' + str(e.reason))
    except urllib.error.URLError as e:
        raise ApiError('NETWORK', str(e.reason))
    except socket.timeout:
        raise ApiError('NETWORK', 'request timed out')
    try:
        result = json.loads(body)
    except ValueError:
        raise ApiError('API_ERROR', 'response body is not valid JSON')
    if isinstance(result, dict) and result.get('error'):
        raise ApiError('API_ERROR', str(result.get('error')))
    return result

def extract_inner_text(result):
    try:
        text = result['output'][0]['content'][0]['text']
    except (KeyError, IndexError, TypeError):
        raise ApiError('API_ERROR', 'missing output content')
    try:
        return json.loads(text)
    except ValueError:
        raise ApiError('API_ERROR', 'output text is not JSON: ' + text)

def build_payload(prompt, negative_prompt, size, duration, mode, seed, sound):
    input_obj = {
        'prompt': prompt,
        'negative_prompt': negative_prompt or '',
    }
    if isinstance(sound, str) and sound.startswith(('http://', 'https://')):
        input_obj['audio_url'] = sound
    parameters = {
        'size': size,
        'prompt_extend': True,
        'duration': duration,
        'shot_type': mode,
        'watermark': False,
    }
    if seed is not None:
        parameters['seed'] = seed
    return {
        'model': MODEL_T2V,
        'input': input_obj,
        'parameters': parameters,
    }

def submit_task(headers, payload, timeout):
    result = call_api(headers, payload, timeout)
    inner = extract_inner_text(result)
    task_id = inner.get('task_id')
    if not task_id:
        raise ApiError('API_ERROR', 'no task_id in submit response')
    return task_id

def poll_task(headers, task_id, timeout):
    deadline = time.time() + timeout
    while time.time() < deadline:
        remaining = deadline - time.time()
        if remaining <= 0:
            break
        query_payload = {'model': MODEL_GET, 'input': task_id}
        result = call_api(headers, query_payload, min(60.0, remaining))
        inner = extract_inner_text(result)
        status = inner.get('task_status', '')
        if status == 'SUCCEEDED':
            video_url = inner.get('video_url')
            if not video_url:
                raise ApiError('API_ERROR', 'SUCCEEDED but no video_url')
            return video_url
        if status == 'FAILED':
            raise ApiError('API_ERROR', 'task failed: ' + str(inner.get('message', 'unknown')))
        if status not in ('PENDING', 'RUNNING'):
            raise ApiError('API_ERROR', 'unknown task_status: ' + status)
        time.sleep(2)
    raise ApiError('NETWORK', 'polling timeout')

def download_video(url, dest_path, timeout):
    try:
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            with open(dest_path, 'wb') as f:
                shutil.copyfileobj(resp, f)
    except urllib.error.HTTPError as e:
        raise ApiError('API_ERROR', 'download HTTP ' + str(e.code) + ' ' + str(e.reason))
    except urllib.error.URLError as e:
        raise ApiError('NETWORK', 'download failed: ' + str(e.reason))
    except socket.timeout:
        raise ApiError('NETWORK', 'download timeout')

class BitWriter:
    def __init__(self):
        self.bits = 0
        self.nbits = 0
        self.out = bytearray()

    def write(self, code, size):
        self.bits |= code << self.nbits
        self.nbits += size
        while self.nbits >= 8:
            self.out.append(self.bits & 0xFF)
            self.bits >>= 8
            self.nbits -= 8

    def flush(self):
        while self.nbits > 0:
            self.out.append(self.bits & 0xFF)
            self.bits >>= 8
            self.nbits -= 8
        return bytes(self.out)

def lzw_encode(data, min_code_size):
    clear_code = 1 << min_code_size
    end_code = clear_code + 1
    next_code = end_code + 1
    code_size = min_code_size + 1
    dictionary = {bytes([i]): i for i in range(clear_code)}
    writer = BitWriter()
    writer.write(clear_code, code_size)
    w = b''
    for value in data:
        k = bytes([value])
        if w + k in dictionary:
            w = w + k
        else:
            writer.write(dictionary[w], code_size)
            if next_code < 4096:
                dictionary[w + k] = next_code
                next_code += 1
                if next_code == (1 << code_size) and code_size < 12:
                    code_size += 1
            w = k
    if w:
        writer.write(dictionary[w], code_size)
    writer.write(end_code, code_size)
    return writer.flush()

def make_mock_gif(path):
    width = 120
    height = 120
    frames = 4
    header = b'GIF89a'
    logical_screen = struct.pack('<HH', width, height) + bytes([0x80, 0, 0])
    global_table = bytes([0, 0, 0, 255, 255, 255])
    netscape_ext = bytes([0x21, 0xFF, 0x0B]) + b'NETSCAPE2.0' + bytes([0x03, 0x01, 0, 0, 0])
    data = bytearray()
    data += header
    data += logical_screen
    data += global_table
    data += netscape_ext
    for frame in range(frames):
        pixels = []
        start_x = (frame * 20) % (width - 20)
        start_y = (frame * 10) % (height - 20)
        for y in range(height):
            for x in range(width):
                if start_x <= x < start_x + 20 and start_y <= y < start_y + 20:
                    pixels.append(1)
                else:
                    pixels.append(0)
        compressed = lzw_encode(pixels, 2)
        gce = bytes([0x21, 0xF9, 0x04, 0x00]) + struct.pack('<H', 8) + bytes([0x00, 0x00])
        desc = bytes([0x2C]) + struct.pack('<HHHH', 0, 0, width, height) + bytes([0x00])
        data += gce
        data += desc
        data += bytes([2])
        for i in range(0, len(compressed), 255):
            chunk = compressed[i:i + 255]
            data += bytes([len(chunk)])
            data += chunk
        data += bytes([0])
    data += bytes([0x3B])
    with open(path, 'wb') as f:
        f.write(data)

def create_mock_video(output_dir):
    filename = 'mock_' + time.strftime('%Y%m%d_%H%M%S') + '.gif'
    path = os.path.join(output_dir, filename)
    make_mock_gif(path)
    return os.path.abspath(path)

def run(params):
    start = time.time()
    output_dir = params.get('output_dir') or '.'
    os.makedirs(output_dir, exist_ok=True)

    if is_mock(params):
        video_path = create_mock_video(output_dir)
        return {'files': [video_path], 'elapsed': round(time.time() - start, 3)}

    task_id = params.get('task_id')
    headers = None
    timeout = parse_timeout(params.get('timeout') or 600)
    # 全局预算：提交 + 轮询 + 下载共享同一份 timeout，
    # 避免各阶段各拿一份、总耗时远超外壳的强杀上限
    deadline = start + timeout

    if not task_id:
        prompt = params.get('prompt')
        if not prompt or not str(prompt).strip():
            raise ApiError('INVALID_PARAMS', 'prompt is required')
        ratio = normalize_ratio(params.get('ratio', '16:9'))
        res = normalize_resolution(params.get('resolution', '1080p'))
        size = SIZE_MAP.get((res, ratio))
        if not size:
            raise ApiError('INVALID_PARAMS', 'unsupported combination of resolution and ratio')
        duration = parse_duration(params.get('duration', '5'))
        mode = params.get('mode', 'single')
        if mode not in ('single', 'multi'):
            raise ApiError('INVALID_PARAMS', 'mode must be single or multi')
        seed = parse_seed(params.get('seed'))
        negative_prompt = params.get('negative_prompt', '')
        sound = params.get('sound')

        key = get_api_key()
        if not key:
            raise ApiError('AUTH_FAILED', 'DMXAPI_API_KEY is not set')
        headers = {
            'Content-Type': 'application/json',
            'Authorization': key,
        }
        payload = build_payload(str(prompt), negative_prompt, size, duration, mode, seed, sound)
        # 提交接口实测响应需 30~48 秒，上限给到 120 秒（仍受全局预算约束）
        task_id = submit_task(headers, payload, min(120.0, max(1.0, deadline - time.time())))

    if headers is None:
        key = get_api_key()
        if not key:
            raise ApiError('AUTH_FAILED', 'DMXAPI_API_KEY is not set')
        headers = {
            'Content-Type': 'application/json',
            'Authorization': key,
        }

    video_url = poll_task(headers, str(task_id), max(1.0, deadline - time.time()))
    dest_path = os.path.join(output_dir, 'wan2.6_' + str(task_id) + '.mp4')
    download_video(video_url, dest_path, max(1.0, deadline - time.time()))
    return {'files': [os.path.abspath(dest_path)], 'elapsed': round(time.time() - start, 3)}

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--params', required=True, help='Path to job params JSON')
    args = parser.parse_args()
    try:
        with open(args.params, 'r', encoding='utf-8') as f:
            params = json.load(f)
    except Exception as e:
        emit({'status': 'error', 'code': 'INVALID_PARAMS', 'message': 'cannot read params: ' + str(e)})
        return
    try:
        result = run(params)
        emit({'status': 'ok', 'files': result['files'], 'elapsed': result['elapsed']})
    except ApiError as e:
        emit({'status': 'error', 'code': e.code, 'message': e.message})
    except Exception as e:
        emit({'status': 'error', 'code': 'INTERNAL', 'message': str(e)})

if __name__ == '__main__':
    main()