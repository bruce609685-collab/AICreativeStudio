"""脚本元数据模型（ACS_META 的内存表示）。

"制式脚本"是指按固定格式编写、可被本程序识别和调用的 AI 生成脚本，
每个脚本头部都声明了一段 ACS_META 元数据（叫什么名字、能做什么、
支持哪些参数档位等）。本文件把这些元数据装载成 Python 对象，
让程序在内存中可以方便地读取和传递。

M1 骨架版：仅承载界面演示所需字段；
M2 将由 core/registry/meta_parser.py 从 py 脚本头部解析填充。

本文件属于 domain（领域）层：只描述数据长什么样，不含任何
界面或网络逻辑，因此可以被 UI 层、启动层等各方共同引用。
"""

from dataclasses import dataclass, field

from domain.enums import MediaCategory


@dataclass
class ScriptMeta:
    """一个制式脚本的元数据快照。

    dataclass（数据类）是 Python 的语法糖：只需声明字段，就自动获得
    构造函数、比较等功能。这个类的每个字段对应脚本声明的一项能力或
    信息，界面据此决定显示哪些控件（比如脚本不支持种子就不显示种子输入框）。

    关键字段说明：
    - display_name / file_path：脚本的名字和位置，用于界面展示与调用；
    - function：脚本功能类型（t2i=文字生图、i2i=图生图、t2v=文字生视频、
      i2v=图生视频、tts=语音合成、voice_design=音色设计）；
    - api_key：只记录"已填/未填"的事实，明文密钥不存这里；
    - 各能力开关（seed/stream/web_search 等）：驱动界面参数区的显隐。
    """

    display_name: str = ""                    # 界面显示名（下拉框）
    # 该脚本产出哪类媒体（image/video/audio），默认按图片处理
    category: MediaCategory = MediaCategory.IMAGE
    function: str = "t2i"                     # t2i/i2i/t2v/i2v/tts/voice_design
    file_path: str = ""                       # 相对 scripts/ 的路径
    template_version: str = "1.0.0"
    # §5.4 契约版本门闸结论：ok 一致 / older 脚本过旧 / newer 脚本过新。
    # 只影响界面提示（如状态栏提醒"脚本模板过旧"），不阻断注册使用。
    version_compat: str = "ok"
    api_key: str = ""                         # 是否已填 KEY（只存"已填/未填"事实）

    # 能力声明（驱动界面参数区显隐）
    seed: bool = False                        # 是否支持随机种子
    stream: bool = False                      # 是否支持流式输出
    web_search: bool = False                  # 是否支持联网搜索
    sound: bool = False                       # 是否支持生成声音（视频类）
    need_image: bool = False                  # 是否需要参考图/首帧
    # 下面几组列表是可选档位：界面会按列表内容生成对应的下拉选项；
    # 用 default_factory 是因为 dataclass 的可变默认值必须这样写才安全
    resolutions: list[str] = field(default_factory=list)
    ratios: list[str] = field(default_factory=list)
    qualities: list[str] = field(default_factory=list)
    formats: list[str] = field(default_factory=list)      # 输出格式
    durations: list[str] = field(default_factory=list)   # 视频时长档位
    modes: list[str] = field(default_factory=list)       # 生成模式档位
    voices: list[str] = field(default_factory=list)      # 预置音色列表
    max_text_len: int = 1000                  # 语音类文本上限
    key_env: str = ""                         # 脚本读取 KEY 的环境变量名
    key_required: bool = True                 # 是否需要 API KEY
    pip_requires: list[str] = field(default_factory=list)  # pip 依赖包名列表

    @property
    def has_key(self) -> bool:
        """判断脚本所需的 API KEY 是否已填写。

        返回值：True 表示已有非空（去掉首尾空白后）的 KEY 记录；
        False 表示还没填。界面用它决定是否提示用户先去填写密钥。
        """
        # strip() 去掉首尾空白：防止用户只填了空格被误认为已填写
        return bool(self.api_key and self.api_key.strip())
