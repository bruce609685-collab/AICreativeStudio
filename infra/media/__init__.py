"""媒体：产物 URL 下载落盘（处理 24h 时效）、缩略图生成。

media（媒体）子包负责与"生成出来的媒体文件"相关的杂务：
- 下载：部分 AI 服务只返回一个临时下载链接，且通常 24 小时内失效，
  所以必须及时把文件下载到本地保存，否则链接过期就无法找回
  （见 downloader.download_url）；
- 缩略图：历史记录列表里展示小图，避免加载原始大图拖慢界面
  （缩略图渲染由 ui/widgets/history_bar.py 用 QPixmap 直接完成，
  无需额外生成缓存文件）。

公共出口：download_url / DownloadError / safe_filename。
"""

from .downloader import DownloadError, download_url, safe_filename

__all__ = ["DownloadError", "download_url", "safe_filename"]
