"""LLM 客户端（headless）：OpenAI 兼容 chat/completions + Mock 演示模式。

本模块是"智能导入"功能里负责和 AI 大模型对话的那一环：把 API 文档
和生成要求发给 LLM，拿回它写好的脚本代码。兼容所有 OpenAI 格式的
接口（包括各种国内中转站），默认走 SSE 流式接收——这样界面可以
像"打字机"一样实时显示 LLM 的输出，用户不用干等。

真实模式：POST {api_url}，Bearer 鉴权，返回 assistant 内容；
Mock 模式：不联网，返回一份预设的演示脚本 JSON（用于演示/测试）。

连接失败时提供可操作的分类提示（DNS/拒绝/超时/SSL），
并支持 URL 智能补全（base 地址自动补 /chat/completions）。

对外主要入口：call_llm（正式调用）、test_llm_connection（设置页
"测试连接"按钮）、mock_generate_scripts（演示模式）、LLMConfig
（配置对象，由 config.py 负责存取）。pipeline.py 调用本模块完成生成。
"""

from __future__ import annotations

import json
import logging
import socket
import ssl
import urllib.error
import urllib.request
from dataclasses import dataclass
from urllib.parse import urlparse

logger = logging.getLogger(__name__)


@dataclass
class LLMConfig:
    """LLM 连接配置。

    代表用户在"模型设置"页面填写的全部信息，dataclass 自动生成
    __init__，可以 LLMConfig(api_url=..., api_key=...) 直接构造。

    关键属性：
    - api_url: OpenAI 兼容接口地址（会经 normalize_api_url 补全路径）；
    - api_key: 鉴权密钥，以 Bearer 方式放进请求头；
    - model: 模型名（如 gpt-4o），写进请求体的 "model" 字段；
    - mock: True 表示演示模式——不联网，直接返回内置演示脚本。

    使用场景：由 config.py 从 data/config.json 读入/写出，
    在 call_llm / test_llm_connection 中作为请求参数。
    """

    api_url: str = ""   # OpenAI 兼容接口地址，由用户在导入页填写
    api_key: str = ""   # 鉴权密钥，不内置、不预填
    model: str = ""     # 模型名，由用户在导入页填写
    mock: bool = False          # 演示模式：不走真实 LLM


# ----------------------------------------------------------------------
# URL 智能补全
# ----------------------------------------------------------------------

def normalize_api_url(raw: str) -> str:
    """把用户填的地址规整为可用的 OpenAI 兼容 chat/completions 地址。

    规则（尽量保守，不猜用户的自定义路径）：
    1. 去首尾空白；
    2. 缺协议补 https://；
    3. 纯主机（无路径）或以 /v1、/v1beta、/api 结尾（典型 base）→ 补 /chat/completions；
    4. 已是完整 /chat/completions 或含其他路径 → 原样返回。
    """
    url = (raw or "").strip()
    if not url:
        return url
    if "://" not in url:
        url = "https://" + url
    base = url.rstrip("/")
    if base.endswith("/chat/completions"):
        return url
    path = urlparse(url).path.rstrip("/")
    if not path or path in ("/v1", "/v1beta", "/api", "/api/v1"):
        return base + "/chat/completions"
    return url


def describe_api_url(url: str) -> str:
    """对地址做基本诊断（协议/主机/路径），供「测试连接」展示。

    Args:
        url: API 地址。

    Returns:
        形如 "HTTPS · api.example.com/v1/chat/completions" 的一行摘要；
        地址无法解析时返回提示文字。
    """
    try:
        parts = urlparse(url)
    except ValueError:
        return "地址格式无法解析"
    scheme = (parts.scheme or "?").upper()
    host = parts.hostname or "?"
    path = parts.path or "/"
    return f"{scheme} · {host}{path}"


# ----------------------------------------------------------------------
# 错误分类
# ----------------------------------------------------------------------

