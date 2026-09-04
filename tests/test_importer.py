"""智能导入管线单测：完备性门闸 + mock 全链路 + 落盘 + 注册表兼容。

测试分组：
  一、完备性检查：check_document 对完整/缺 URL 文档的缺口识别；
  二、mock 全链路：LLM 输出解析（含代码块包裹）、管线落盘后可被
      注册表扫描到、必要项缺失阻断、KEY 强制清空（安全）；
  三、M7.1 连接诊断：URL 补全规则 + 连接异常分类为中文提示；
  四、M7.3 流式输出：SSE 解析收集 delta、keepalive 跳过、mock 分块、
      HTTP 400 自动降级非流式、深度思考模型空 content 降级。

全部用 mock LLM，不依赖网络。

运行：python -m tests.test_importer
"""

import io
import json
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

from app import paths
from core.importer import (
    ImportResult,
    import_from_document,
    save_scripts,
)
from core.importer.completeness import check_document
from core.importer.llm_client import (
    LLMConfig, classify_connection_error, mock_generate_scripts,
    normalize_api_url, _read_sse,
)
from core.importer.pipeline import (
    _parse_llm_json, _simulate_stream_chunks,
)
from core.registry.scanner import scan_scripts_dir

# 样例"完整"接入文档：含接口地址、认证方式、模型 ID 三要素
GOOD_DOC = (
    "接口地址：https://api.example.com/v1/images/generations\n"
    "认证方式：Authorization: Bearer <API_KEY>\n"
    "模型 ID：demo-image-1，支持 seed、stream、web_search 参数。\n"
)


# ============================================================
# 一、完备性检查
# ============================================================

def test_completeness_full_doc() -> None:
    """完整文档：必要项与非必要项均无缺失。"""
    gaps = check_document(GOOD_DOC)
    assert gaps["required_missing"] == []
    assert gaps["optional_missing"] == []


def test_completeness_missing_url() -> None:
    """缺接口地址的文档：必要项缺口应含"API 接口地址"。"""
    gaps = check_document("只有认证方式 Bearer 和模型 demo-image-1，没有 URL")
    assert "API 接口地址" in gaps["required_missing"]


# ============================================================
# 二、mock 全链路
# ============================================================

def test_parse_llm_json_with_codeblock() -> None:
    """LLM 输出被 ```json 代码块包裹时也能正确解析出脚本列表。"""
    raw = "好的，以下是脚本：\n```json\n" + mock_generate_scripts() + "\n```"
    items = _parse_llm_json(raw)
    assert len(items) == 1
    assert items[0]["category"] == "image"


def test_mock_import_full_pipeline() -> None:
    """mock 全链路：导入成功 → 产物脚本结构合规 → 落盘可被注册表扫描。"""
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)
        result = import_from_document(
            GOOD_DOC, LLMConfig(mock=True),
            templates_dir=paths.TEMPLATES_DIR,
            scripts_dir=base / "scripts",
            on_log=lambda msg: None,
        )
        assert result.ok, f"导入失败：{result.error}"
        assert len(result.scripts) == 1
        s = result.scripts[0]
        # 脚本必须含 META 块，且 KEY 必须为空（安全要求）
        assert "[ACS_META_START]" in s.code
        assert 'API_KEY = ""' in s.code
        assert "sk-" not in s.code  # 安全：KEY 必须置空

        saved = save_scripts(result, base / "scripts")
        assert len(saved) == 1 and saved[0].exists()
        # 落盘后可被注册表扫描到（与 M2 兼容）
        metas = scan_scripts_dir(base / "scripts")
        assert len(metas) == 1
        assert metas[0].category.value == "image"


def test_mock_import_blocked_on_missing_required() -> None:
    """必要项缺失：管线阻断（ok=False），应有必要缺口且不产出脚本。"""
    with tempfile.TemporaryDirectory() as tmp:
        result = import_from_document(
            "只有一句话，没有 URL/认证/模型",
            LLMConfig(mock=True),
            templates_dir=paths.TEMPLATES_DIR,
            scripts_dir=Path(tmp) / "scripts",
        )
        assert not result.ok
        assert result.required_missing, "应有必要项缺失"
        assert result.scripts == []


def test_mock_import_key_cleaned_even_if_injected() -> None:
    """即使 LLM 塞了假 KEY，管线也必须清空。"""
    raw = mock_generate_scripts().replace('API_KEY = ""',
                                          'API_KEY = "sk-leak-test"')
    from core.importer.pipeline import _parse_llm_json

    items = _parse_llm_json(raw)
    code = items[0]["code"]
    import re

    # 用正则把 API_KEY 赋值行重写为空串（模拟管线的安全清洗）
    code = re.sub(r'API_KEY\s*=\s*["\'](?:[^"\'\\]|\\.)*["\']',
                  'API_KEY = ""', code, count=1)
    assert 'API_KEY = ""' in code
    assert "sk-leak-test" not in code


