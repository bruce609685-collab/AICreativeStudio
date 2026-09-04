"""弹窗集合：通用确认框、完备性门闸弹窗、导入预览弹窗。

对外统一暴露，导入页等通过 ui.dialogs import 直接使用。
"""

from ui.dialogs.confirm_dialog import GapOptionalDialog, GapRequiredDialog, confirm
from ui.dialogs.import_preview_dialog import ImportPreviewDialog

__all__ = ["GapOptionalDialog", "GapRequiredDialog", "ImportPreviewDialog", "confirm"]