def classify_connection_error(exc, timeout: float | None = None) -> str:
    """把连接类异常翻译成可操作的中文提示。

    用户大多不是程序员，看到 "Errno 11001" 这类报错会一头雾水；
    本函数按异常类型（SSL/域名解析/拒绝连接/超时/其他网络错误）
    翻译成人话，并附上"接下来该做什么"的建议。

    Args:
        exc: 捕获到的异常对象。
        timeout: 当超时发生时，用于显示"已等待多少秒"。

    Returns:
        一段面向用户的中文提示文本。
    """
    if isinstance(exc, ssl.SSLCertVerificationError):
        return "SSL 证书校验失败——地址可能是自签名/过期证书，或域名与证书不匹配。"
    if isinstance(exc, ssl.SSLError):
        msg = str(exc)
        if "UNEXPECTED_EOF" in msg or "RESET" in msg.upper() or "EOF" in msg:
            return ("服务器中断连接——域名可能不存在、服务未开放，"
                    "或网络被防火墙/代理拦截。请核对地址后重试。")
        return f"SSL 握手失败：{msg}。"
    if isinstance(exc, socket.gaierror):
        return ("域名解析失败——请检查「API 地址」是否拼写正确，"
                "或该域名当前无法访问。")
    if isinstance(exc, ConnectionRefusedError):
        return "连接被拒绝——请确认地址端口正确、服务已开启。"
    if isinstance(exc, TimeoutError):
        waited = f"已等待 {timeout:.0f} 秒" if timeout else "等待超时"
        return (f"接口响应超时（{waited}）——生成完整脚本内容较长时，"
                "模型可能需要 1-3 分钟，请直接重试；如频繁超时，"
                "请检查模型名是否有效或接口是否限流。"
                "若网络需要代理访问，请配置系统/环境代理后重试。")
    if isinstance(exc, (urllib.error.URLError, OSError)):
        reason = getattr(exc, "reason", None)
        if reason is not None and reason is not exc:
            return classify_connection_error(reason, timeout)
        return f"网络错误：{exc}。"
    return f"无法连接 LLM：{exc}。"


# ----------------------------------------------------------------------
# 探测 / 调用
# ----------------------------------------------------------------------

def test_llm_connection(cfg: LLMConfig, timeout: float = 12.0) -> tuple[bool, str]:
    """发一个最小请求探测 LLM 连通性（不依赖完整导入流程）。

    做法：发一条只要求回复 1 个 token 的 "ping" 消息，省时省费用。
    设置页的「测试连接」按钮调用本函数，让用户填完配置先验一下
    再去跑导入。

    Args:
        cfg: LLM 连接配置。
        timeout: 超时秒数（探测不需要太久，默认 12 秒）。

    Returns:
        (ok, message)：ok=True 表示接口可连通（鉴权是否有效也一并反馈），
        message 是可直接展示给用户的中文结果说明。
    """
    url = normalize_api_url(cfg.api_url)
    if not url:
        return False, "「API 地址」为空，请填写。"
    body = {
        "model": cfg.model,
        "messages": [{"role": "user", "content": "ping"}],
        "max_tokens": 1,
    }
    req = urllib.request.Request(
        url,
        data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        headers={"Authorization": f"Bearer {cfg.api_key}",
                 "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8", errors="replace"))
        content = (data.get("choices") or [{}])[0].get("message", {}).get("content")
        if content is not None:
            return True, "✅ 连接成功，接口响应正常（模型可用）。"
        return True, "✅ 连接成功（HTTP 200），但响应缺少 choices，模型名可能需要调整。"
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")[:160]
        if exc.code in (401, 403):
            return False, f"❌ 鉴权失败（HTTP {exc.code}）——API 密钥错误或已失效。{raw}"
        if exc.code in (404, 405):
            return False, (f"❌ 接口路径错误（HTTP {exc.code}）——地址疑似缺少 "
                           f"「/chat/completions」路径。{raw}")
        return False, f"❌ 接口返回 HTTP {exc.code}：{raw}"
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        return False, "❌ " + classify_connection_error(exc, timeout)


