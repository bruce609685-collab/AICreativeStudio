"""FFmpeg / pip 依赖检测与一键安装。M6 实现。

很多脚本运行前需要两样外部依赖：
1. Python 第三方包（pip 包）——脚本在 META 里用 "pip_requires" 字段声明，
   本模块负责扫描哪些包还没装、并调用 pip 一键安装；
2. FFmpeg——一个命令行的音视频处理工具，图片转视频等脚本离不开它。
   本模块会把官方预编译好的 zip 包下载下来、解压到项目的 data/ffmpeg/
   目录（含 ffmpeg 和 ffplay 两个程序），让用户不用自己去官网配置。

在整体架构中的角色：注册表（registry）解析出脚本依赖后，界面层的
"依赖检查"页面会调用本模块列出缺失项并安装；FFmpeg 可用性则直接决定
部分脚本能否运行。本模块不依赖界面，可独立测试。

职责：扫描脚本"pip_requires"字段列出缺失包；
FFmpeg 程序内下载安装（含 ffplay）——下载预编译 zip 包解压到 data/ffmpeg/ 目录。
"""

import importlib
import logging
import os
import shutil
import subprocess
import sys
import urllib.request
import zipfile
from pathlib import Path

from contract.fields import normalize_pip_requires

logger = logging.getLogger(__name__)

# 路径常量（内联，避免触发 app/__init__.py 的循环导入）
_BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = _BASE_DIR / "data"
FFMPEG_DIR = DATA_DIR / "ffmpeg"
FFMPEG_ZIP = DATA_DIR / "ffmpeg.zip"

# FFmpeg 下载地址（BtbN 预编译 Windows 64 位 GPL 版）
# 主源 GitHub + 备用国内镜像（§10.7：国内网络优先可达源）
FFMPEG_DOWNLOAD_URLS = [
    # 国内镜像（优先）：阿里云 CDN 代理的 GitHub 发布物
    "https://mirrors.aliyun.com/ffmpeg-builds/"
    "ffmpeg-master-latest-win64-gpl.zip",
    # 主源：GitHub Releases
    "https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/"
    "ffmpeg-master-latest-win64-gpl.zip",
]
# 兼容旧名（部分测试/调用引用）
FFMPEG_DOWNLOAD_URL = FFMPEG_DOWNLOAD_URLS[-1]

# pip 国内镜像（清华 PyPI，需求 §10.7"下载一律走国内镜像"）
PIP_MIRROR_ARGS = ["-i", "https://pypi.tuna.tsinghua.edu.cn/simple"]


def _check_pip_installed(pkg: str) -> bool:
    """检查某个 pip 包是否已安装（按包分发包名查，不依赖导入名）。

    两步走：
    1. 首选 importlib.metadata 按包分发名（如 "pillow"）查询——这是 pip
       官方记录的名字，最准确；
    2. 兜底再尝试直接 import 对应模块（横线转下划线），防止某些包
       分发名和导入名不一致导致误判。

    Args:
        pkg: 包名（如 "pillow"）。

    Returns:
        已安装返回 True，否则 False。
    """
    try:
        import importlib.metadata as md
        md.distribution(pkg.strip().lower())
        return True
    except (importlib.metadata.PackageNotFoundError, AttributeError):
        pass
    # 兜底：尝试 importlib 导入
    try:
        importlib.import_module(pkg.strip().lower().replace("-", "_"))
        return True
    except ImportError:
        pass
    return False


def list_missing(scripts_pip_requires: list[str]) -> list[str]:
    """扫描脚本依赖列表，返回缺失的包名。

    Args:
        scripts_pip_requires: 所有脚本的 pip_requires 合并去重列表。

    Returns:
        缺失的包名列表（已去重，按字母序）。
    """
    seen: set[str] = set()
    missing: list[str] = []
    # 入口再洗一遍：兼容未经过契约层清洗的调用方（如外部直接
    # 构造 ScriptMeta），确保 none 这类占位词不会进界面变成可点假包
    for pkg in normalize_pip_requires(scripts_pip_requires):
        if pkg in seen:
            continue
        seen.add(pkg)
        if not _check_pip_installed(pkg):
            missing.append(pkg)
    return sorted(missing)


def _resolve_python() -> str | None:
    """找一个真正带 pip 模块的 Python 解释器。

    开发态直接用当前解释器；PyInstaller 打包后 sys.executable 是主程序 exe，
    里面没有 pip 模块，`exe -m pip` 必失败——此时退而在系统 PATH 里找
    python / py 启动器。找不到返回 None，由调用方给出友好提示。
    """
    if not getattr(sys, "frozen", False):
        return sys.executable
    for cand in ("python", "python3", "py"):
        found = shutil.which(cand)
        if found:
            return found
    return None


