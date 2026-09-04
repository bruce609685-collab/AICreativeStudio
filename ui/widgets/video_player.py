"""视频预览播放器（还原 .video-player 黑底 16:9，§3.2 内置播放版）。

2026-09-02 起：接入 QMediaPlayer 内置播放——产物加载后可直接在程序内
播放（进度条、播放/暂停、音量、时间显示），不再只有"封面图 + 跳系统
播放器"一种观感。外放仍保留两路：
- 🖥 系统播放：QDesktopServices 交给系统默认播放器（任何格式都行）；
- 解码失败兜底：某些容器/编码 Windows 自带解码器不支持时，内置播放器
  会报 errorOccurred，此时自动退回"封面 + 系统播放"的老行为并提示。

技术要点（PySide6 6.11）：
- QMediaPlayer + QAudioOutput：音频输出要单独建实例并挂到 player；
- QVideoWidget：视频画面渲染控件（轻量，不需要 QMediaPlayer 整套
  Widgets 后端的多余依赖）；
- 打包注意：PyInstaller 需收集 PySide6 的 QtMultimedia 相关 DLL 与
  mediaservice 插件（spec 已配 collect）。
"""

from pathlib import Path

from PySide6.QtCore import QProcess, QUrl, Qt
from PySide6.QtGui import QDesktopServices
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtMultimediaWidgets import QVideoWidget
from PySide6.QtWidgets import (
    QHBoxLayout, QLabel, QPushButton, QSizePolicy, QSlider, QVBoxLayout,
    QWidget,
)

from core.deps import check_ffmpeg, FFMPEG_DIR


