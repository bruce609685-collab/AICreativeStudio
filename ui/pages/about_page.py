"""关于页（还原预览文档 page-about）。展示程序信息 + 依赖项 + 更新日志。

界面自上而下：程序图标/名称/版本头部、程序信息卡片（名称/版本/构建日期/
发布地址）、安装依赖项卡片（FFmpeg + 各脚本的 pip 依赖，检测已装/未装）、
更新日志卡片。

依赖安装走 QThread 后台线程（_FfmpegWorker 下载 FFmpeg、_PipWorker
执行 pip install），进度与结果通过信号回传 UI 线程，安装期间界面不卡死。

M6 升级：依赖卡片从注册表读取真实 pip_requires 列表 + 检测状态；
安装按钮真走 core/deps 的 install_pip / download_ffmpeg（QThread 后台）。
"""

from PySide6.QtCore import QThread, Signal, Qt
from PySide6.QtWidgets import (
    QFrame, QGroupBox, QHBoxLayout, QLabel, QProgressBar, QPushButton,
    QScrollArea, QVBoxLayout, QWidget,
)

import about
from core.deps import (
    check_ffmpeg, download_ffmpeg, install_pip, list_missing,
)
from core.registry import ScriptRegistry


class _FfmpegWorker(QThread):
    """后台下载 FFmpeg，进度与结果通过信号回传。

    线程安全：run() 在子线程执行，下载回调只 emit 信号，
    界面更新全部在 UI 线程的槽函数里完成。
    """

    progress = Signal(int, int)  # current, total（已下载字节 / 总字节）
    done = Signal(bool)          # 下载是否成功

    def run(self) -> None:
        """子线程入口：执行下载，进度经 progress 信号、结果经 done 信号回传。"""
        def cb(current: int, total: int) -> None:
            self.progress.emit(current, total)

        ok = download_ffmpeg(progress_cb=cb)
        self.done.emit(ok)


class _PipWorker(QThread):
    """后台 pip install，结果通过信号回传。"""

    done = Signal(bool, str)  # ok, package（安装结果 + 包名）

    def __init__(self, package: str, parent=None) -> None:
        """记录要安装的包名。

        参数：package: pip 包名。
        """
        super().__init__(parent)
        self._pkg = package

    def run(self) -> None:
        """子线程入口：执行 pip 安装，结果经 done 信号回传。"""
        ok = install_pip(self._pkg)
        self.done.emit(ok, self._pkg)


# 更新日志数据：(版本, 日期, [更新条目...])
CHANGELOG = [
    ("v0.3", "2026-09-04", [
        "使用 Kimi K3 和 GLM-5.3 进行重构，首个公开版本",
    ]),
    ("v0.2", "2026-08-20", [
        "大幅度修改软件框架，由程序执行改为脚本执行",
    ]),
    ("v0.1", "2026-07-14", [
        "初始版本",
    ]),
]


