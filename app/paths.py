"""路径常量集中管理（全项目唯一入口）。

程序要读写很多文件：脚本目录、模板、数据库、日志、生成结果……
所有这些路径都只在本文件定义一次，其他模块统一从这里取。
好处是：想调整某个目录的位置，只改这一个文件即可。

开发期：以源码根目录为 BASE_DIR；
打包后（PyInstaller onedir）：以 exe 所在目录为 BASE_DIR。
只读资源（scripts/templates）兼容 _internal/ 布局（PyInstaller 6.x）。
"文件找不到"类问题第一嫌疑人就是这里。
"""

import sys
from pathlib import Path


def _resolve_base_dir() -> Path:
    """开发期取源码根；PyInstaller 打包后取 exe 所在目录。

    返回值：程序"根目录"的 Path。
    原理：sys.frozen 是 PyInstaller 打包后才会注入的标记（值为 True），
    借此判断当前是"源码运行"还是"打包后的 exe 运行"。
    """
    if getattr(sys, "frozen", False):          # PyInstaller 环境为 True
        # sys.executable 是 exe 自身路径，取其父目录即 exe 所在目录
        return Path(sys.executable).resolve().parent
    # 源码运行：本文件位于 app/ 下，往上两级就是源码根目录
    return Path(__file__).resolve().parent.parent


def _resolve_resource_dir() -> Path:
    """只读资源（scripts/templates）所在目录。

    PyInstaller 6.x onedir 把数据收集进 _internal/，开发期即源码根。
    两个位置都兼容：exe 旁优先（用户可扩展），否则 _internal。

    返回值：资源根目录的 Path。
    """
    if getattr(sys, "frozen", False):
        # 打包后优先检查 exe 旁有没有 scripts 目录——放这里的资源
        # 用户可以直接增删替换，比藏在 _internal 里更友好
        cand = _resolve_base_dir() / "_internal"
        if (cand / "scripts").is_dir():
            return cand
    return _resolve_base_dir()


# 模块加载时（import 本文件的那一刻）就解析好两个根目录，
# 之后所有路径常量都基于它们拼出来
BASE_DIR = _resolve_base_dir()
RESOURCE_DIR = _resolve_resource_dir()

# 目录
SCRIPTS_DIR = RESOURCE_DIR / "scripts"
IMAGE_SCRIPTS_DIR = SCRIPTS_DIR / "image_scripts"
VIDEO_SCRIPTS_DIR = SCRIPTS_DIR / "video_scripts"
AUDIO_SCRIPTS_DIR = SCRIPTS_DIR / "audio_scripts"
TEMPLATES_DIR = RESOURCE_DIR / "templates"
DATA_DIR = BASE_DIR / "data"
LOGS_DIR = BASE_DIR / "logs"

# 文件
CONFIG_FILE = DATA_DIR / "config.json"
HISTORY_DB = DATA_DIR / "history.db"
JOBS_DIR = DATA_DIR / "jobs"   # 生成任务的 job.json（外壳 → 脚本传参）
LOG_FILE = LOGS_DIR / "AICreativeStudio.log"

# 产物目录（生成结果的落盘位置，与 scripts/ 平级）
OUTPUT_IMAGE_DIR = BASE_DIR / "image"
OUTPUT_VIDEO_DIR = BASE_DIR / "video"
OUTPUT_AUDIO_DIR = BASE_DIR / "voice"


def ensure_dirs() -> None:
    """启动时确保运行期目录存在（幂等，可反复调用）。

    逐个创建上面定义的关键目录；parents=True 连同缺失的上级目录一起建，
    exist_ok=True 已存在时不报错，所以无论调用多少次都安全。
    """
    for d in (
        SCRIPTS_DIR, IMAGE_SCRIPTS_DIR, VIDEO_SCRIPTS_DIR, AUDIO_SCRIPTS_DIR,
        TEMPLATES_DIR, DATA_DIR, JOBS_DIR, LOGS_DIR,
        OUTPUT_IMAGE_DIR, OUTPUT_VIDEO_DIR, OUTPUT_AUDIO_DIR,
    ):
        d.mkdir(parents=True, exist_ok=True)
