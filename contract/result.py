"""出参 JSON 的解析与错误码（契约层，headless）。

制式脚本跑完之后，需要"汇报结果"给外壳（本程序）。约定方式是：
脚本运行结束向 stdout（标准输出）打印一行 JSON：
  {"status": "ok", "files": ["C:/.../image/xxx_1.png"], "elapsed": 12.3}
  {"status": "error", "code": "AUTH_FAILED", "message": "API KEY 无效"}
外壳只解析 stdout 最后一行；脚本的日志一律走 stderr（标准错误）。
这样"结果"和"日志"两条通道互不干扰，外壳能可靠地拿到结果。

本文件定义了统一的错误码常量，并负责校验/解析脚本输出的结果行。
"""

from __future__ import annotations

import json

# ---- 错误码全集（脚本按需使用，外壳按 code 提示用户） ----
# 外壳看到 code 后能给出友好的中文提示，而不是显示一堆原始报错
ERR_AUTH_FAILED = "AUTH_FAILED"      # KEY 缺失 / 无效
ERR_INVALID_PARAMS = "INVALID_PARAMS"  # 入参不合法（脚本侧校验失败）
ERR_API_ERROR = "API_ERROR"          # 上游 API 返回错误（message 透传上游原文）
ERR_NETWORK = "NETWORK"              # 网络不可达 / 超时 / DNS 失败
ERR_BLOCKED = "BLOCKED"              # 内容策略拦截（block_reason）
ERR_INTERNAL = "INTERNAL"            # 脚本自身异常
ERR_TIMEOUT = "TIMEOUT"              # 外壳侧超时终止（非脚本输出）


class ResultError(ValueError):
    """结果行缺失 / 非 JSON / 缺 status / files 类型错误。

    当脚本输出的"结果行"不符合约定格式时抛出，外壳据此判定
    这次任务没有可信的结果。
    """


def parse_result_line(line: str) -> dict:
    """解析脚本 stdout 的最后一行结果 JSON，非法时抛 ResultError。

    参数 line：从 stdout 抓到的最后一行文本（可能为 None 或空串）。
    返回值：解析出的结果字典，形如
    {"status": "ok", "files": [...]} 或 {"status": "error", ...}。
    异常：行缺失、不是合法 JSON、不是 JSON 对象、缺 status、
    ok 结果的 files 不是合法字符串列表时，均抛 ResultError。
    """
    # or ""：允许调用方直接把 None 传进来而不崩
    line = (line or "").strip()
    if not line:
        raise ResultError("脚本未输出结果 JSON（stdout 为空）")
    try:
        data = json.loads(line)
    except json.JSONDecodeError:
        raise ResultError("脚本输出不是合法 JSON") from None
    if not isinstance(data, dict):
        raise ResultError("结果必须是 JSON 对象")
    status = data.get("status")
    if status not in ("ok", "error"):
        raise ResultError("结果缺少 status 字段（必须是 ok / error）")
    if status == "ok":
        # 成功时必须给出文件列表；逐项校验"每一项都是非空字符串"，
        # 防止 None、数字或空串混进文件路径里
        files = data.get("files") or []
        if not isinstance(files, list) or not all(
            isinstance(f, str) and f.strip() for f in files
        ):
            raise ResultError("ok 结果的 files 字段必须是字符串列表")
    return data
