"""入参 JSON 的键名与组装（契约层，headless）。

外壳（本程序界面）调用制式脚本时，不是直接传一大堆命令行参数，
而是把所有参数组装成一个 JSON 文件（job.json），通过一条命令传给脚本：
python script.py --params <job.json>

本文件定义了 job.json 里允许出现的键名（如 prompt、ratio 等），
以及生成该文件的工具函数。脚本只读自己需要的键，未知键忽略。
键名即契约，改动必须同步更新《脚本契约规范-v1.0.0.md》。
"""

from __future__ import annotations

import json
from pathlib import Path

# ---- 入参键名常量（脚本与外壳共认，改动=契约变更） ----
# 代码中不直接写字符串，而是引用这些常量，可以避免手滑拼错键名
K_PROMPT = "prompt"              # 主提示词（必填）
K_PROMPT_NEG = "negative_prompt"  # 负向提示词（可选）
K_RATIO = "ratio"                # 画面比例，如 1:1 / 16:9
K_RESOLUTION = "resolution"      # 分辨率档位，如 1k / 2K
K_QUALITY = "quality"            # 质量档位，如 standard / high
K_FORMAT = "format"              # 输出格式，如 png / jpeg
K_SEED = "seed"                  # 随机种子，-1 = 随机
K_BATCH = "batch"                # 生成数量 1–9
K_OUTPUT_DIR = "output_dir"      # 产物目录（绝对路径）
K_REF_IMAGE = "ref_image"        # 参考图路径（i2i / i2v / 音色克隆）
K_STREAM = "stream"              # 流式输出（bool）
K_WEB_SEARCH = "web_search"      # 联网搜索（bool）
K_SOUND = "sound"                # 视频是否生成声音（bool）
K_VOICE = "voice"                # 预置音色（语音类）
K_STYLE = "style"                # 风格指令 / 音色设计描述（语音类）
K_DURATION = "duration"          # 视频时长档位（如 5 / 10 秒）
K_MODE = "mode"                  # 生成模式档位（如 std / pro）
K_TASK_ID = "task_id"            # 异步任务断点续查（视频类）
K_MOCK = "mock"                  # 演示模式：不调真实 API，产出占位产物
K_TIMEOUT = "timeout"            # 外壳允许的脚本执行总超时（秒），脚本应据此设 API 调用超时

# 命令行参数名（脚本统一 argparse 入口）
ARG_PARAMS = "--params"


def write_params_file(path: Path | str, **values) -> Path:
    """把参数字典写为 job.json 并返回路径（幂等，覆盖写）。

    参数 path：目标文件路径（字符串或 Path 对象均可）。
    参数 values：任意多个关键字参数，即要写入的键值对，
    例如 write_params_file(p, prompt="一只猫", ratio="1:1")。
    返回值：实际写入的文件路径（Path 对象）。
    说明："幂等，覆盖写"指重复调用同一组参数会得到完全相同的结果，
    已存在的旧文件会被直接覆盖，不追加。
    """
    path = Path(path)
    # 先确保父目录存在：parents=True 表示连同上级目录一并创建，
    # exist_ok=True 表示目录已存在时不报错
    path.parent.mkdir(parents=True, exist_ok=True)
    # ensure_ascii=False 允许中文原样写入（而不是转成 \u 转义）；
    # default=str 遇到无法直接序列化的对象（如 Path）时退化为字符串，避免报错
    path.write_text(
        json.dumps(values, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    return path
