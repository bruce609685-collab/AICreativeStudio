"""运行日志初始化：exe 同级 logs/ 目录，单文件 ≤1MB 自动轮转。

"日志"是程序运行的流水账：什么时候启动、加载了几个脚本、出了什么错，
都会按时间顺序记录下来，是排查问题的第一手材料。本文件负责在程序
启动前把日志系统配置好——写到哪里、格式是什么、文件多大要换新。

约定（长期交付规范）：日志文件大小不超过 1MB，超出轮转，不无限增长。
"""

import logging
from logging.handlers import RotatingFileHandler

from app import paths

# 日志行的格式：时间 [级别] 模块名: 内容，例如
# "2026-08-28 10:00:00 [INFO] app.application: main window shown"
LOG_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
LOG_DATEFMT = "%Y-%m-%d %H:%M:%S"
MAX_BYTES = 1024 * 1024          # 1MB 硬上限
BACKUP_COUNT = 2                 # 保留 AICreativeStudio.log.1 / .2
FILE_LEVEL = logging.DEBUG       # 文件里记最详细的 DEBUG 级别（排查用）
CONSOLE_LEVEL = logging.INFO     # 控制台只显示 INFO 及以上（避免刷屏）

# 模块级"已初始化"标记：防止 setup_logging 被调用多次导致日志重复输出
_initialized = False


def setup_logging() -> None:
    """初始化根日志器（幂等，重复调用只生效一次）。

    "根日志器"是所有日志的源头：给它配好处理器后，程序里任何模块
    用 logging.getLogger(__name__) 记的日志都会汇到这里统一输出。
    "幂等"指无论调用几次，效果都和调用一次相同。
    """
    global _initialized
    if _initialized:
        return

    # 日志目录可能还不存在，先确保它建好
    paths.ensure_dirs()

    root = logging.getLogger()
    root.setLevel(logging.DEBUG)  # 根级别放开到 DEBUG，具体收窄由各 handler 控制

    # 文件处理器：写入 logs/，超过 1MB 自动轮转（旧文件改名 .log.1/.log.2），
    # 最多保留 2 个备份，日志总量因此有上限、不会撑爆磁盘
    file_handler = RotatingFileHandler(
        paths.LOG_FILE,
        maxBytes=MAX_BYTES,
        backupCount=BACKUP_COUNT,
        encoding="utf-8",
    )
    file_handler.setLevel(FILE_LEVEL)
    file_handler.setFormatter(logging.Formatter(LOG_FORMAT, LOG_DATEFMT))

    # 控制台处理器：开发调试时在终端直接看输出，只显示较重要的信息
    console_handler = logging.StreamHandler()
    console_handler.setLevel(CONSOLE_LEVEL)
    console_handler.setFormatter(logging.Formatter(LOG_FORMAT, LOG_DATEFMT))

    root.addHandler(file_handler)
    root.addHandler(console_handler)

    # 模块级 logger 名 = 包路径，日志天然带模块定位信息（调试用）
    logging.getLogger(__name__).debug("logging initialized -> %s", paths.LOG_FILE)
    _initialized = True
