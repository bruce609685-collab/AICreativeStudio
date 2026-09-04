"""智能导入主流程（headless）：文档 → 门闸 → LLM → 解析 → 安全 → 落盘。

这是"智能导入"功能的主编排器，把 importer 包里其他模块串成一条完整
流水线，共 5 步：
1. 完备性门闸（completeness）：先快速检查用户粘贴的 API 文档是否
   包含必要信息（接口地址/认证方式/模型 ID），缺了就直接拦下；
2. 加载提示词模板：按脚本类别（图/视频/音频）选对应的 prompt 模板，
   模板作为 system 提示词告诉 LLM "要生成什么格式的脚本"；
3. 调用 LLM（llm_client）：把文档喂给大模型，流式接收生成的脚本
   JSON（演示模式下走 mock，不联网）；
4. 解析与安全检查：提取 JSON、校验 ACS_META 标记、**强制清空
   API_KEY**（防止 LLM 把真实密钥写进代码）、修复 META 格式、
   注入缺失的默认能力字段；
5. 产出 ImportResult 交给界面确认，用户点"导入"后由 save_scripts()
   把脚本文件写到 scripts/{类别}_scripts/ 目录，随后交给注册表登记。

管线：import_from_document() 产出 ImportResult（含脚本列表与缺口信息）；
UI 确认后调用 save_scripts() 落盘。本模块禁止 import PySide6，可独立测试。
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

from core.importer import completeness
from core.importer.llm_client import LLMConfig, call_llm, mock_generate_scripts
from contract.fields import META_END, META_START

logger = logging.getLogger(__name__)

TEMPLATE_FILENAME = "prompt_template_v1.0.0.txt"

# 类别 → 专用模板文件名（为空则回退到通用模板）
_CATEGORY_TEMPLATES = {
    "image": "prompt_image_v1.0.0.txt",
    "video": "prompt_video_v1.0.0.txt",
    "audio": "prompt_audio_v1.0.0.txt",
}

# 类别 → scripts/ 子目录
_CATEGORY_DIRS = {
    "image": "image_scripts",
    "video": "video_scripts",
    "audio": "audio_scripts",
}

# 脚本头部注释里的依赖提示（M6「关于 → 安装依赖项」会解析它）
DEPS_MARKERS = ("pip install", "依赖安装")


@dataclass
class ImportedScript:
    """一个待落盘的制式脚本。

    代表 LLM 生成、并通过校验和安全检查的一个脚本，此时还未写入磁盘。

    关键属性：
    - file_name: 清洗后的安全文件名（如 "demo_mock_t2i.py"）；
    - code: 脚本完整代码（已置空 API_KEY、已修复 META 格式）；
    - category: 类别（image/video/audio），决定落到哪个子目录；
    - display_name: 展示名称（界面列表里显示的名字）；
    - warn_deps: True 表示代码里声明了 pip 依赖，落盘后要提醒
      用户去「关于」页安装依赖。

    使用场景：由 import_from_document 填充，save_scripts 消费。
    """

    file_name: str
    code: str
    category: str
    display_name: str
    warn_deps: bool = False     # 依赖非内嵌 → 提醒去「关于」页安装


@dataclass
class ImportResult:
    """一次导入的产物与缺口信息。

    是 import_from_document 的返回值，完整描述这次导入的结果：
    成功时 scripts 里有待落盘脚本；失败时 error 说明原因；
    完备性检查的缺口（缺哪些文档信息）无论成败都会带回，
    供界面弹窗提示用户补充。

    关键属性：
    - ok: 整个管线是否走通（True 表示可以调 save_scripts 落盘）；
    - scripts: 解析出的待落盘脚本列表；
    - required_missing / optional_missing: 文档缺失的必要/非必要项名称；
    - error: 失败原因（面向用户的中文提示）；
    - llm_output: LLM 的原始输出全文（诊断用，界面可回看）。
    """

    ok: bool = False
    scripts: list[ImportedScript] = field(default_factory=list)
    required_missing: list[str] = field(default_factory=list)
    optional_missing: list[str] = field(default_factory=list)
    error: str = ""
    llm_output: str = ""


# ----------------------------------------------------------------------
# 工具
# ----------------------------------------------------------------------

def _sanitize_filename(name: str) -> str:
    """display_name → 安全文件名（小写下划线）。

    把 LLM 随口起的名字清洗成合法的 Python 文件名：空格、标点等
    非法字符换成下划线（中文保留），全空则回退 "imported_script"，
    最后加 .py 后缀并转小写。

    Args:
        name: 脚本展示名或 LLM 给的 file_name。

    Returns:
        形如 "demo_mock_t2i.py" 的安全文件名。
    """
    name = re.sub(r"[^\w\u4e00-\u9fff-]+", "_", name.strip()).strip("_")
    if not name:
        name = "imported_script"
    return name.lower() + ".py"


def _simulate_stream_chunks(text: str, on_chunk, size: int = 40) -> None:
    """把一段文字按小块吐出（mock 演示模式模拟流式效果）。

    真实 LLM 是流式输出，mock 模式为了让界面的"打字机"效果一致，
    把整段文字按 size 字符一块、每块间隔 4 毫秒地回调 on_chunk，
    假装在流式生成。

    Args:
        text: 要模拟输出的全文。
        on_chunk: 增量回调 on_chunk(chunk_text)。
        size: 每块的字符数。
    """
    import time

    for i in range(0, len(text), size):
        on_chunk(text[i:i + size])
        time.sleep(0.004)


# 各类别默认能力字段（LLM 遗漏时注入）
_DEFAULT_CAPS: dict[str, list[str]] = {
    "image": [
        "# resolutions   = 1k,2k",
        "# ratios        = 1:1,16:9,4:3,3:4,9:16",
        "# qualities     = standard",
        "# formats       = png,jpeg",
    ],
    "video": [
        "# resolutions   = 720p,1080p",
        "# ratios        = 16:9,9:16,1:1",
        "# qualities     = standard",
        "# durations     = 2-15",
        "# modes         = std,pro",
    ],
    "audio": [
        "# voices        = 默认音色,标准女声,标准男声",
        "# max_text_len  = 1000",
        "# formats       = wav,mp3",
    ],
}

# 布尔能力字段检测：脚本代码中引用以下参数 → 自动注入 true
_BOOL_CAP_PATTERNS: dict[str, list[str]] = {
    "seed": [
        r'params\[.seed.\]', r'params\.get\(.seed.',
        r'K_SEED', r'"seed"', r"'seed'",
    ],
    "stream": [
        r'params\[.stream.\]', r'params\.get\(.stream.',
        r'K_STREAM', r'"stream"', r"'stream'",
    ],
    "web_search": [
        r'params\[.web_search.\]', r'params\.get\(.web_search.',
        r'K_WEB_SEARCH', r'"web_search"', r"'web_search'",
    ],
    "sound": [
        r'params\[.sound.\]', r'params\.get\(.sound.',
        r'K_SOUND', r'"sound"', r"'sound'",
    ],
    "need_image": [
        r'params\[.ref_image.\]', r'params\.get\(.ref_image.',
        r'K_REF_IMAGE', r'"ref_image"', r"'ref_image'",
        r'ref_image',
    ],
}


def _detect_bool_caps(code: str) -> list[str]:
    """从脚本代码中检测是否引用了某个布尔能力参数，返回应设为 true 的字段名。

    LLM 生成的代码里如果用到了 seed / stream / web_search 等参数
    （如 params.get("seed")），但 META 注释块里忘了声明对应能力字段，
    运行器就不会把该参数传给脚本——这里通过正则扫描代码把这些
    "代码里用了但 META 里没写"的能力找出来，调用方据此补一条
    "# seed = true" 进 META。

    Args:
        code: 脚本完整代码。

    Returns:
        检测到的能力字段名列表（如 ["seed", "stream"]），无则空表。
    """
    found: list[str] = []
    for field, patterns in _BOOL_CAP_PATTERNS.items():
        for pat in patterns:
            if re.search(pat, code):
                found.append(field)
                break
    return found


def _fix_meta_format(code: str) -> str:
    """修复 LLM 生成的 META 块格式错误（Python 语法 → 标准格式）。

    LLM 很容易把 META 写成 Python 语法，比如：
      resolutions: ['2K', '3K', '4K']
      seed: True
    但注册表的 META 解析器只认标准格式：
      # resolutions   = 2K,3K,4K
      # seed          = true
    本函数专门做这道"格式翻译"：冒号改等号、列表去引号去方括号、
    True/False 转小写，并且只处理 META 块内部（两个标记之间）的行，
    代码其他部分原样保留。

    Args:
        code: LLM 生成的脚本完整代码。

    Returns:
        修复后的代码；找不到 META 标记或没有需要修复的行时原样返回。
    """
    # 先找带 # 前缀的标记，找不到再找裸标记（兼容两种写法）
    start = code.find("# [ACS_META_START]")
    end = code.find("# [ACS_META_END]")
    if start < 0 or end <= start:
        start = code.find("[ACS_META_START]")
        end = code.find("[ACS_META_END]")
        if start < 0 or end <= start:
            return code

    meta_raw = code[start:end + len("# [ACS_META_END]")]
    meta_lines = meta_raw.splitlines()
    fixed: list[str] = []
    changed = False
    for line in meta_lines:
        stripped = line.strip()
        # 跳过标记行和空行
        if stripped in ("[ACS_META_START]", "[ACS_META_END]",
                        "# [ACS_META_START]", "# [ACS_META_END]"):
            fixed.append(line)
            continue
        if not stripped or stripped.startswith("#") and "=" in stripped:
            fixed.append(line)  # 已有正确格式，保留
            continue

        # 去掉 # 前缀
        content = stripped.lstrip("#").strip()
        if not content:
            fixed.append(line)
            continue

        # 检查是否包含 ":"（Python 语法）而非 "="——这是需要修复的行
        if ":" in content and "=" not in content:
            parts = content.split(":", 1)
            key = parts[0].strip()
            val = parts[1].strip()
            # 转换 Python 列表语法 ['a', 'b'] → a,b
            if val.startswith("[") and val.endswith("]"):
                inner = val[1:-1]
                items = []
                for item in inner.split(","):
                    item = item.strip().strip("'\"").strip()
                    if item:
                        items.append(item)
                val = ",".join(items)
            # 转换 Python 布尔语法 True/False → true/false
            if val.lower() in ("true", "false"):
                val = val.lower()
            # 按标准格式重排：# 键(左对齐14格) = 值
            fixed.append(f"# {key:14} = {val}")
            changed = True
        else:
            fixed.append(line)

    if not changed:
        return code
    # 用修复后的 META 块替换原来的块，块外代码不动
    return code[:start] + "\n".join(fixed) + code[end + len("# [ACS_META_END]"):]


def _inject_default_caps(code: str, category: str) -> str:
    """如果生成的脚本 META 块缺少能力字段，注入默认值（插入 [ACS_META_END] 前）。

    LLM 生成的 META 经常漏写字段（如 resolutions、ratios），或者写出
    无法解析的"垃圾值"（比如把分辨率写成中文描述"2K到4K"）。缺字段
    会导致运行器没法给界面提供分辨率/比例等选项，垃圾值会导致解析失败。
    本函数做三件事：
    1. 扫描 META 里的已有字段，把"垃圾值"行删掉（含中文或
       "数字~数字/数字-数字"范围描述的值都算垃圾）；
    2. 按 category 对照 _DEFAULT_CAPS，把缺失的（或刚删掉的垃圾）
       字段用默认值补上；
    3. 调 _detect_bool_caps 扫描代码，把"代码里用了但 META 没声明"的
       布尔能力（seed/stream 等）补成 true。

    不覆盖已有**有效**字段，只补充缺失的或替换非数字垃圾值。

    Args:
        code: 脚本完整代码（应已含 META 块）。
        category: 脚本类别（image/video/audio），决定用哪套默认值。

    Returns:
        补全后的代码；没有 META 结束标记或无字段可补时原样返回。
    """
    # 列表类字段的值有效性检测：不能含中文、不能是范围描述
    def _is_garbage(val: str) -> bool:
        # 值里出现中文字符 → 大概率是 LLM 写的描述文字而非枚举值
        if any('\u4e00' <= c <= '\u9fff' for c in val):
            return True
        # "720p-1080p"、"2~4" 这类范围描述无法作为合法枚举 → 视为垃圾
        if re.search(r'\d+\s*[~\-]\s*\d+', val):
            return True
        return False

    meta_end = "# [ACS_META_END]"
    if meta_end not in code:
        return code

    # 1. 扫描已有字段，收集垃圾行并移除
    lines = code.splitlines(keepends=True)
    clean_lines: list[str] = []
    existing_valid: set[str] = set()
    garbage_fields: list[str] = []
    for line in lines:
        line_s = line.strip()
        if line_s.startswith("#") and "=" in line_s:
            after = line_s.lstrip("#").strip()
            if "=" in after:
                field, _, val = after.partition("=")
                field = field.strip()
                val = val.strip()
                if _is_garbage(val):
                    garbage_fields.append(field)
                    logger.info("移除垃圾值：%s = %s", field, val)
                    continue  # 跳过垃圾行，稍后注入默认值
                existing_valid.add(field)
        clean_lines.append(line)

    # 2. 注入缺失的或替换垃圾的默认值
    defaults = _DEFAULT_CAPS.get(category, [])
    need = []
    for line in defaults:
        field = line.lstrip("#").split("=")[0].strip()
        if field not in existing_valid or field in garbage_fields:
            need.append(line + "\n")

    # 3. 注入布尔类能力（从代码检测）
    for field in _detect_bool_caps(code):
        if field not in existing_valid:
            need.append(f"# {field:14} = true\n")

    if not need:
        return "".join(clean_lines)

    # 4. 在 [ACS_META_END] 前插入
    clean_code = "".join(clean_lines)
    insert = "".join(need)
    clean_code = clean_code.replace(meta_end, insert + meta_end, 1)
    return clean_code


def _parse_llm_json(text: str) -> list[dict]:
    """从 LLM 输出提取 JSON（兼容 ```json 包裹与前后杂文）。

    LLM 有时不守规矩：输出被 ```json ... ``` 代码块包着、前后带
    客套话等。本函数负责"剥壳"：去掉代码围栏，截取第一个 { 到最后
    一个 } 之间的内容再解析，最后校验 scripts 数组存在且非空。

    Args:
        text: LLM 的原始输出全文。

    Returns:
        scripts 数组（list[dict]），每项是一个脚本描述。

    Raises:
        ValueError: 输出为空 / 找不到 JSON 对象 / 解析失败 /
        scripts 数组为空——错误信息均面向用户、附原始输出预览，
        便于界面诊断。
    """
    text = (text or "").strip()
    if not text:
        raise ValueError("LLM 输出为空——模型未返回任何内容，请重试或检查模型。")
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end <= start:
        preview = text[:200].replace("\n", " ")
        raise ValueError(
            f"LLM 输出缺少 JSON 对象——模型可能未按模板要求返回格式，"
            f"请重试；如持续失败请更换模型或检查模型名。"
            f"（原始输出预览：{preview}）")
    try:
        data = json.loads(text[start:end + 1])
    except json.JSONDecodeError as exc:
        raise ValueError(f"LLM 输出 JSON 解析失败：{exc}") from None
    scripts = data.get("scripts")
    if not isinstance(scripts, list) or not scripts:
        raise ValueError("LLM 输出 scripts 数组为空")
    return scripts


# ----------------------------------------------------------------------
# 主流程
# ----------------------------------------------------------------------

def import_from_document(doc_text: str, cfg: LLMConfig,
                         templates_dir: Path, scripts_dir: Path,
                         on_log=None, on_chunk=None,
                         category: str = "") -> ImportResult:
    """完整导入管线。

    按顺序执行：完备性检查 → 加载模板 → LLM 生成 → 解析校验 →
    安全检查（清空 API_KEY）→ 修复 META → 注入默认能力 → 产出结果。
    任何一步失败都会立刻返回（result.ok=False，error 说明原因），
    不会落盘任何文件。

    Args:
        doc_text: 用户粘贴的 API 文档全文。
        cfg: LLM 连接配置（mock=True 时跳过真实调用）。
        templates_dir: 提示词模板所在目录。
        scripts_dir: scripts/ 根目录（本函数不直接写文件，
        只透传给后续的 save_scripts 使用）。
        on_log(msg) 可选回调：管线步骤日志；
        on_chunk(text) 可选回调：LLM 输出增量块（流式实时显示用）；
        category 可选：image / video / audio，指定使用专用模板（空 = 通用模板）。

    Returns:
        ImportResult：成功时 scripts 为待落盘脚本列表，调用方
        （UI 确认后）再调 save_scripts 写入磁盘。
    """

    def log(msg: str) -> None:
        if on_log is not None:
            on_log(msg)

    result = ImportResult(ok=False)

    # 1. 完备性门闸：文档必要信息
    gaps = completeness.check_document(doc_text)
    result.required_missing = gaps["required_missing"]
    result.optional_missing = gaps["optional_missing"]
    if gaps["required_missing"]:
        result.error = "必要信息缺失"
        return result
    log("✅ 完备性检查通过（必要项齐全）")

    # 2. 加载提示词模板（按类别选专用模板，未指定或不存在则回退通用）
    tpl_name = _CATEGORY_TEMPLATES.get(category, "")
    tpl_file = Path(templates_dir) / tpl_name if tpl_name else Path(templates_dir) / TEMPLATE_FILENAME
    if not tpl_file.exists():
        tpl_file = Path(templates_dir) / TEMPLATE_FILENAME  # 回退通用
    if not tpl_file.exists():
        result.error = f"提示词模板缺失：{tpl_file.name}"
        return result
    template = tpl_file.read_text(encoding="utf-8")
    log(f"🔍 加载提示词模板 {tpl_file.name}")

    # 3. LLM 生成（mock 或真实）
    if cfg.mock:
        # 演示模式：不联网，返回内置演示脚本，并模拟流式打字效果
        raw = mock_generate_scripts()
        log("🤖 演示模式：使用 Mock LLM 生成脚本")
        if on_chunk is not None:
            _simulate_stream_chunks(raw, on_chunk)
    else:
        if not cfg.api_key.strip():
            result.error = "未配置 LLM API 密钥（或开启演示模式）"
            return result
        log("📖 连接 LLM，分析文档…（生成脚本可能需要 1-3 分钟，请耐心等待）")
        try:
            raw = call_llm(cfg, system=template, user=doc_text,
                           timeout=300.0, on_chunk=on_chunk)
        except RuntimeError as exc:
            result.error = str(exc)
            return result
    result.llm_output = raw

    # 4. 解析 + 校验 + 安全检查
    log("📝 解析并校验生成脚本…")
    try:
        items = _parse_llm_json(raw)
    except ValueError as exc:
        result.error = str(exc)
        return result

    for item in items:
        code = str(item.get("code", "")).strip()
        if not code:
            result.error = "LLM 返回的脚本代码为空"
            return result
        if META_START not in code or META_END not in code:
            result.error = f"脚本「{item.get('display_name', '?')}」缺少 ACS_META 标记"
            return result
        # 安全检查：API KEY 一律置空（防 LLM 注入真实密钥）
        # ——不管 LLM 写了什么 KEY，都替换成空串；用户稍后在
        # 「模型设置」页填入自己的 KEY（keys.py 的 inject_key）
        code = re.sub(
            r'API_KEY\s*=\s*["\'](?:[^"\'\\]|\\.)*["\']',
            'API_KEY = ""', code, count=1,
        )
        if 'API_KEY = ""' not in code:
            # 脚本里根本没有 API_KEY 行 → 在末尾补一行，保证 keys.py 有地方写入
            code = code.rstrip() + '\nAPI_KEY = ""  # ← 由模型设置「确定」写入\n'
        category = str(item.get("category", "image")).strip().lower()
        if category not in _CATEGORY_DIRS:
            category = "image"  # 类别不在白名单内 → 兜底归为图片类
        # 修复 META 格式（Python 语法 → 标准格式）
        code = _fix_meta_format(code)
        # 注入默认能力字段（LLM 遗漏时补全）
        code = _inject_default_caps(code, category)
        display_name = str(item.get("display_name", "")).strip() or "导入脚本"
        fname = _sanitize_filename(
            str(item.get("file_name") or display_name))
        warn_deps = any(marker in code for marker in DEPS_MARKERS)
        result.scripts.append(ImportedScript(
            file_name=fname, code=code, category=category,
            display_name=display_name, warn_deps=warn_deps,
        ))
        log(f"  → {display_name}（{category}）")

    if not result.scripts:
        result.error = "没有可导入的脚本"
        return result

    result.ok = True
    log("🔒 安全检查完成（API KEY 已置空）")
    log("✨ 完成")
    return result


def save_scripts(result: ImportResult, scripts_dir: Path) -> list[Path]:
    """把 ImportResult.scripts 落盘到 scripts/{category}_scripts/，返回路径。

    在 UI 展示导入预览、用户确认后才调用本函数。按每个脚本的类别
    写入对应子目录（image_scripts/video_scripts/audio_scripts），
    目录不存在会自动创建。落盘后由注册表重新扫描即可"上架"。

    Args:
        result: import_from_document 的产出（ok=True 才有意义）。
        scripts_dir: scripts/ 根目录。

    Returns:
        成功写入的脚本文件路径列表。
    """
    saved: list[Path] = []
    root = Path(scripts_dir)
    for script in result.scripts:
        d = root / _CATEGORY_DIRS.get(script.category, "image_scripts")
        d.mkdir(parents=True, exist_ok=True)
        path = d / script.file_name
        path.write_text(script.code, encoding="utf-8")
        saved.append(path)
        logger.info("已落盘脚本：%s", path)
    return saved
