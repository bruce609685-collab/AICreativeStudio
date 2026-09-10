"""MiniMax · 视频生成（MiniMax-H3）——制式脚本样例。

模板版本：1.0.0
依赖：Pillow（仅 mock 分支产 GIF 用；真实调用走标准库 urllib）

契约要点：
- 异步任务协议（创建 → 轮询 → 下载）：脚本内部完成，外壳不感知
- 产物 URL 有实效，脚本必须下载落盘后再回传文件路径
- mock=true 时不发起网络请求，用 Pillow 产多帧 GIF 动画（真实可播）
- KEY 优先级：脚本内 API_KEY 常量 → 环境变量 MINIMAX_API_KEY
- 超时：timeout 是"整个任务总预算"（提交 + 轮询 + 下载合计），由外壳下发；
  各阶段只允许在剩余预算内取用，严禁给单次请求设远小于总预算的硬性上限
- 真实接口字段以 MiniMax 开放平台官方文档为准（本脚本为 v1 骨架）

# [ACS_META_START]
# display_name  = MiniMax · 视频生成（H3）
# category      = video
# function      = t2v
# stream        = false
# web_search    = false
# seed          = false
# resolutions   = 720p,1080p
# ratios        = 16:9,9:16,1:1,4:3,3:4
# durations     = 5,6,10
# qualities     = standard
# modes         = std,pro
# formats       = mp4,gif
# sound         = true
# need_image    = false
# key_env       = MINIMAX_API_KEY
# pip_requires  = pillow
# [ACS_META_END]
"""

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path

API_KEY = ""  # 由模型设置「确定」写入；为空时回退环境变量 MINIMAX_API_KEY

MODEL_ID = "MiniMax-H3"
API_BASE = "https://api.minimaxi.com/v1"
POLL_INTERVAL = 5.0      # 轮询间隔（秒）
DEFAULT_TIMEOUT = 600.0  # 默认总预算（秒）：提交 + 轮询 + 下载共享


# ----------------------------------------------------------------------
# mock：Pillow 产多帧 GIF 动画（真实可播的占位产物）
# ----------------------------------------------------------------------