# ============================================================
# M7.1 连接诊断：URL 补全 / 错误分类
# ============================================================

def test_normalize_url_complete() -> None:
    """完整 chat/completions 地址原样保留。"""
    url = "https://api.x.com/v1/chat/completions"
    assert normalize_api_url(url) == url


def test_normalize_url_base_forms() -> None:
    """典型 base 地址自动补全 /chat/completions。"""
    assert normalize_api_url("https://api.x.com/v1") == \
        "https://api.x.com/v1/chat/completions"
    assert normalize_api_url("https://api.x.com/") == \
        "https://api.x.com/chat/completions"
    assert normalize_api_url("https://api.x.com/v1beta") == \
        "https://api.x.com/v1beta/chat/completions"


def test_normalize_url_missing_scheme() -> None:
    """缺协议自动补 https://。"""
    assert normalize_api_url("api.x.com/v1") == \
        "https://api.x.com/v1/chat/completions"


def test_normalize_url_keep_custom_path() -> None:
    """含其他自定义路径（如 /v1/generate）不猜，原样返回。"""
    url = "https://api.x.com/v1/generate"
    assert normalize_api_url(url) == url


def test_normalize_url_empty() -> None:
    assert normalize_api_url("") == ""
    assert normalize_api_url("   ") == ""


def test_classify_connection_error() -> None:
    """连接异常分类为可操作中文提示（不依赖网络）。

    分别覆盖 DNS 解析失败、连接被拒绝、超时（含等待时长）、通用网络错误。
    """
    import socket

    from core.importer import llm_client

    # DNS
    msg = classify_connection_error(socket.gaierror(-2, "name or service not known"))
    assert "域名解析失败" in msg
    # 拒绝
    msg = classify_connection_error(ConnectionRefusedError(10061, "refused"))
    assert "连接被拒绝" in msg
    # 超时（带等待时长提示）
    msg = classify_connection_error(TimeoutError("timed out"), timeout=300)
    assert "接口响应超时" in msg
    assert "300" in msg  # 提示已等待 300 秒
    # 通用 OSError
    msg = classify_connection_error(OSError("boom"))
    assert "网络错误" in msg


# ============================================================
# M7.3 流式输出：SSE 解析 / mock 流式 / HTTP 400 降级
# ============================================================

# ============================================================
# M7.3 流式输出：SSE 解析 / mock 流式 / HTTP 400 降级
# ============================================================

class _FakeStreamResp:
    """模拟 SSE 响应：可迭代 bytes 块（替代真实 HTTP 流）。"""

    def __init__(self, chunks: list[bytes]):
        self._chunks = chunks
        self.headers = {"Content-Type": "text/event-stream"}

    def __iter__(self):
        yield from self._chunks


def test_read_sse_collects_deltas() -> None:
    """SSE 流逐块收集 content，[DONE] 结束。

    验证：拼接结果正确、回调逐块收到内容、[DONE] 之后的块被忽略。
    """
    sse = (
        b'data: {"choices":[{"delta":{"content":"import "}}]}\n\n'
        b'data: {"choices":[{"delta":{"content":"json"}}]}\n\n'
        b'data: [DONE]\n\n'
        b'data: {"choices":[{"delta":{"content":"IGNORED"}}]}\n\n'  # [DONE] 后忽略
    )
    received: list[str] = []
    text = _read_sse(_FakeStreamResp([sse]), received.append)
    assert text == "import json"
    assert received == ["import ", "json"]


def test_read_sse_skips_keepalive() -> None:
    """非 data: 行（keepalive/注释）安全跳过。"""
    sse = (
        b': keepalive\n\n'
        b'data: {"choices":[{"delta":{"content":"ok"}}]}\n\n'
        b'\n'
        b'data: [DONE]\n\n'
    )
    text = _read_sse(_FakeStreamResp([sse]), None)
    assert text == "ok"


def test_simulate_stream_chunks() -> None:
    """mock 流式：小块拼接等于原文。"""
    text = mock_generate_scripts()
    got: list[str] = []
    _simulate_stream_chunks(text, got.append, size=30)
    assert "".join(got) == text
    assert len(got) > 1  # 确实分块了


def test_mock_import_stream_on_chunk() -> None:
    """mock 导入链路：on_chunk 收到流式块，拼接后等于 mock 输出。"""
    chunks: list[str] = []
    with tempfile.TemporaryDirectory() as tmp:
        result = import_from_document(
            GOOD_DOC, LLMConfig(mock=True),
            templates_dir=paths.TEMPLATES_DIR,
            scripts_dir=Path(tmp) / "scripts",
            on_log=lambda msg: None,
            on_chunk=chunks.append,
        )
    assert result.ok
    assert "".join(chunks) == result.llm_output