def _build_request(url: str, cfg: LLMConfig, system: str, user: str,
                   stream: bool):
    """构造 OpenAI 兼容请求。

    Args:
        url: 完整的 chat/completions 接口地址。
        cfg: LLM 配置（模型名、KEY 从这里取）。
        system: 系统提示词（告诉 LLM 它的角色和输出规范）。
        user: 用户提示词（这里是 API 文档 + 生成要求）。
        stream: 是否请求 SSE 流式响应。

    Returns:
        配好请求头和请求体的 urllib Request 对象。
    """
    body = {
        "model": cfg.model,
        # messages 是 OpenAI 格式的对话历史：system 定规则，user 给材料
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        # 温度调低（0.2）：生成代码要稳定、少发挥
        "temperature": 0.2,
    }
    if stream:
        body["stream"] = True
    headers = {
        "Authorization": f"Bearer {cfg.api_key}",
        "Content-Type": "application/json",
    }
    if stream:
        # 流式请求要声明接收 text/event-stream（SSE）格式
        headers["Accept"] = "text/event-stream"
    return urllib.request.Request(
        url,
        data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        headers=headers,
        method="POST",
    )


def _extract_content(data, on_chunk) -> str:
    """从非流式 JSON 响应取 content；取到即整段回调 on_chunk。

    Args:
        data: 接口返回的 JSON（dict）。
        on_chunk: 可选回调，函数签名 on_chunk(text)。

    Returns:
        assistant 回复的完整文本。

    Raises:
        RuntimeError: 响应里找不到 choices[0].message.content 时抛出，
        常见于模型名写错或接口返回结构不标准。
    """
    try:
        content = str(data["choices"][0]["message"]["content"])
    except (KeyError, IndexError, TypeError):
        raise RuntimeError(f"LLM 响应格式异常：{str(data)[:200]}") from None
    if on_chunk is not None and content:
        on_chunk(content)
    return content


def _read_sse(resp, on_chunk) -> str:
    """解析 SSE 流（data: {...} 行，[DONE] 结束），逐块回调 on_chunk。

    SSE（Server-Sent Events）是流式输出的标准格式：服务器不断发来
    形如 "data: {json片段}" 的文本行，每个 json 里的 delta.content
    是一小段新生成的文字；最后发一行 "data: [DONE]" 表示结束。
    本函数逐行拆包，把每段新文字通过 on_chunk 回调交给界面实时显示，
    同时累积成完整文本返回。

    Args:
        resp: urlopen 返回的响应对象（可逐行迭代）。
        on_chunk: 可选回调 on_chunk(delta_text)，每个增量块触发一次。

    Returns:
        拼接后的完整文本。

    注意：网络分包可能导致一行 JSON 被切成两半，所以用 buf 缓冲、
    凑够换行符才解析；个别行解析失败只跳过该行，不中断整个流。
    """
    chunks: list[str] = []
    buf = ""
    done = False
    for raw in resp:
        if done:
            break
        # 累积字节并解码；凑到换行符才切行，防止 JSON 被拦腰截断
        buf += raw.decode("utf-8", errors="replace")
        while "\n" in buf and not done:
            line, buf = buf.split("\n", 1)
            line = line.strip()
            # 只关心 "data:" 开头的行；SSE 里还有注释行/空行/事件名行
            if not line.startswith("data:"):
                continue
            payload = line[5:].strip()
            if payload == "[DONE]":
                done = True
                break
            try:
                obj = json.loads(payload)
                # 流式增量放在 choices[0].delta.content（非流式才是 message）
                delta = (obj.get("choices") or [{}])[0] \
                    .get("delta", {}).get("content")
            except (json.JSONDecodeError, IndexError, TypeError, AttributeError):
                delta = None
            if delta:
                chunks.append(delta)
                if on_chunk is not None:
                    on_chunk(delta)
    return "".join(chunks)