def install_pip(package: str) -> bool:
    """用捆绑 Python 执行 pip 安装指定包。

    Args:
        package: 包名（如 "pillow"）。

    Returns:
        安装成功返回 True。
    """
    # 防御：只有合法且非占位的包名才允许进 pip，避免拼错或占位词
    # 被真的执行成 pip install（pip install none 会装到无关包或报错）
    if not normalize_pip_requires([package]):
        logger.warning("拒绝安装非法 pip 包名：%r", package)
        return False
    package = package.strip().lower()
    python_exe = _resolve_python()
    if python_exe is None:
        logger.warning("pip install %s 失败：打包环境内无可用 Python/pip，"
                "请在系统安装 Python 3 后重试", package)
        return False
    try:
        # 走清华镜像安装（§10.7），下载更快更稳
        result = subprocess.run(
            [python_exe, "-m", "pip", "install", package,
             *PIP_MIRROR_ARGS],
            capture_output=True, text=True, timeout=120.0,
        )
        if result.returncode == 0:
            logger.info("pip install %s 成功", package)
            return True
        logger.warning("pip install %s 失败：%s", package, result.stderr.strip())
        return False
    except subprocess.TimeoutExpired:
        logger.warning("pip install %s 超时", package)
        return False
    except OSError as exc:
        logger.error("pip install %s 异常：%s", package, exc)
        return False


def check_ffmpeg() -> bool:
    """检测 FFmpeg 是否可用。

    查找顺序：
    1. 系统 PATH
    2. data/ffmpeg/ 目录（递归搜索 ffmpeg.exe）

    Returns:
        True 表示可用。
    """
    # 1. PATH 检查
    if shutil.which("ffmpeg") is not None:
        return True
    # 2. data/ffmpeg/ 目录
    if FFMPEG_DIR.is_dir():
        for exe in FFMPEG_DIR.rglob("ffmpeg.exe"):
            if exe.is_file():
                # PATH 在 Windows 上恒存在，setdefault 永远不会写入；
                # 必须显式前置追加，后续 shutil.which / subprocess 才能找到
                os.environ["PATH"] = os.pathsep.join(
                    [str(exe.parent), os.environ.get("PATH", "")])
                return True
    return False


def _progress_hook_default(current: int, total: int) -> None:
    """默认进度回调（无操作）。"""
    pass


def download_ffmpeg(progress_cb=None) -> bool:
    """下载 FFmpeg 预编译包并解压到 data/ffmpeg/。

    Args:
        progress_cb: 可选回调，签名 (current_bytes, total_bytes)。

    Returns:
        下载+解压成功返回 True。
    """
    if progress_cb is None:
        progress_cb = _progress_hook_default

    # 清理旧文件
    if FFMPEG_ZIP.exists():
        FFMPEG_ZIP.unlink()
    if FFMPEG_DIR.exists():
        shutil.rmtree(FFMPEG_DIR)

    class _Reporter:
        """下载进度上报器。

        urllib 的 urlretrieve 每收到一块数据就调用一次 __call__，
        其中 count 是**累计**块数（不是本次增量），所以已下载字节数
        = count × block_size 直接赋值即可，不能再累加（否则进度会
        呈平方增长、瞬间超过 100%）。
        """

        def __init__(self, cb):
            self._cb = cb

        def __call__(self, count, block_size, total_size):
            downloaded = count * block_size
            if total_size and total_size > 0:
                downloaded = min(downloaded, total_size)
            self._cb(downloaded, total_size if total_size and total_size > 0 else 1)

    try:
        logger.info("开始下载 FFmpeg…")
        reporter = _Reporter(progress_cb)
        # 依次尝试多个下载源（国内镜像优先，全部失败才报错）
        last_exc: Exception | None = None
        for url in FFMPEG_DOWNLOAD_URLS:
            try:
                logger.info("下载源：%s", url)
                urllib.request.urlretrieve(url, str(FFMPEG_ZIP), reporter)
                last_exc = None
                break
            except Exception as exc:   # noqa: BLE001（换源重试）
                logger.warning("下载源失败（%s）：%s", url, exc)
                last_exc = exc
        if last_exc is not None:
            raise last_exc
        logger.info("下载完成，文件大小：%d 字节", FFMPEG_ZIP.stat().st_size)
    except Exception as exc:
        logger.error("FFmpeg 下载失败：%s", exc)
        # 清理残留
        if FFMPEG_ZIP.exists():
            FFMPEG_ZIP.unlink()
        return False

    # 解压——zip 内第一层目录名不确定，直接解压到 FFMPEG_DIR
    try:
        FFMPEG_DIR.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(str(FFMPEG_ZIP), "r") as zf:
            # 拿第一个目录名作为顶层目录
            top = None
            for name in zf.namelist():
                parts = name.replace("\\", "/").split("/")
                if parts[0] and top is None:
                    top = parts[0]
                if not name.endswith("/"):
                    zf.extract(name, str(FFMPEG_DIR))
        # 把顶层目录里的内容提到 FFMPEG_DIR 根
        if top:
            top_dir = FFMPEG_DIR / top
            if top_dir.is_dir():
                for item in top_dir.iterdir():
                    dest = FFMPEG_DIR / item.name
                    if dest.exists():
                        if dest.is_dir():
                            shutil.rmtree(dest)
                        else:
                            dest.unlink()
                    shutil.move(str(item), str(dest))
                shutil.rmtree(top_dir)
        FFMPEG_ZIP.unlink()
        logger.info("FFmpeg 解压完成：%s", FFMPEG_DIR)
        return check_ffmpeg()
    except Exception as exc:
        logger.error("FFmpeg 解压失败：%s", exc)
        if FFMPEG_ZIP.exists():
            FFMPEG_ZIP.unlink()
        return False