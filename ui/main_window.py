"""主窗口：标题、页签容器、状态栏。

这是整个程序的"外壳"：负责把六个功能页签（AI生图片 / AI生视频 / AI生语音 /
模型设置 / 智能导入 / 关于）组装到一个 QTabWidget 里，并提供底部状态栏。
页签之间不直接互相调用，而是通过本窗口提供的对外 API（show_status 显示
临时提示、switch_tab 程序化跳转页签）进行联动——例如"智能导入"完成后
会自动跳转到"模型设置"页提醒用户填写 API KEY。

对应预览文档的 .window（1280×800）+ .tab-bar + .status-bar。
"""

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QLabel, QMainWindow, QTabWidget, QWidget

import about
from core.registry import ScriptRegistry
from core.services import HistoryDatabase
from ui.icons import symbol_icon
from ui.pages.about_page import AboutPage
from ui.pages.audio_page import AudioPage
from ui.pages.image_page import ImagePage
from ui.pages.import_page import ImportPage
from ui.pages.settings_page import SettingsPage
from ui.pages.video_page import VideoPage

# 窗口默认尺寸（像素），与预览文档一致
WINDOW_WIDTH = 1280
WINDOW_HEIGHT = 800

# 状态栏默认文本：任务结束后 2 秒自动回到"就绪"
STATUS_READY = "就绪"


class MainWindow(QMainWindow):
    """外壳主窗口：六个页签 + 底部状态栏。

    各功能页通过 main_window 引用调用 show_status / switch_tab，
    本窗口不包含具体业务逻辑，只负责"组装 + 页签联动 + 状态提示"。
    """

    def __init__(self, registry: ScriptRegistry | None = None,
                 db: HistoryDatabase | None = None) -> None:
        """构造主窗口。

        参数：
            registry: 脚本注册表（传给各生成页/设置页/导入页使用），可为 None
            db: 历史记录数据库（传给各生成页落库历史），可为 None
        """
        super().__init__()
        self._registry = registry
        self._db = db
        self.setWindowTitle(about.APP_NAME)
        # 允许最小化/最大化按钮
        self.setWindowFlag(Qt.WindowType.WindowMinMaxButtonsHint, True)
        self.resize(WINDOW_WIDTH, WINDOW_HEIGHT)
        # 窗口最小尺寸，防止布局被压得太小
        self.setMinimumSize(1024, 680)

        # 中央页签容器：documentMode 让页签栏更贴合窗口边框（浏览器式外观）
        self._tabs = QTabWidget()
        self._tabs.setDocumentMode(True)
        self.setCentralWidget(self._tabs)

        self._build_pages()
        self._build_status_bar()

    # ------------------------------------------------------------------
    # 构建
    # ------------------------------------------------------------------

    def _build_pages(self) -> None:
        """六个页签：生图片 / 生视频 / 生语音 / 模型设置 / 智能导入 / 关于。

        图标用 icons.symbol_icon 渲染成图片挂上去，而不是直接写 emoji 字符：
        Windows 上 Qt 对符号字体的回退不稳定，直接写字符会出现方块（豆腐块）。
        """
        pages = [
            (ImagePage(self, self._registry, self._db), "  AI生图片", "🖼"),
            (VideoPage(self, self._registry, self._db), "  AI生视频", "🎬"),
            (AudioPage(self, self._registry, self._db), "  AI生语音", "🎙"),
            (SettingsPage(self, self._registry), "  模型设置", "⚙"),
            (ImportPage(self, self._registry), "  智能导入", "📥"),
            (AboutPage(self, self._registry), "  关于", "ℹ"),
        ]
        for page, title, symbol in pages:
            index = self._tabs.addTab(page, title)
            # 图标尺寸按页签行高给，32px 渲染足够清晰又不糊
            self._tabs.setTabIcon(index, symbol_icon(symbol, "#333333", 32))

    def _build_status_bar(self) -> None:
        """左：可变状态文本；右：脚本数 / 模板版本 / 程序版本。

        另建一个单次触发的 QTimer：show_status 显示临时消息后，
        到时自动把左侧文本复位为"就绪"。
        """
        bar = self.statusBar()

        # 左侧：可变状态文本（各页通过 show_status 更新）
        self._status_label = QLabel(STATUS_READY)
        bar.addWidget(self._status_label)

        # 右侧：常驻信息（脚本数 / 模板版本 / 程序版本），用竖线分隔更易读
        right = QLabel()
        right.setAlignment(Qt.AlignmentFlag.AlignRight)
        bar.addPermanentWidget(right)
        self._status_right = right
        self.refresh_status_info()   # 统一由这个方法生成文案（避免两处格式不一致）

        # 单次定时器：临时消息超时后自动复位为"就绪"
        self._status_timer = QTimer(self)
        self._status_timer.setSingleShot(True)
        self._status_timer.timeout.connect(lambda: self._status_label.setText(STATUS_READY))

    def refresh_status_info(self) -> None:
        """重算右侧常驻信息（脚本数会随导入/删除变化，模板/版本不变）。

        原实现脚本数只在窗口构造时算一次，导入或删除脚本后状态栏
        一直显示旧数字；本方法供各页在脚本变动后调用刷新。
        """
        script_count = self._registry.count() if self._registry else 0
        # 用 " │ " 分隔三段信息，比连续空格更清晰（与 UI 预览稿一致）
        self._status_right.setText(
            f"脚本：{script_count} 个  │  模板 {about.TEMPLATE_VERSION}"
            f"  │  v{about.APP_VERSION}")

    # ------------------------------------------------------------------
    # 对外 API（各页调用）
    # ------------------------------------------------------------------

    def show_status(self, text: str, reset_ms: int = 2000) -> None:
        """状态栏临时消息；reset_ms=0 表示不自动复位（长任务期间用）。

        参数：
            text: 要显示的提示文本
            reset_ms: 多少毫秒后恢复为"就绪"；传 0 则一直保留（如"生成中…"）
        """
        self._status_label.setText(text)
        if reset_ms > 0:
            self._status_timer.start(reset_ms)

    def switch_tab(self, index: int) -> None:
        """程序化切换页签（导入完成后跳转模型设置等场景）。

        参数：index: 页签序号，可用下方 TAB_* 常量。
        """
        self._tabs.setCurrentIndex(index)

    # 页签序号常量（供程序化跳转）：各页通过 main_window.TAB_XXX 定位目标页
    TAB_IMAGE = 0
    TAB_VIDEO = 1
    TAB_AUDIO = 2
    TAB_SETTINGS = 3
    TAB_IMPORT = 4
    TAB_ABOUT = 5

    @property
    def tab_widget(self) -> QTabWidget:
        """暴露页签容器，供其他页取到兄弟页并调用其刷新方法。"""
        return self._tabs

    @property
    def status_label(self) -> QWidget:
        """左侧状态文本控件（测试用）。"""
        return self._status_label

    @property
    def status_right_text(self) -> str:
        """状态栏右侧信息（脚本数/模板版本/程序版本），供测试断言。"""
        return self._status_right.text()