class VideoPlayer(QWidget):
    """黑底视频播放器：内置播放（QMediaPlayer）+ 系统播放外放双路。"""

    def __init__(self, parent=None) -> None:
        """构建播放器：视频画面 + 中央遮罩按钮 + 底部控制条。"""
        super().__init__(parent)
        self._file = ""          # 当前加载的产物文件路径
        self._duration_ms = 0    # 媒体总时长（毫秒，元数据解析后回填）
        self._user_seeking = False  # 进度条拖动中（避免拖动时被回填打断）

        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setMinimumHeight(260)
        self.setStyleSheet(
            "background:qlineargradient(x1:0, y1:0, x2:1, y2:1,"
            " stop:0 #2a2a2a, stop:1 #181818); border:none;"
        )

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # --- 视频画面区：QVideoWidget 渲染 + 中央播放遮罩 ---
        self._video = QVideoWidget()
        self._video.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        outer.addWidget(self._video, stretch=1)

        # 中央播放/暂停大按钮（半透明圆形，盖在画面上）
        self._big_btn = QPushButton("▶", self._video)
        self._big_btn.setFixedSize(52, 52)
        self._big_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._big_btn.setStyleSheet(
            "border-radius:26px; background:rgba(255,255,255,0.25);"
            " color:#ffffff; font-size:20px;"
            " border:2px solid rgba(255,255,255,0.5);"
        )
        self._big_btn.setToolTip("播放 / 暂停")
        self._big_btn.clicked.connect(self._toggle_play)

        # --- 底部控制条：播放钮 + 进度条 + 时间 + 音量 + 系统播放 ---
        bar = QWidget()
        bar.setStyleSheet("background:rgba(0,0,0,0.6); border:none;")
        bar.setFixedHeight(34)
        row = QHBoxLayout(bar)
        row.setContentsMargins(8, 0, 8, 0)
        row.setSpacing(6)

        self._play_btn = QPushButton("▶")
        self._play_btn.setFixedSize(26, 22)
        self._play_btn.setToolTip("播放 / 暂停")
        self._play_btn.setStyleSheet(
            "color:#ffffff; border:1px solid rgba(255,255,255,0.4);"
            " background:transparent; font-size:11px; padding:0;"
        )
        self._play_btn.clicked.connect(self._toggle_play)

        # 进度条：0-1000 刻度（QSlider 惯例，粒度足够且平滑）
        self._seek = QSlider(Qt.Orientation.Horizontal)
        self._seek.setRange(0, 1000)
        self._seek.setValue(0)
        self._seek.setStyleSheet(
            "QSlider::groove:horizontal{height:4px; background:rgba(255,255,255,0.25);}"
            "QSlider::handle:horizontal{width:10px; margin:-5px 0;"
            " background:#ffffff; border-radius:5px;}"
            "QSlider::sub-page:horizontal{background:#0078d4;}"
        )
        # 信号槽：按下=暂停回填、拖动=记状态、松手=真正跳转
        self._seek.sliderPressed.connect(lambda: setattr(self, "_user_seeking", True))
        self._seek.sliderReleased.connect(self._on_seek_released)
        self._seek.sliderMoved.connect(
            lambda v: self._time_label.setText(
                f"{self._fmt(v / 1000 * self._duration_ms)} / {self._fmt(self._duration_ms)}")
        )

        self._time_label = QLabel("00:00 / 00:00")
        self._time_label.setStyleSheet(
            "color:#ffffff; font-size:10px; border:none; background:transparent;")

        # 音量：图标 + 竖排改横排小滑条
        vol_icon = QLabel("🔊")
        vol_icon.setStyleSheet(
            "font-size:11px; border:none; background:transparent;")
        self._volume = QSlider(Qt.Orientation.Horizontal)
        self._volume.setRange(0, 100)
        self._volume.setValue(80)
        self._volume.setFixedWidth(64)
        self._volume.setToolTip("音量")
        self._volume.setStyleSheet(
            "QSlider::groove:horizontal{height:3px; background:rgba(255,255,255,0.25);}"
            "QSlider::handle:horizontal{width:8px; margin:-4px 0;"
            " background:#ffffff; border-radius:4px;}"
        )
        self._volume.valueChanged.connect(
            lambda v: self._audio.setVolume(v / 100.0))

        sys_btn = QPushButton("🖥 系统播放")
        sys_btn.setToolTip("用系统播放器打开产物文件")
        sys_btn.setStyleSheet(
            "color:#ffffff; border:1px solid rgba(255,255,255,0.4);"
            " background:transparent; font-size:11px; padding:2px 8px;"
        )
        sys_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        sys_btn.clicked.connect(self.open_external)

        # §3.2 FFplay 外放（依赖 FFmpeg）：装了 FFmpeg 才显示此按钮；
        # FFplay 是 FFmpeg 自带的轻量播放器，逐帧/调试看视频很方便
        self._ffplay_btn = QPushButton("FFplay")
        self._ffplay_btn.setToolTip("用 FFplay 播放（需在「关于」页安装 FFmpeg）")
        self._ffplay_btn.setStyleSheet(
            "color:#ffffff; border:1px solid rgba(255,255,255,0.4);"
            " background:transparent; font-size:11px; padding:2px 8px;"
        )
        self._ffplay_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._ffplay_btn.clicked.connect(self._open_ffplay)
        self._ffplay_btn.setVisible(check_ffmpeg())

        row.addWidget(self._play_btn)
        row.addWidget(self._seek, stretch=1)
        row.addWidget(self._time_label)
        row.addWidget(vol_icon)
        row.addWidget(self._volume)
        row.addWidget(sys_btn)
        row.addWidget(self._ffplay_btn)
        outer.addWidget(bar)

        # --- 媒体播放核心对象 ---
        self._audio = QAudioOutput()
        self._audio.setVolume(0.8)
        self._player = QMediaPlayer()
        self._player.setAudioOutput(self._audio)
        self._player.setVideoOutput(self._video)
        # 信号槽：状态/进度/时长/错误 四类事件驱动界面刷新
        self._player.playbackStateChanged.connect(self._on_state)
        self._player.positionChanged.connect(self._on_position)
        self._player.durationChanged.connect(self._on_duration)
        self._player.errorOccurred.connect(self._on_error)

        self._file_label = QLabel("未加载产物")
        self._file_label.setStyleSheet(
            "color:#ffffff; font-size:10px; border:none; background:transparent;")

    # ------------------------------------------------------------------
    # 公开接口（宿主页面调用）
    # ------------------------------------------------------------------

    def load(self, path: str) -> None:
        """加载产物文件：内置播放器就绪 + 文件名提示。

        参数：path: 产物文件路径。
        """
        self._file = str(path)
        self._file_label.setText(Path(path).name)
        self._file_label.setToolTip(self._file)
        self._duration_ms = 0
        self._seek.setValue(0)
        self._time_label.setText("00:00 / 00:00")
        self._player.setSource(QUrl.fromLocalFile(self._file))
        self._big_btn.show()

    def clear(self) -> None:
        """清空播放器：停止播放、释放媒体源、恢复初始状态。"""
        self._player.stop()
        self._player.setSource(QUrl())
        self._file = ""
        self._file_label.setText("未加载产物")
        self._time_label.setText("00:00 / 00:00")
        self._seek.setValue(0)
        self._big_btn.show()

    def current_file(self) -> str:
        """返回当前加载的文件路径。"""
        return self._file

    def open_external(self) -> None:
        """用系统默认播放器打开当前文件（公开接口，无文件时静默）。"""
        if self._file:
            QDesktopServices.openUrl(QUrl.fromLocalFile(self._file))

    def _ffplay_exe(self) -> str:
        """定位 ffplay.exe：优先 PATH，其次 data/ffmpeg/ 递归找。"""
        import shutil as _shutil
        import os as _os
        found = _shutil.which("ffplay")
        if found:
            return found
        if FFMPEG_DIR.is_dir():
            for exe in FFMPEG_DIR.rglob("ffplay.exe"):
                if exe.is_file():
                    return str(exe)
        return _os.environ.get("FFPLAY", "")

    def _open_ffplay(self) -> None:
        """用 FFplay 播放当前文件（独立子进程，不阻塞界面）。

        ffplay 参数：-autoexit 播完自动关窗、-window_title 窗口标题。
        未找到 ffplay 时状态提示走按钮隐藏逻辑，这里静默兜底。
        """
        if not self._file:
            return
        exe = self._ffplay_exe()
        if not exe:
            self._ffplay_btn.hide()   # 环境变化导致失效 → 隐藏按钮
            return
        QProcess.startDetached(exe, ["-autoexit", "-window_title",
                                     Path(self._file).name, self._file])

    # ------------------------------------------------------------------
    # 内部：播放控制与事件
    # ------------------------------------------------------------------

    def _toggle_play(self) -> None:
        """播放/暂停切换（无文件时忽略）。"""
        if not self._file:
            return
        if self._player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self._player.pause()
        else:
            self._player.play()

    def _on_state(self, state: QMediaPlayer.PlaybackState) -> None:
        """播放状态变化 → 同步两个播放按钮的文字。"""
        playing = state == QMediaPlayer.PlaybackState.PlayingState
        text = "⏸" if playing else "▶"
        self._play_btn.setText(text)
        self._big_btn.setText(text)
        self._big_btn.setVisible(not playing or True)  # 播放中保留按钮可暂停

    def _on_position(self, pos_ms: int) -> None:
        """播放进度回填进度条与时间显示（拖动中不回填，避免打架）。"""
        if self._user_seeking or self._duration_ms <= 0:
            return
        self._seek.setValue(int(pos_ms / self._duration_ms * 1000))
        self._time_label.setText(
            f"{self._fmt(pos_ms)} / {self._fmt(self._duration_ms)}")

    def _on_duration(self, dur_ms: int) -> None:
        """媒体总时长就绪（元数据解析完成后触发一次）。"""
        self._duration_ms = dur_ms

    def _on_seek_released(self) -> None:
        """进度条松手：按滑条位置跳转播放，并恢复进度回填。"""
        self._user_seeking = False
        if self._duration_ms > 0:
            self._player.setPosition(
                int(self._seek.value() / 1000 * self._duration_ms))

    def _on_error(self, err, err_str: str) -> None:
        """内置解码失败兜底：提示用户改用系统播放（不崩、不静默）。"""
        if err != QMediaPlayer.Error.NoError and self._file:
            self._file_label.setText(
                f"内置播放不支持该格式，请点\"🖥 系统播放\"（{Path(self._file).name}）")

    @staticmethod
    def _fmt(ms: int) -> str:
        """毫秒 → "mm:ss" 显示格式。"""
        s = int(ms // 1000)
        return f"{s // 60:02d}:{s % 60:02d}"

    def resizeEvent(self, event) -> None:  # noqa: N802（Qt 命名）
        """窗口缩放时让中央按钮保持在画面正中。"""
        super().resizeEvent(event)
        self._reposition_big_btn()

    def _reposition_big_btn(self) -> None:
        """把中央播放按钮摆到视频画面几何中心。"""
        g = self._video.geometry()
        self._big_btn.move(
            g.x() + (g.width() - self._big_btn.width()) // 2,
            g.y() + (g.height() - self._big_btn.height()) // 2,
        )