def call_llm(cfg: LLMConfig, system: str, user: str,
             timeout: float = 120.0, on_chunk=None, stream: bool = True) -> str:
    """调用 OpenAI 兼容接口，返回 assistant 全文；异常抛 RuntimeError。

    这是本模块的主入口：组装请求 → 发送 → 流式/非流式解析 → 返回全文。
    stream=True 时以 SSE 流式接收，每个增量块回调 on_chunk(text)——
    界面可实时显示 LLM 输出。

    两类自动降级（都只重试一次，避免死循环）：
    1. 流式响应里拿不到内容：深度思考模型（如 xx-reasoner）流式时
       delta.content 全是空的，真正的答案只在非流式的 message.content
       里 → 改用非流式重新请求；
    2. 流式请求被服务端拒绝（HTTP 400/422）：有的接口不支持 stream
       参数 → 改用非流式重新请求。

    Args:
        cfg: LLM 连接配置。
        system: 系统提示词；user: 用户提示词（API 文档 + 要求）。
        timeout: 超时秒数；生成完整脚本耗时较长（可能 1-3 分钟），
        导入管线请传 timeout=300。
        on_chunk: 流式增量回调 on_chunk(text)，可为 None。
        stream: 是否优先尝试流式。

    Returns:
        assistant 回复的完整文本。

    Raises:
        RuntimeError: 连接失败 / HTTP 错误 / 响应格式异常，
        错误信息已翻译为可操作的中文提示。
    """
    url = normalize_api_url(cfg.api_url)
    try:
        req = _build_request(url, cfg, system, user, stream)
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            ctype = resp.headers.get("Content-Type", "")
            if stream and "text/event-stream" in ctype:
                text = _read_sse(resp, on_chunk)
                # 深度思考模型（reasoner）流式时 delta.content 可能全空，
                # JSON 只在非流式的 message.content 里 → 降级非流式重试一次
                # （另外内容里没有 { 或 [ 也说明不像脚本 JSON，一并降级）
                if not text.strip() or ("{" not in text and "[" not in text):
                    logger.info(
                        "流式输出不含 JSON（可能为深度思考模型），降级非流式重试")
                    return call_llm(cfg, system, user, timeout=timeout,
                                    on_chunk=on_chunk, stream=False)
                return text
            data = json.loads(resp.read().decode("utf-8"))
            return _extract_content(data, on_chunk)
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        if stream and exc.code in (400, 422):
            # 服务端不支持 stream → 降级非流式重试一次
            logger.info("流式请求被拒（HTTP %s），降级非流式重试：%s",
                        exc.code, raw[:100])
            try:
                req2 = _build_request(url, cfg, system, user, stream=False)
                with urllib.request.urlopen(req2, timeout=timeout) as resp2:
                    data2 = json.loads(resp2.read().decode("utf-8"))
                return _extract_content(data2, on_chunk)
            except (urllib.error.URLError, TimeoutError, OSError) as exc2:
                raise RuntimeError(
                    classify_connection_error(exc2, timeout)) from None
        if exc.code in (404, 405):
            raise RuntimeError(
                f"接口路径错误（HTTP {exc.code}）——「API 地址」疑似缺少 "
                f"「/chat/completions」路径，已自动尝试补全；仍失败请检查地址。"
                f"{raw[:160]}") from None
        raise RuntimeError(f"LLM API 错误 HTTP {exc.code}：{raw[:200]}") from None
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise RuntimeError(classify_connection_error(exc, timeout)) from None
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"LLM 响应 JSON 解析失败：{exc}") from None


# ----------------------------------------------------------------------
# Mock：演示脚本（不联网，返回一份"文生图"骨架，可真实运行 mock 分支）
# ----------------------------------------------------------------------

