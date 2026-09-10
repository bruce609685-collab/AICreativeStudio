"""生成任务的参数字典组装（runner 域）。UI 页签 → job.json。

本模块是"界面 → 脚本"的翻译官：用户在图/视频/语音三个页签里选的
参数（提示词、分辨率、比例、时长、种子等），由这里组装成统一的
参数字典，随后写成 job.json 文件传给脚本子进程（见 runner.py）。

字典的键名全部来自 contract.params 常量（如 K_PROMPT），保证界面、
脚本两侧对同一概念的叫法完全一致。所有用户输入都不可信：非数字、
超范围、负数值都在这里被清洗/截断（见 _safe_int、_sanitize_seed），
不会把脏参数传给脚本。
"""

from contract import params as P
from contract.params import write_params_file

# 各 API 通用的种子安全范围（有符号 32 位）
_SEED_MAX = 2147483647


def write_job_file(path, **values):
    """把组装好的参数写为 job.json（core 层对 ui 的唯一落盘出口）。

    §9.2 规定 ui 不许直接 import contract，落盘一律走 core 服务——
    本函数即为此收拢：三个生成页调它，内部转手 contract.params。
    参数含义与 contract.params.write_params_file 一致（幂等覆盖写）。
    """
    return write_params_file(path, **values)


def _sanitize_seed(raw: str) -> str | None:
    """把种子值清洗为安全范围：<0 / 非数字 → None（不传，让 API 随机），>max 截断。

    种子（seed）决定生成结果的随机性：相同种子+相同参数会得到相同
    结果。各 API 对种子的要求是有符号 32 位整数，超范围会报错，所以：
    - 用户填负数（常见 "-1"=随机）→ 返回 None，调用方跳过该键，
      job.json 里就完全没有 seed 字段，脚本按"未提供"处理；
    - 超过 2147483647 → 截断到上限；
    - 非数字 → 同样返回 None（当作随机）。

    历史教训：曾返回空串 ""，但部分 LLM 生成的脚本用
    `int(params.get("seed"))` 直接转换，`int("")` 崩溃报
    "seed must be an integer"。改成 None + 省键后彻底规避。

    Args:
        raw: 用户在界面输入的种子字符串。

    Returns:
        清洗后的种子字符串（合法数字）或 None（不传）。
    """
    try:
        n = int(raw.strip())
    except (ValueError, AttributeError):
        return None
    if n < 0:
        return None   # 不传 seed，让 API 随机
    if n > _SEED_MAX:
        n = _SEED_MAX
    return str(n)


def _safe_int(raw: str, default: int = 5, min_val: int | None = None,
               max_val: int | None = None) -> int:
    """安全解析整数字符串，非数字时返回默认值；指定范围时自动截断到边界。

    界面传来的值都可能是"脏"的（空串、乱输入、超范围），本函数
    保证吐出来的一定是合法整数：
    - 解析失败 → 返回 default；
    - 小于 min_val → 返回 min_val；大于 max_val → 返回 max_val
      （截断而非报错，让生成流程不中断）。

    Args:
        raw: 待解析的值（通常是界面输入的字符串）。
        default: 解析失败时的默认值。
        min_val / max_val: 允许的最小/最大值，None 表示不限制。

    Returns:
        清洗后的整数。
    """
    try:
        n = int(str(raw).strip())
    except (ValueError, AttributeError):
        return default
    if min_val is not None and n < min_val:
        return min_val
    if max_val is not None and n > max_val:
        return max_val
    return n


