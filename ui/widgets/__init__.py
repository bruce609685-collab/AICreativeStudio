"""可复用界面控件。仅做展示与信号，不放业务逻辑（业务在 core/）。

包含：ParamPanel（动态参数面板）、ModelBar（脚本选择条）、KeyWarnBar
（KEY 警告条）、PreviewGrid（图片宫格）、PromptEcho（提示词回看条）、
KeyInputPanel（KEY 输入面板）、HistoryStrip/HistoryTable（历史条/表格）、
VideoPlayer/AudioPlayer（视频/语音播放器）、DropZone（上传区）。
"""

from ui.widgets.param_panel import KeyWarnBar, ModelBar, ParamPanel
from ui.widgets.preview_grid import PreviewGrid
from ui.widgets.prompt_echo import PromptEcho
from ui.widgets.key_input import KeyInputPanel
from ui.widgets.history_bar import HistoryStrip, HistoryTable
from ui.widgets.video_player import VideoPlayer
from ui.widgets.audio_player import AudioPlayer
from ui.widgets.drop_zone import DropZone
from ui.widgets.elapsed_timer import ElapsedTimer

__all__ = [
    "AudioPlayer", "DropZone", "ElapsedTimer", "HistoryStrip", "HistoryTable",
    "KeyInputPanel", "KeyWarnBar", "ModelBar", "ParamPanel",
    "PreviewGrid", "PromptEcho", "VideoPlayer",
]
