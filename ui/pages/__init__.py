"""六个页签：生图片 / 生视频 / 生语音 / 模型设置 / 智能导入 / 关于。

每个页对应一个独立模块，均以 QWidget 子类实现，由 ui/main_window.py
统一组装进主窗口的 QTabWidget。
"""

__all__ = [
    "AboutPage", "AudioPage", "ImagePage", "ImportPage",
    "SettingsPage", "VideoPage",
]