def test_call_llm_stream_fallback_on_400() -> None:
    """服务端拒绝 stream（HTTP 400）→ 自动降级非流式重试。"""
    import urllib.error

    from core.importer import llm_client

    url = "https://api.x.com/v1/chat/completions"
    cfg = LLMConfig(api_url=url, api_key="sk-x", model="gpt-4o")

    # 第一次请求抛 HTTPError(400)，第二次成功返回完整 JSON
    def _fake_urlopen(req, timeout=None):
        if getattr(req, "data", b""):
            body = req.data
            if b'"stream": true' in body:
                hdrs = {"Content-Type": "application/json"}
                fp = io.BytesIO(b'{"error":{"message":"stream not supported"}}')
                raise urllib.error.HTTPError(url, 400, "Bad Request", hdrs, fp)
        # 非流式重试成功
        class _Resp:
            headers = {"Content-Type": "application/json"}

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def read(self):
                return (b'{"choices":[{"message":{"content":"ok script"}}]}')
        return _Resp()

    with patch.object(llm_client.urllib.request, "urlopen",
                      side_effect=_fake_urlopen):
        chunks: list[str] = []
        text = llm_client.call_llm(cfg, "sys", "user", on_chunk=chunks.append)
    assert text == "ok script"
    assert chunks == ["ok script"]


def test_call_llm_stream_empty_fallback_to_nostream() -> None:
    """深度思考模型：流式 content 全空 → 自动降级非流式拿完整 JSON。"""
    from core.importer import llm_client

    url = "https://api.x.com/v1/chat/completions"
    cfg = LLMConfig(api_url=url, api_key="sk-x", model="deepseek-reasoner")
    full_json = '{"scripts":[{"display_name":"x","category":"image",' \
                '"function":"t2i","file_name":"x.py","code":"# ok"}]}'

    def _fake_urlopen(req, timeout=None):
        body = req.data
        if b'"stream": true' in body:
            # 流式：只给 reasoning_content（content 全空）
            class _SseResp:
                headers = {"Content-Type": "text/event-stream"}

                def __enter__(self):
                    return self

                def __exit__(self, *args):
                    return False

                def __iter__(self):
                    yield (b'data: {"choices":[{"delta":{"reasoning_content":'
                           b'"thinking..."}}]}\n\n')
                    yield b'data: [DONE]\n\n'
            return _SseResp()
        # 非流式：完整 JSON 在 message.content
        class _Resp:
            headers = {"Content-Type": "application/json"}

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def read(self):
                return (b'{"choices":[{"message":{"content":'
                        + json.dumps(full_json).encode() + b'}}]}')
        return _Resp()

    with patch.object(llm_client.urllib.request, "urlopen",
                      side_effect=_fake_urlopen):
        text = llm_client.call_llm(cfg, "sys", "user")
    # 降级后拿到完整 JSON 文本
    assert json.loads(text)["scripts"][0]["file_name"] == "x.py"


def test_parse_llm_json_empty_text() -> None:
    """空文本 → 明确错误信息。"""
    try:
        _parse_llm_json("")
    except ValueError as exc:
        assert "输出为空" in str(exc)
    else:
        raise AssertionError("应抛 ValueError")


def test_parse_llm_json_no_json_with_preview() -> None:
    """纯文字输出（无 JSON）→ 错误信息带原始输出预览。"""
    try:
        _parse_llm_json("好的，我可以帮你生成脚本，请提供更多信息。")
    except ValueError as exc:
        msg = str(exc)
        assert "缺少 JSON 对象" in msg
        assert "原始输出预览" in msg
    else:
        raise AssertionError("应抛 ValueError")


if __name__ == "__main__":
    test_completeness_full_doc()
    test_completeness_missing_url()
    test_parse_llm_json_with_codeblock()
    test_mock_import_full_pipeline()
    test_mock_import_blocked_on_missing_required()
    test_mock_import_key_cleaned_even_if_injected()
    test_normalize_url_complete()
    test_normalize_url_base_forms()
    test_normalize_url_missing_scheme()
    test_normalize_url_keep_custom_path()
    test_normalize_url_empty()
    test_classify_connection_error()
    test_read_sse_collects_deltas()
    test_read_sse_skips_keepalive()
    test_simulate_stream_chunks()
    test_mock_import_stream_on_chunk()
    test_call_llm_stream_fallback_on_400()
    test_call_llm_stream_empty_fallback_to_nostream()
    test_parse_llm_json_empty_text()
    test_parse_llm_json_no_json_with_preview()
    print("importer test passed")
    sys.exit(0)
