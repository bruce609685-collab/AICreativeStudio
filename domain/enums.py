"""全局枚举——程序里所有"取值固定的选项"都集中在这里定义。

枚举（Enum）可以理解为"一组约定好的固定选项"，比如媒体类别只有图片/
视频/语音三种、任务状态只有排队/生成中/成功/失败四种。把这类选项
统一定义在这一处，其他代码都从这里引用，可以避免到处硬编码字符串、
拼写不一致等低级错误。

本文件属于 domain（领域）层：不依赖任何界面库或第三方库，
任何模块都可以放心引用它。
"""

from enum import Enum


class MediaCategory(str, Enum):
    """脚本媒体类别（对应 ACS_META 的 category 字段）。

    标识一个制式脚本生成的是哪一类媒体文件。继承自 str，
    所以枚举值可以直接当普通字符串使用（比如 "image"），
    便于与脚本文件头部声明的元数据文本做比对。
    """

    IMAGE = "image"
    VIDEO = "video"
    AUDIO = "audio"


class JobStatus(str, Enum):
    """一次生成任务的状态机。

    "状态机"指一个任务从创建到结束只会按固定路线流转：
    排队(QUEUED) → 生成中(RUNNING) → 成功(SUCCEEDED) 或 失败(FAILED)。
    界面和数据库都用这几个值来判断/展示任务当前进展到哪一步。
    """

    QUEUED = "queued"        # 已排队
    RUNNING = "running"      # 生成中
    SUCCEEDED = "succeeded"  # 成功
    FAILED = "failed"        # 失败（历史记录保留提示词）