def make_mock_gif(path: Path, ratio: str, duration: int) -> None:
    from PIL import Image, ImageDraw

    width, height = 960, 540
    if ratio == "9:16":
        width, height = 540, 960
    elif ratio == "1:1":
        width, height = 768, 768
    elif ratio == "4:3":
        width, height = 896, 672
    elif ratio == "3:4":
        width, height = 672, 896

    frames = max(8, min(48, int(duration or 5) * 4))
    images: list[Image.Image] = []
    base = (60, 90, 200)
    for i in range(frames):
        t = i / max(1, frames - 1)
        img = Image.new("RGB", (width, height), base)
        draw = ImageDraw.Draw(img)
        # 竖向渐变
        for y in range(0, height, 8):
            k = y / height
            draw.rectangle([0, y, width, y + 8], fill=(
                int(base[0] + (255 - base[0]) * k * 0.5),
                int(base[1] + (255 - base[1]) * k * 0.5),
                int(base[2] + (255 - base[2]) * k * 0.5),
            ))
        # 水平移动的圆形
        cx = int(width * (0.15 + 0.7 * ((t * 2) % 1)))
        cy = int(height * 0.55)
        draw.ellipse([cx - 50, cy - 50, cx + 50, cy + 50], fill=(255, 215, 80))
        # 序号文字
        draw.text((width // 2 - 40, 24), f"MOCK {i + 1}/{frames}",
                  fill=(255, 255, 255))
        images.append(img)
    images[0].save(str(path), save_all=True, append_images=images[1:],
                   duration=int(1000 / 4), loop=0)


# ----------------------------------------------------------------------
# 真实调用（异步任务协议）
# ----------------------------------------------------------------------

def _resolve_key() -> str:
    if API_KEY.strip():
        return API_KEY.strip()
    return os.environ.get("MINIMAX_API_KEY", "").strip()


def _request(method: str, url: str, body: dict | None, key: str,
             timeout: float) -> dict:
    req = urllib.request.Request(
        url,
        data=json.dumps(body).encode("utf-8") if body is not None else None,
        headers={"Authorization": f"Bearer {key}",
                 "Content-Type": "application/json"},
        method=method,
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"API_ERROR|HTTP {exc.code}|{raw[:300]}") from None
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise RuntimeError(f"NETWORK|{exc}") from None


def _call_minimax(prompt: str, ratio: str, resolution: str,
                  duration: int, sound: bool, key: str,
                  timeout: float) -> str:
    """创建视频任务 → 轮询到完成 → 返回产物 file_url。

    全局预算 deadline：提交 + 轮询共享同一份 timeout，避免各阶段各拿
    一份、总耗时远超外壳强杀上限。提交接口实测响应需 30~48 秒，上限
    给到 120 秒，仍受全局预算约束。
    """
    deadline = time.time() + timeout
    create_body: dict = {
        "model": MODEL_ID,
        "prompt": prompt,
        "prompt_optimizer": False,
        "aspect_ratio": ratio,
        "duration": int(duration),
        "resolution": resolution or "720p",
        "subject_reference": [],
        "camera": [],
    }
    if sound:
        create_body["generate_audio"] = True
    created = _request("POST", f"{API_BASE}/video_generation",
                       create_body, key,
                       min(120.0, max(1.0, deadline - time.time())))
    task_id = created.get("task_id") or created.get("video_id")
    if not task_id:
        raise RuntimeError(f"API_ERROR|创建任务失败：{created}")

    while time.time() < deadline:
        time.sleep(min(POLL_INTERVAL, max(0.1, deadline - time.time())))
        query = _request(
            "GET",
            f"{API_BASE}/video_generation/query/{task_id}?model={MODEL_ID}",
            None, key,
            min(60.0, max(1.0, deadline - time.time())),
        )
        status = str(query.get("status", "")).lower()
        if status in ("succeed", "succeeded", "success"):
            data = query.get("data") or {}
            file_url = data.get("file_url") or query.get("file_url")
            if not file_url:
                raise RuntimeError(f"API_ERROR|任务成功但缺 file_url：{query}")
            return str(file_url)
        if status in ("failed", "fail", "error"):
            raise RuntimeError(f"API_ERROR|任务失败：{query}")
    raise RuntimeError("TIMEOUT|视频任务轮询超时")


def _download(url: str, dest: Path, timeout: float) -> None:
    req = urllib.request.Request(url, method="GET")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        dest.write_bytes(resp.read())


# ----------------------------------------------------------------------
# 主流程
# ----------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(description="MiniMax H3 视频生成制式脚本")
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
    ratio = str(params.get("ratio", "16:9"))
    resolution = str(params.get("resolution", "720p"))
    duration = max(1, min(60, int(params.get("duration", 5) or 5)))
    sound = bool(params.get("sound", False))
    mock = bool(params.get("mock", False))

    # 总预算：提交 + 轮询 + 下载共享；由外壳下发，缺省 600 秒
    timeout = DEFAULT_TIMEOUT
    try:
        if params.get("timeout") not in (None, ""):
            timeout = float(params.get("timeout"))
    except (TypeError, ValueError):
        timeout = DEFAULT_TIMEOUT
    if timeout <= 0:
        timeout = DEFAULT_TIMEOUT
    deadline = started + timeout

    try:
        output_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")

        if mock:
            path = output_dir / f"minimax_mock_{stamp}.gif"
            make_mock_gif(path, ratio, duration)
            files = [str(path.resolve())]
        else:
            key = _resolve_key()
            if not key:
                _emit({"status": "error", "code": "AUTH_FAILED",
                       "message": "API KEY 未配置（脚本内 API_KEY 或环境变量 MINIMAX_API_KEY）"})
                return 1
            file_url = _call_minimax(prompt, ratio, resolution, duration,
                                     sound, key,
                                     max(1.0, deadline - time.time()))
            path = output_dir / f"minimax_{stamp}.mp4"
            _download(file_url, path, max(1.0, deadline - time.time()))
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
