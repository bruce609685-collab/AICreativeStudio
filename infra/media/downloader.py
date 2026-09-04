"""产物 URL 下载落盘（headless）。部分 AI 服务只返回临时下载链接。

背景：一些视频/图片 API 异步任务完成后只给一个带签名的临时 URL，
通常 24 小时内失效（见需求 §7 infra/media/downloader 规划）。本模块
负责把 URL 内容及时下载到本地产物目录，带重试与超时。

设计要点：
- 纯 headless（urllib 标准库，无 PySide6 / httpx 强依赖），可独立测试；
- download_url(url, dest_dir, filename=None, retries=2, timeout=60)：
  失败自动重试（指数退避：2s、4s），全部失败抛 DownloadError；
- safe_filename(name)：清洗 URL/服务端给的文件名，防路径穿越。

M2 规划项，本版填充实现；脚本侧也可直接 import 使用。
"""

from __future__ import annotations

import logging
import re
import time
import urllib.request
from pathlib import Path

logger = logging.getLogger(__name__)

# 单次请求的默认超时（秒）与重试次数
DEFAULT_TIMEOUT = 60.0
DEFAULT_RETRIES = 2
# 文件名中需要替换成下划线的非法字符（Windows 文件名限制 + 路径穿越）
_UNSAFE_CHARS = re.compile(r'[\\/:*?"<>|\s]+')


class DownloadError(Exception):
    """产物下载失败（重试耗尽 / HTTP 错误 / 磁盘写入失败）。"""


def safe_filename(name: str) -> str:
    """把 URL 或服务端返回的文件名清洗成安全的本地文件名。

    规则：非法字符（\\ / : * ? " < > | 空白）替换为下划线；
    去掉开头的路径穿越点；空结果回退为 "download"。

    参数：name: 原始文件名或 URL 末段。
    返回：安全的文件名（不含目录）。
    """
    cleaned = _UNSAFE_CHARS.sub("_", (name or "").strip()).lstrip(".")
    return cleaned or "download"


def filename_from_url(url: str) -> str:
    """从 URL 提取文件名（取路径末段并清洗）；失败回退时间戳风格名。"""
    tail = url.rstrip("/").rsplit("/", 1)[-1].split("?")[0]
    return safe_filename(tail)


def download_url(url: str, dest_dir: str | Path, filename: str | None = None,
                 retries: int = DEFAULT_RETRIES,
                 timeout: float = DEFAULT_TIMEOUT) -> Path:
    """把 url 内容下载到 dest_dir/filename，返回落盘后的完整路径。

    带 retries 次重试（指数退避 2s、4s…），全部失败抛 DownloadError。
    调用方（脚本或 runner）应在拿到产物 URL 后第一时间调用，
    避免链接 24h 过期后产物无法找回。

    参数：
        url: 产物下载地址（http/https）。
        dest_dir: 目标目录（不存在自动创建）。
        filename: 目标文件名；None 时从 URL 推断。
        retries: 失败重试次数（不含首次）。
        timeout: 单次请求超时秒数。

    返回：落盘文件 Path。
    """
    name = safe_filename(filename) if filename else filename_from_url(url)
    dest = Path(dest_dir) / name
    dest.parent.mkdir(parents=True, exist_ok=True)

    last_exc: Exception | None = None
    for attempt in range(retries + 1):
        try:
            req = urllib.request.Request(
                url, headers={"User-Agent": "AICreativeStudio/0.1"})
            with urllib.request.urlopen(req, timeout=timeout) as resp, \
                    open(dest, "wb") as f:
                f.write(resp.read())
            logger.info("产物下载成功：%s（%.1f KB）",
                        dest.name, dest.stat().st_size / 1024)
            return dest
        except Exception as exc:   # noqa: BLE001（统一换重试）
            last_exc = exc
            logger.warning("产物下载失败（第 %d 次）：%s",
                           attempt + 1, exc)
            # 清掉写了一半的残留文件
            if dest.exists():
                try:
                    dest.unlink()
                except OSError:
                    pass
            if attempt < retries:
                time.sleep(2 ** (attempt + 1))   # 指数退避：2s、4s…
    raise DownloadError(f"下载失败（已重试 {retries} 次）：{url}") from last_exc