def build_image_params(
    prompt: str,
    ratio: str,
    resolution: str,
    quality: str,
    format_: str,
    batch: int,
    output_dir,
    seed: str = "-1",
    mock: bool = False,
    ref_image: str | None = None,
    timeout: int = 300,
) -> dict:
    """组装生图任务参数字典（键名见契约 §2.1）。

    把生图页签的全部输入规整为一个 dict，之后写成 job.json 传给脚本。
    内含几处清洗：张数限 1-9（_safe_int 截断）、种子经 _sanitize_seed。

    Args:
        prompt: 提示词（画面描述）。
        ratio: 画面比例（如 "16:9"）。
        resolution: 分辨率档位（如 "2k"）。
        quality: 质量档位（如 "standard"）。
        format_: 输出格式（默认 png）。
        batch: 一次生成几张（1-9）。
        output_dir: 输出目录（转成字符串传入）。
        seed: 种子字符串，默认 "-1"（随机）。
        mock: True 表示走脚本内置的 mock 分支（演示用）。
        ref_image: 参考图路径（图生图时提供）。
        timeout: 超时秒数，透传给脚本。

    Returns:
        参数字典（键为 contract.params 常量）。
    """
    data: dict = {
        P.K_PROMPT: prompt,
        P.K_RATIO: ratio or "",
        P.K_RESOLUTION: resolution or "",
        P.K_QUALITY: quality or "",
        P.K_FORMAT: format_ or "png",
        # 张数限幅 1-9：防止手滑输入 0 或超大数字
        P.K_BATCH: max(1, min(9, _safe_int(batch, 1))),
        P.K_OUTPUT_DIR: str(output_dir),
        P.K_TIMEOUT: timeout,
    }
    # seed 无效（负数/非数字）→ 整个键不写入 job.json，脚本按"未提供"处理
    seed_clean = _sanitize_seed(seed)
    if seed_clean is not None:
        data[P.K_SEED] = seed_clean
    if mock:
        data[P.K_MOCK] = True
    if ref_image:
        data[P.K_REF_IMAGE] = str(ref_image)
    return data


def build_video_params(
    prompt: str,
    ratio: str,
    resolution: str,
    duration: str,
    mode: str,
    output_dir,
    seed: str = "-1",
    sound: bool = False,
    mock: bool = False,
    ref_image: str | None = None,
    timeout: int = 600,
) -> dict:
    """组装生视频任务参数字典（视频类：一次一条，异步任务协议见契约）。

    与生图类似的组装逻辑，差别：视频一次只生成一条（batch 恒为 1）；
    时长经 _safe_int 限幅 2-15 秒；可选声效开关（sound）和参考图
    （图生视频）。

    Args:
        prompt: 提示词（画面/运镜描述）。
        ratio: 画面比例。resolution: 分辨率档位。
        duration: 视频时长字符串（清洗后限 2-15 秒）。
        mode: 生成模式（如 "std"/"pro"）。
        output_dir: 输出目录。
        seed: 种子字符串，默认 "-1"（随机）。
        sound: 是否生成带声音的视频。
        mock: True 走 mock 分支。ref_image: 参考图路径（图生视频）。
        timeout: 超时预算秒数。视频生成耗时长，默认 600 秒。

    Returns:
        参数字典（键为 contract.params 常量）。
    """
    data: dict = {
        P.K_PROMPT: prompt,
        P.K_RATIO: ratio or "",
        P.K_RESOLUTION: resolution or "",
        P.K_DURATION: _safe_int(duration, 5, min_val=2, max_val=15),
        P.K_MODE: mode or "",
        P.K_BATCH: 1,
        P.K_OUTPUT_DIR: str(output_dir),
        P.K_TIMEOUT: timeout,
    }
    # seed 无效（负数/非数字）→ 整个键不写入 job.json，脚本按"未提供"处理
    seed_clean = _sanitize_seed(seed)
    if seed_clean is not None:
        data[P.K_SEED] = seed_clean
    if sound:
        data[P.K_SOUND] = True
    if mock:
        data[P.K_MOCK] = True
    if ref_image:
        data[P.K_REF_IMAGE] = str(ref_image)
    return data


def build_audio_params(
    text: str,
    voice: str,
    style: str,
    format_: str,
    output_dir,
    mock: bool = False,
    timeout: int = 300,
) -> dict:
    """组装生语音任务参数字典（语音类：文本走 prompt 键）。

    注意：配音页签里用户输入的"文本"在参数字典里也用 K_PROMPT 键
    承载（契约约定：所有任务的待处理内容统一叫 prompt），脚本侧
    按类别自行把它当文本处理。无种子/比例等字段。

    Args:
        text: 要转成语音的文本。
        voice: 音色（如 "标准女声"）。
        style: 语言/风格。
        format_: 输出格式（默认 wav）。
        output_dir: 输出目录。
        mock: True 走 mock 分支。
        timeout: 超时秒数。

    Returns:
        参数字典（键为 contract.params 常量）。
    """
    data: dict = {
        P.K_PROMPT: text,
        P.K_VOICE: voice or "",
        P.K_STYLE: style or "",
        P.K_FORMAT: format_ or "wav",
        P.K_BATCH: 1,
        P.K_OUTPUT_DIR: str(output_dir),
        P.K_TIMEOUT: timeout,
    }
    if mock:
        data[P.K_MOCK] = True
    return data
