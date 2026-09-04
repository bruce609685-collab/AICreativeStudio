"""脚本执行域：参数组装 + 子进程执行 + 结果解析。

用户在界面上点"开始生成"后，真正干活的就是这个包：
- params.py：把界面上选的参数（提示词、分辨率、比例、张数等）
  组装成一份 job.json 参数字典，键名遵循项目契约（contract 包），
  各种非法输入（非数字、超范围、负数种子）都在这里清洗掉；
- runner.py：启动一个**隔离的子进程**去执行脚本（而不是在主程序
  里直接跑），脚本崩溃、卡死、输出乱码都不会影响主程序；执行完
  解析脚本打印的结果行，得到"生成了哪些文件、耗时多久"。

对外暴露 build_*_params 三个参数组装函数和 run_script 执行函数。
"""

from core.runner.params import (
    build_audio_params,
    build_image_params,
    build_video_params,
    write_job_file,
)
from core.runner.runner import RunResult, run_script

__all__ = [
    "RunResult",
    "build_audio_params",
    "build_image_params",
    "build_video_params",
    "run_script",
    "write_job_file",
]
