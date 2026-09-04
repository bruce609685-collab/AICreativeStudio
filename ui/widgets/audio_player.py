"""语音预览播放器（还原 .audio-player：波形示意 + 真实元数据 + 控制）。

界面构成：40 根蓝色竖条的装饰性波形图、时长/采样率/格式三项统计、
控制按钮行（⏮ ▶播放 ⏭ 🖥）。播放不内置解码器，而是调用系统
播放器打开文件（QDesktopServices）。

M1：静态示意；M3：load(path) 读取 WAV 真实时长/采样率/格式，
播放按钮用系统播放器打开（mock 产出的 WAV 是真实可播文件）。
"""

import math
import random
import wave
from pathlib import Path

from PySide6.QtCore import QUrl, Qt, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget,
)


def _read_wav_meta(path: str) -> tuple[float, int, str]:
    """返回 (时长秒, 采样率, 格式名)；读失败返回 (0, 0, "-")。

    参数：path: WAV 文件路径。
    返回：三元组 (时长, 采样率, 格式名)。
    """
    try:
        with wave.open(str(path), "rb") as w:
            frames = w.getnframes()
            rate = w.getframerate()
            dur = frames / rate if rate else 0.0
            return dur, rate, "WAV"
    except (wave.Error, OSError):
        return 0.0, 0, "-"


class AudioPlayer(QWidget):
    """还原预览文档语音页的预览区：波形 + 统计 + 控制按钮。

    上一首/下一首（⏮/⏭）本控件不持有播放列表，切换行为由宿主
    （语音页的 HistoryTable）通过 navigate_prev/navigate_next 信号
    实现按历史记录顺序切换。
    """

    # 信号：用户点击 ⏮ / ⏭，宿主负责切换上一条/下一条历史记录
    navigate_prev = Signal()
    navigate_next = Signal()

    def __init__(self, parent=None) -> None:
        """构建波形示意、统计区与控制按钮。"""
        super().__init__(parent)
        self._file = ""   # 当前加载的产物文件路径

        box = QFrame()
        box.setStyleSheet(
            "border:1px solid #d4d4d4; background:#f8f8f8; border-radius:1px;"
        )
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(box)

        v = QVBoxLayout(box)
        v.setContentsMargins(12, 12, 12, 12)
        v.setSpacing(8)

        # 波形示意：40 根蓝色竖条（复刻预览文档 JS 生成逻辑）
        wave_row = QWidget()
        wave_row.setFixedHeight(48)
        row = QHBoxLayout(wave_row)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(2)
        rng = random.Random(42)                    # 固定种子，截图稳定
        for i in range(40):
            bar = QWidget()
            # 高度 = 正弦波形 + 少量随机抖动，前 16 根全透明度（模拟已播放）
            height = int(abs(math.sin(i * 0.28)) * 18 + rng.random() * 10 + 8)
            bar.setFixedSize(3, height)
            opacity = 1.0 if i < 16 else 0.25
            bar.setStyleSheet(
                f"background:rgba(0,120,212,{opacity}); border-radius:1px; border:none;"
            )
            row.addWidget(bar, alignment=Qt.AlignmentFlag.AlignCenter)
        v.addWidget(wave_row, alignment=Qt.AlignmentFlag.AlignHCenter)

        # 时长 / 采样率 / 格式 统计（M3：真实数据）
        stats = QHBoxLayout()
        stats.setSpacing(20)
        self._stat_labels: dict[str, QLabel] = {}
        for key, caption in (("dur", "时长"), ("rate", "采样率"), ("fmt", "格式")):
            cell = QWidget()
            cv = QVBoxLayout(cell)
            cv.setContentsMargins(0, 0, 0, 0)
            cv.setSpacing(0)
            big = QLabel("0:00")
            big.setAlignment(Qt.AlignmentFlag.AlignHCenter)
            big.setStyleSheet("font-size:16px; font-weight:700; border:none;")
            small = QLabel(caption)
            small.setAlignment(Qt.AlignmentFlag.AlignHCenter)
            small.setStyleSheet("font-size:12px; color:#666; border:none;")
            cv.addWidget(big)
            cv.addWidget(small)
            self._stat_labels[key] = big
            stats.addWidget(cell)
        v.addLayout(stats)
        v.setAlignment(stats, Qt.AlignmentFlag.AlignHCenter)

        # 控制按钮：⏮ ▶播放 ⏭ 🖥（⏮⏭ 发信号由宿主切换上一条/下一条历史）
        controls = QHBoxLayout()
        controls.setSpacing(7)
        self._prev = QPushButton("⏮")
        self._prev.setToolTip("上一条历史语音")
        self._play = QPushButton("▶ 播放")
        self._play.setProperty("class", "primary")
        self._play.setStyleSheet("padding:5px 20px;")
        self._play.setToolTip("用系统播放器打开")
        # 信号槽：点播放 → 系统播放器打开当前文件
        self._play.clicked.connect(self._open_external)
        self._next = QPushButton("⏭")
        self._next.setToolTip("下一条历史语音")
        sys_btn = QPushButton("🖥")
        sys_btn.setToolTip("用系统播放器打开产物文件")
        sys_btn.clicked.connect(self._open_external)
        # 信号槽：上一首/下一首 → 发出导航信号，宿主切换历史记录
        self._prev.clicked.connect(self.navigate_prev.emit)
        self._next.clicked.connect(self.navigate_next.emit)
        controls.addStretch(1)
        for b in (self._prev, self._play, self._next, sys_btn):
            controls.addWidget(b)
        controls.addStretch(1)
        v.addLayout(controls)

    # ------------------------------------------------------------------

    def load(self, path: str) -> None:
        """加载 WAV 产物，刷新真实元数据。

        参数：path: WAV 文件路径。
        """
        self._file = str(path)
        dur, rate, fmt = _read_wav_meta(path)
        mins, secs = divmod(int(dur), 60)
        self._stat_labels["dur"].setText(f"{mins}:{secs:02d}")
        # 采样率显示成 "24k" 形式
        self._stat_labels["rate"].setText(f"{rate // 1000}k" if rate else "-")
        self._stat_labels["fmt"].setText(fmt)

    def current_file(self) -> str:
        """返回当前加载的文件路径。"""
        return self._file

    def open_external(self) -> None:
        """用系统默认播放器打开当前文件（公开接口，宿主页面调用）。"""
        self._open_external()

    def _open_external(self) -> None:
        """用系统默认播放器打开当前文件（无文件时静默忽略）。"""
        if self._file:
            QDesktopServices.openUrl(QUrl.fromLocalFile(self._file))