_MOCK_CODE = '''"""演示 · 文生图（Mock 导入样例）——由 Mock LLM 生成。

模板版本：1.0.0
依赖：无（纯标准库）

# [ACS_META_START]
# display_name  = 演示 · 文生图（Mock 导入样例）
# category      = image
# function      = t2i
# stream        = false
# web_search    = false
# seed          = false
# resolutions   = 1k,2k
# ratios        = 1:1,16:9,4:3,3:4
# qualities     = standard
# formats       = png
# need_image    = false
# key_env       = DEMO_API_KEY
# [ACS_META_END]
"""

import argparse
import json
import math
import os
import struct
import sys
import time
import zlib
from datetime import datetime
from pathlib import Path

API_KEY = ""  # 由模型设置「确定」写入；为空时回退环境变量 DEMO_API_KEY

_MOCK_COLORS = [(70, 100, 210), (210, 80, 60), (60, 160, 100), (200, 160, 50)]


def _make_png(path: Path, width: int, height: int, base) -> None:
    def chunk(tag, data):
        return (struct.pack(">I", len(data)) + tag + data
                + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF))
    raw = bytearray()
    for y in range(height):
        raw.append(0)
        t = y / max(1, height - 1)
        row = bytes((
            min(255, int(base[0] + (255 - base[0]) * t * 0.5)),
            min(255, int(base[1] + (255 - base[1]) * t * 0.5)),
            min(255, int(base[2] + (255 - base[2]) * t * 0.5)),
        ))
        raw.extend(row * width)
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    png = (b"\\x89PNG\\r\\n\\x1a\\n"
           + chunk(b"IHDR", ihdr)
           + chunk(b"IDAT", zlib.compress(bytes(raw), 9))
           + chunk(b"IEND", b""))
    path.write_bytes(png)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--params", required=True)
    args = parser.parse_args()
    started = time.time()
    try:
        params = json.loads(Path(args.params).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(json.dumps({"status": "error", "code": "INVALID_PARAMS",
                          "message": str(exc)}, ensure_ascii=False))
        return 1
    prompt = str(params.get("prompt", "")).strip()
    if not prompt:
        print(json.dumps({"status": "error", "code": "INVALID_PARAMS",
                          "message": "prompt 不能为空"}, ensure_ascii=False))
        return 1
    out = Path(params.get("output_dir") or ".")
    batch = max(1, min(9, int(params.get("batch", 1) or 1)))
    mock = bool(params.get("mock", False))
    try:
        out.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        files = []
        for i in range(batch):
            p = out / f"demo_mock_{stamp}_{i + 1:02d}.png"
            _make_png(p, 768, 768, _MOCK_COLORS[i % len(_MOCK_COLORS)])
            files.append(str(p.resolve()))
        print(json.dumps({"status": "ok", "files": files,
                          "elapsed": round(time.time() - started, 2)},
                         ensure_ascii=False))
        return 0
    except Exception as exc:  # noqa: BLE001
        print(json.dumps({"status": "error", "code": "INTERNAL",
                          "message": str(exc)}, ensure_ascii=False))
        return 1


if __name__ == "__main__":
    sys.exit(main())
'''


def mock_generate_scripts() -> str:
    """返回一份演示脚本 JSON（模拟 LLM 输出），供 mock 导入链路使用。

    演示/测试时不想真连 LLM，就调用本函数：它返回的 JSON 结构和真实
    LLM 输出一致（scripts 数组，每项含 display_name/category/function/
    file_name/code），代码是一份"纯标准库画 PNG 渐变图"的可运行脚本，
    走完整个导入管线后能真正跑起来出图。

    Returns:
        JSON 字符串（模拟 LLM 的回复全文）。
    """
    payload = {
        "scripts": [
            {
                "display_name": "演示 · 文生图（Mock 导入样例）",
                "category": "image",
                "function": "t2i",
                "file_name": "demo_mock_t2i.py",
                "code": _MOCK_CODE,
            }
        ]
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)