class AboutPage(QWidget):
    """关于页：程序信息 + 依赖安装（后台线程）+ 更新日志。"""

    def __init__(self, main_window, registry: ScriptRegistry | None = None,
                 parent=None) -> None:
        """构造关于页。

        参数：
            main_window: 主窗口引用（状态栏提示）
            registry: 脚本注册表（收集 pip_requires 用），可为 None
        """
        super().__init__(parent)
        self._main = main_window
        self._registry = registry
        self._ff_worker: _FfmpegWorker | None = None      # FFmpeg 下载线程
        self._pip_workers: list[_PipWorker] = []          # 进行中的 pip 安装线程

        # 整页套滚动区，内容居中限宽
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        inner = QWidget()
        inner.setMaximumWidth(620)
        v = QVBoxLayout(inner)
        v.setContentsMargins(14, 14, 14, 14)
        v.setSpacing(9)
        v.setAlignment(Qt.AlignmentFlag.AlignHCenter)

        v.addWidget(self._build_header())
        v.addWidget(self._build_info_card())
        v.addWidget(self._build_deps_card())
        v.addWidget(self._build_changelog_card())

        # 版权页脚
        footer = QLabel(f"© 2026 {about.AUTHOR} · {about.LICENSE}")
        footer.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        footer.setStyleSheet("font-size:11px; color:#aaa;")
        v.addWidget(footer)

        scroll.setWidget(inner)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(scroll)

    # ------------------------------------------------------------------

    def _build_header(self) -> QWidget:
        """构建头部：渐变色图标 + 程序名 + 版本 + 模板/文档规格。

        返回：头部 QWidget。
        """
        w = QWidget()
        v = QVBoxLayout(w)
        v.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        v.setSpacing(2)
        # "AI" 字样的渐变圆角图标
        ico = QLabel("AI")
        ico.setFixedSize(52, 52)
        ico.setAlignment(Qt.AlignmentFlag.AlignCenter)
        ico.setStyleSheet(
            "background:qlineargradient(x1:0, y1:0, x2:1, y2:1,"
            " stop:0 #0078d4, stop:1 #6C5CE7); border-radius:12px;"
            " color:#ffffff; font-size:22px; font-weight:800;"
        )
        title = QLabel(about.APP_NAME)
        title.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        title.setStyleSheet("font-size:18px; font-weight:700;")
        ver = QLabel(f"版本 {about.APP_VERSION} · Build {about.BUILD_DATE}")
        ver.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        ver.setStyleSheet("font-size:13px; color:#888;")
        spec = QLabel(
            f"提示词模板 {about.TEMPLATE_VERSION} · 文档规格 {about.DOC_SPEC}"
        )
        spec.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        spec.setStyleSheet("font-size:11px; color:#aaa;")
        v.addWidget(ico, alignment=Qt.AlignmentFlag.AlignHCenter)
        v.addWidget(title)
        v.addWidget(ver)
        v.addWidget(spec)
        return w

    def _build_info_card(self) -> QGroupBox:
        """构建"程序信息"卡片：名称/版本/构建日期/发布地址逐行展示。

        返回：信息卡片 QGroupBox。
        """
        card = QGroupBox("程序信息")
        v = QVBoxLayout(card)
        rows = [
            ("程序名称", f"{about.APP_NAME}（AI Creative Studio）"),
            ("当前版本", about.APP_VERSION),
            ("构建日期", about.BUILD_DATE),
        ]
        for label, value in rows:
            row = QHBoxLayout()
            key = QLabel(label)
            key.setFixedWidth(88)
            key.setStyleSheet(
                "font-size:13px; color:#666; font-weight:600; border:none;")
            val = QLabel(value)
            val.setStyleSheet("font-size:13px; color:#1a1a1a; border:none;")
            val.setWordWrap(True)
            row.addWidget(key)
            row.addWidget(val, stretch=1)
            v.addLayout(row)
        # 发布地址：可点击超链接（浏览器打开）
        link_row = QHBoxLayout()
        link_key = QLabel("发布地址")
        link_key.setFixedWidth(88)
        link_key.setStyleSheet(
            "font-size:13px; color:#666; font-weight:600; border:none;")
        link_val = QLabel(
            f'<a href="{about.RELEASE_URL}">{about.RELEASE_URL}</a>')
        link_val.setOpenExternalLinks(True)
        link_val.setStyleSheet(
            "font-size:13px; border:none;")
        link_val.setWordWrap(True)
        link_row.addWidget(link_key)
        link_row.addWidget(link_val, stretch=1)
        v.addLayout(link_row)
        return card

    # ------------------------------------------------------------------
    # 依赖卡片
    # ------------------------------------------------------------------

    def _collect_script_pip_requires(self) -> list[str]:
        """从注册表收集所有脚本的 pip_requires，去重。

        返回：去重后的 pip 包名列表（小写）。
        """
        if self._registry is None:
            return []
        seen: set[str] = set()
        result: list[str] = []
        for meta in self._registry.all:
            for pkg in meta.pip_requires:
                p = pkg.strip().lower()
                if p and p not in seen:
                    seen.add(p)
                    result.append(p)
        return result

    def _build_deps_card(self) -> QGroupBox:
        """构建"安装依赖项"卡片：FFmpeg + 各脚本 pip 依赖 + 内嵌库说明。

        每项显示安装状态；未安装项带"⬇ 安装"按钮（点击后台安装）。

        返回：依赖卡片 QGroupBox。
        """
        card = QGroupBox("安装依赖项")
        v = QVBoxLayout(card)
        intro = QLabel(
            "安装脚本或播放所需的第三方组件。内嵌库（requests / httpx / Pillow）"
            "一般无需安装。扫描脚本「pip_requires」字段自动列出缺失包。"
        )
        intro.setStyleSheet("font-size:12px; color:#666;")
        intro.setWordWrap(True)
        v.addWidget(intro)

        # FFmpeg：检测已装/未装，未装显示下载按钮与进度条
        ffmpeg_ok = check_ffmpeg()
        self._ff_status = QLabel(
            "已安装 · 可在程序内播放视频" if ffmpeg_ok
            else "未安装 · 安装后可在程序内播放视频"
        )
        self._ff_bar = QProgressBar()
        self._ff_bar.setFixedHeight(4)
        self._ff_bar.setTextVisible(False)
        self._ff_bar.hide()
        v.addWidget(self._build_dep_item(
            "FFmpeg（含 ffplay）", self._ff_status,
            "已安装" if ffmpeg_ok else "⬇ 安装 FFmpeg",
            self._install_ffmpeg if not ffmpeg_ok else None,
        ))
        v.addWidget(self._ff_bar)

        # 脚本 pip 依赖项：从注册表收集，检测缺失后逐项列出
        pip_reqs = self._collect_script_pip_requires()
        installed = [p for p in pip_reqs if p not in list_missing(pip_reqs)]
        missing = list_missing(pip_reqs)

        for pkg in sorted(set(pip_reqs)):
            is_ok = pkg in installed
            item = self._build_dep_item(
                pkg,
                QLabel("已安装" if is_ok else "未安装"),
                "已安装" if is_ok else "⬇ 安装",
                self._make_install_cb(pkg) if not is_ok else None,
            )
            v.addWidget(item)

        # 内嵌库：随程序提供，无需安装（按钮禁用）
        v.addWidget(self._build_dep_item(
            "requests / httpx / Pillow",
            QLabel("已随程序提供（内嵌）"),
            "无需安装",
            enabled=False,
        ))

        if not pip_reqs:
            v.addWidget(QLabel("（当前脚本无额外 pip 依赖）"))
        return card

    def _build_dep_item(self, name: str, status: QLabel | None = None,
                        btn_text: str = "", on_click=None,
                        enabled: bool = True) -> QWidget:
        """构建一行依赖项：名称 + 状态文字 + 安装按钮。

        参数：
            name: 依赖名称；status: 状态文字控件；btn_text: 按钮文字；
            on_click: 按钮回调（None 表示按钮禁用）；enabled: 按钮是否可用。
        返回：依赖项 QFrame。
        """
        item = QFrame()
        item.setStyleSheet(
            "background:#f6f8fa; border:1px solid #e0e0e0; border-radius:1px;"
        )
        h = QHBoxLayout(item)
        h.setContentsMargins(10, 9, 10, 9)
        info = QWidget()
        iv = QVBoxLayout(info)
        iv.setContentsMargins(0, 0, 0, 0)
        iv.setSpacing(2)
        nm = QLabel(name)
        nm.setStyleSheet("font-size:12px; font-weight:600; border:none;")
        iv.addWidget(nm)
        if status is not None:
            iv.addWidget(status)
            # 已安装显示绿色，否则灰色
            status.setStyleSheet(
                "font-size:11px; color:"
                + ("#2e7d32" if status.text().startswith("已") else "#888")
                + "; border:none;"
            )
        h.addWidget(info, stretch=1)
        btn = QPushButton(btn_text)
        if on_click is not None:
            btn.setProperty("class", "primary")
            btn.setStyleSheet("font-size:11px; padding:2px 5px;")
            btn.clicked.connect(on_click)
        else:
            btn.setStyleSheet("font-size:11px; padding:2px 5px; opacity:0.5;")
        # 无回调（已安装/无需安装）的按钮必须保持禁用——原来先 setEnabled(False)
        # 又被末行 setEnabled(enabled) 重新启用，导致"已安装"按钮可点但没反应
        btn.setEnabled(enabled and on_click is not None)
        h.addWidget(btn)
        return item

    # ------------------------------------------------------------------
    # 安装逻辑
    # ------------------------------------------------------------------

    def _install_ffmpeg(self) -> None:
        """启动 FFmpeg 后台下载：显示进度条，重复点击直接忽略。"""
        if self._ff_worker is not None:
            return
        self._ff_bar.show()
        self._ff_bar.setValue(0)
        self._ff_status.setText("准备下载…")
        self._ff_worker = _FfmpegWorker(self)
        # 信号槽：下载进度 → 进度条；下载完成 → 更新状态
        self._ff_worker.progress.connect(self._on_ffmpeg_progress)
        self._ff_worker.done.connect(self._on_ffmpeg_done)
        self._ff_worker.start()

    def _on_ffmpeg_progress(self, current: int, total: int) -> None:
        """FFmpeg 下载进度回调（UI 线程）：更新进度条与状态文字。

        参数：current: 已下载字节；total: 总字节。
        """
        pct = min(int(current / max(total, 1) * 100), 100)
        self._ff_bar.setValue(pct)
        self._ff_status.setText(f"下载中… {pct}%")

    def _on_ffmpeg_done(self, ok: bool) -> None:
        """FFmpeg 下载完成回调（UI 线程）：按成败更新状态文字。

        参数：ok: 下载是否成功。
        """
        self._ff_worker = None
        if ok:
            self._ff_status.setText("已安装 · 可在程序内播放视频")
            self._ff_status.setStyleSheet(
                "font-size:11px; color:#2e7d32; border:none;")
            self._main.show_status("FFmpeg 安装完成，已可通过系统播放器播放视频", 3000)
        else:
            self._ff_status.setText("安装失败 · 请检查网络连接后重试")
            self._ff_status.setStyleSheet(
                "font-size:11px; color:#d32f2f; border:none;")
            self._main.show_status("FFmpeg 安装失败，请检查网络连接", 4000)
        self._ff_bar.hide()

    def _make_install_cb(self, pkg: str):
        """为 pip 包创建安装回调（工厂函数）。

        同一个包已在安装中时忽略重复点击。

        参数：pkg: pip 包名。
        返回：可连接到按钮 clicked 的回调函数。
        """
        def cb():
            if any(w._pkg == pkg for w in self._pip_workers if w.isRunning()):
                return
            worker = _PipWorker(pkg, self)
            # 信号槽：安装完成 → 状态栏提示
            worker.done.connect(self._on_pip_done)
            self._pip_workers.append(worker)
            worker.start()
            self._main.show_status(f"正在安装 {pkg}…", 0)
        return cb

    def _on_pip_done(self, ok: bool, pkg: str) -> None:
        """pip 安装完成回调（UI 线程）：清理已结束线程并提示结果。

        参数：ok: 安装是否成功；pkg: 包名。
        """
        self._pip_workers = [w for w in self._pip_workers if not w.isFinished()]
        if ok:
            self._main.show_status(f"✅ {pkg} 安装完成", 3000)
        else:
            self._main.show_status(f"❌ {pkg} 安装失败", 4000)

    # ------------------------------------------------------------------
    # 更新日志
    # ------------------------------------------------------------------

    def _build_changelog_card(self) -> QGroupBox:
        """构建"更新日志"卡片：按版本分组渲染 CHANGELOG 数据。

        返回：更新日志卡片 QGroupBox。
        """
        card = QGroupBox("更新日志")
        v = QVBoxLayout(card)
        for version, date, items in CHANGELOG:
            # 版本徽标 + 日期一行
            row = QHBoxLayout()
            tag = QLabel(version)
            tag.setStyleSheet(
                "background:#e5f1fb; color:#0078d4; padding:1px 6px;"
                " font-size:11px; font-weight:700; border-radius:2px;"
            )
            row.addWidget(tag)
            d = QLabel(date)
            d.setStyleSheet("font-size:11px; color:#888;")
            row.addWidget(d)
            row.addStretch(1)
            v.addLayout(row)
            # 各更新条目（缩进列表）
            for item in items:
                li = QLabel("• " + item)
                li.setStyleSheet("font-size:12px; color:#555;")
                li.setContentsMargins(14, 0, 0, 0)
                v.addWidget(li)
        return card