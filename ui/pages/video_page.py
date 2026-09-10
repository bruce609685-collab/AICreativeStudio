"""AI 生视频页（还原预览文档 page-video）。

界面布局与图片页一致：左栏"视频描述 + 生成参数（含视频时长 2-15 秒校验）
+ 生成按钮"，右栏"视频播放器 + 提示词回看 + 历史记录"。

生成流程（与图片页同构）：
  _start_generate 收集参数并写 job 任务文件 → GenerateWorker 后台线程
  执行脚本 → finished_ok/finished_err 信号回 UI 线程 → _on_gen_ok
  加载产物到播放器 / _on_gen_err 显示失败原因 → 历史落库刷新。

M1：静态演示；M3：注册表驱动参数区 + 真实生成链路（QThread 后台）+ 产物
播放（系统播放器打开）/ 打开文件夹 + 历史记录落库 SQLite。
"""

from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QUrl, Qt
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QGroupBox, QHBoxLayout, QLabel, QPlainTextEdit, QPushButton, QScrollArea,
    QVBoxLayout, QWidget,
)

from app import paths
from core.keys import detect_key_status
from core.registry import ScriptRegistry
from core.runner import RunResult, build_video_params, write_job_file
from core.services import HistoryDatabase
from domain.enums import MediaCategory
from ui.widgets import (
    DropZone, ElapsedTimer, HistoryStrip, KeyWarnBar, ModelBar, ParamPanel,
    PromptEcho, VideoPlayer,
)
from ui.workers import GenerateWorker

# 视频风格标签（单选修饰提示词）
STYLE_TAGS = ["默认", "自然风光", "城市街景", "科幻场景"]
# 提示词默认示例
DEFAULT_PROMPT = "一条小船在薄雾笼罩的湖面上缓缓滑行，远处是连绵的雪山，晨光穿透云层"


class VideoPage(QWidget):
    """生视频页：左参数 / 右预览+历史。

    与 ImagePage 结构同构，差异点：参数区多"视频时长"行（2-15 秒校验），
    右栏用 VideoPlayer 播放产物，历史条带"▶ 播放"按钮。
    """

    def __init__(self, main_window, registry: ScriptRegistry,
                 db: HistoryDatabase, parent=None) -> None:
        """构造生视频页（参数含义同 ImagePage）。

        参数：
            main_window: 主窗口引用（状态栏提示 / 页签跳转）
            registry: 脚本注册表，提供视频类可用脚本
            db: 历史数据库，用于记录生成结果
        """
        super().__init__(parent)
        self._main = main_window
        self._registry = registry
        self._db = db
        self._current_key = ""            # 当前选中脚本 key
        self._worker: GenerateWorker | None = None  # 后台生成线程
        self._last_output_dir = ""        # 最近输出目录
        self._last_params: dict = {}      # 最近一次生成的参数快照（历史落库用）
        # 计时进度：视频生成耗时长（30-120s），每 0.5 秒刷新"已等待 N 秒"
        self._gen_timer = ElapsedTimer(self, self._on_gen_tick)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(12)
        layout.addWidget(self._build_left(), stretch=0)
        layout.addWidget(self._build_right(), stretch=1)

        # 初始选中第一个视频脚本并加载历史
        metas = self._registry.by_category(MediaCategory.VIDEO)
        self._on_script_changed(metas[0].file_path if metas else "")
        self._refresh_history()

    def refresh_scripts(self) -> None:
        """导入新脚本后刷新脚本下拉列表（由 import_page 导入完成后调用）。"""
        scripts = {
            m.file_path: m.display_name
            for m in self._registry.by_category(MediaCategory.VIDEO)
        }
        self._model_bar.reload(scripts)
        if not self._current_key or self._current_key not in scripts:
            metas = self._registry.by_category(MediaCategory.VIDEO)
            self._on_script_changed(metas[0].file_path if metas else "")

    # ------------------------------------------------------------------
    # 左栏
    # ------------------------------------------------------------------

    def _build_left(self) -> QWidget:
        """构建左栏：脚本选择条 + KEY 警告条 + 描述/参数/首帧图 + 生成按钮。

        返回：组装好的左栏 QWidget（固定宽 372px）。
        """
        col = QWidget()
        col.setFixedWidth(372)
        outer = QVBoxLayout(col)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(7)

        # 脚本选择条：视频类脚本下拉
        scripts = {
            m.file_path: m.display_name
            for m in self._registry.by_category(MediaCategory.VIDEO)
        }
        self._model_bar = ModelBar(scripts)
        # 信号槽：切换脚本 → 参数区按脚本能力显隐
        self._model_bar.script_changed.connect(self._on_script_changed)
        outer.addWidget(self._model_bar)

        self._key_warn = KeyWarnBar()
        outer.addWidget(self._key_warn)

        # 中间滚动区
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        inner = QWidget()
        outer.addWidget(scroll, stretch=1)
        s = QVBoxLayout(inner)
        s.setContentsMargins(0, 0, 2, 0)
        s.setSpacing(7)

        # 视频描述：提示词 + 风格标签
        desc = QGroupBox("视频描述")
        dv = QVBoxLayout(desc)
        self._prompt = QPlainTextEdit(DEFAULT_PROMPT)
        self._prompt.setFixedHeight(80)
        dv.addWidget(self._prompt)
        dv.addLayout(self._tag_row())
        s.addWidget(desc)

        # 生成参数：duration 行带 2-15 秒输入校验（add_duration_row 内部实现）
        param = QGroupBox("生成参数")
        self._params = ParamPanel()
        self._params.add_combo_row("ratio", "画面比例", [])
        self._params.add_combo_row("resolution", "分辨率", [])
        self._params.add_duration_row("duration", "视频时长")
        self._params.add_combo_row("mode", "生成模式", [])
        self._params.add_seed_row("seed", visible=False)
        self._params.add_check_row([("sound", "生成声音")])
        dv2 = QVBoxLayout(param)
        dv2.addWidget(self._params)
        s.addWidget(param)

        # 首帧图片上传（脚本 need_image=True 时显示）
        self._upload_box = QGroupBox("首帧图片（必填）")
        uv = QVBoxLayout(self._upload_box)
        self._drop_zone = DropZone("上传首帧图片", "JPG / PNG / WebP · 最大 30MB")
        uv.addWidget(self._drop_zone)
        self._upload_box.hide()
        s.addWidget(self._upload_box)

        # 生成按钮 + 进度提示区
        gen_box = QWidget()
        gv = QVBoxLayout(gen_box)
        gv.setContentsMargins(0, 4, 0, 0)
        self._gen_btn = QPushButton("🎬 生成视频")
        self._gen_btn.setProperty("class", "primary")
        # 信号槽：点击生成 → 后台线程跑脚本
        self._gen_btn.clicked.connect(self._start_generate)
        gv.addWidget(self._gen_btn)
        self._prog = QPlainTextEdit("")
        self._prog.setReadOnly(True)
        self._prog.setFixedHeight(48)
        self._prog.setStyleSheet(
            "background:#f0f7ff; border:1px solid #b3d9f7; color:#0078d4;"
            " font-size:12px; padding:3px 7px; border-radius:1px;"
        )
        self._prog.hide()
        gv.addWidget(self._prog)
        s.addWidget(gen_box)
        s.addStretch(1)

        scroll.setWidget(inner)
        return col

    def _tag_row(self) -> QHBoxLayout:
        """构建风格标签行（可点选按钮，默认选第一个）。

        返回：包含所有标签按钮的水平布局。
        """
        row = QHBoxLayout()
        row.setSpacing(2)
        self._tags: list[QPushButton] = []
        for i, name in enumerate(STYLE_TAGS):
            tag = QPushButton(name)
            tag.setCheckable(True)
            tag.setChecked(i == 0)
            tag.setStyleSheet(
                "padding:2px 7px; font-size:11px; border:1px solid #d4d4d4;"
                " background:#f3f3f3; color:#555; border-radius:1px;"
            )
            # 信号槽：点击标签 → 单选高亮
            tag.clicked.connect(lambda _=False, b=tag: self._pick(b))
            self._tags.append(tag)
            row.addWidget(tag)
        row.addStretch(1)
        return row

    def _pick(self, picked) -> None:
        """单选高亮：被点的标签蓝色选中，其余灰色。

        参数：picked: 被点击的标签按钮。
        """
        for tag in self._tags:
            on = tag is picked
            tag.setChecked(on)
            tag.setStyleSheet(
                "padding:2px 7px; font-size:11px; "
                + ("border:1px solid #0078d4; background:#e5f1fb; color:#0078d4;"
                   if on else "border:1px solid #d4d4d4; background:#f3f3f3; color:#555;")
                + " border-radius:1px;"
            )

    # ------------------------------------------------------------------
    # 右栏
    # ------------------------------------------------------------------

    def _build_right(self) -> QWidget:
        """构建右栏：视频播放器 + 提示词回看 + 按钮行 + 历史（滚动区包裹）。

        返回：组装好的右栏 QWidget。
        """
        col = QWidget()
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        inner = QWidget()
        s = QVBoxLayout(inner)
        s.setContentsMargins(0, 0, 0, 0)
        s.setSpacing(7)

        # 视频播放器：黑底 16:9，产物加载后显示封面 + 文件名
        prev = QGroupBox("视频预览")
        pv = QVBoxLayout(prev)
        pv.setContentsMargins(0, 0, 0, 0)
        self._player = VideoPlayer()
        pv.addWidget(self._player)
        s.addWidget(prev)

        # 提示词回看条
        self._echo = PromptEcho(DEFAULT_PROMPT)
        s.addWidget(self._echo)

        # 按钮：打开输出目录 / 播放当前产物（系统播放器）
        actions = QHBoxLayout()
        actions.setSpacing(5)
        # 文案修正：这两个按钮都是"打开"而非"下载"，用文件夹/播放图标更准确
        dl = QPushButton("📁 打开文件夹")
        dl.clicked.connect(self._open_output_dir)
        op = QPushButton("▶ 系统播放")
        op.clicked.connect(self._player.open_external)
        for b in (dl, op):
            b.setStyleSheet("padding:5px 0px;")
            actions.addWidget(b, stretch=1)
        s.addLayout(actions)

        # 历史记录条（视频模式）：每条带"▶ 播放"按钮
        self._hist = HistoryStrip("历史记录", "▶ 播放；点击更新提示词",
                                  video_mode=True)
        # 信号槽：点播放 → 加载对应历史产物并用系统播放器打开
        self._hist.item_play_requested.connect(self._play_hist)
        s.addWidget(self._hist)
        s.addStretch(1)

        scroll.setWidget(inner)
        outer = QVBoxLayout(col)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(scroll)
        return col

    # ------------------------------------------------------------------
    # 元数据驱动
    # ------------------------------------------------------------------

    def _current_meta(self):
        """返回当前选中脚本的元数据；未选中时返回 None。"""
        if not self._current_key:
            return None
        return self._registry.get(self._current_key)

    def _script_abs_path(self, meta) -> Path:
        """把脚本相对路径拼成绝对路径（scripts/ 目录 + 相对路径）。"""
        return paths.SCRIPTS_DIR / meta.file_path

    @staticmethod
    def _meta_to_caps(meta) -> dict:
        """ScriptMeta → ParamPanel.set_caps 能力字典（视频版）。

        与图片页相比多 duration/mode/sound 三个视频特有能力键。
        """
        return {
            "seed": meta.seed,
            "need_image": meta.need_image,
            "stream": meta.stream,
            "web_search": meta.web_search,
            "sound": meta.sound,
            "ratio": meta.ratios,
            "resolution": meta.resolutions,
            "duration": meta.durations,
            "mode": meta.modes,
            "quality": meta.qualities,
            "format": meta.formats,
        }

    def _on_script_changed(self, key: str) -> None:
        """切换脚本后的联动更新：刷新参数区、首帧图框、KEY 警告。

        参数：key: 新选中脚本的 key，空串表示无可选脚本。
        """
        self._current_key = key or ""
        meta = self._current_meta()
        if meta is None:
            self._params.set_caps({})
            self._upload_box.hide()
            self._key_warn.hide()
            return
        self._params.set_caps(self._meta_to_caps(meta))
        self._upload_box.setVisible(meta.need_image)
        self._update_key_warn(meta)
        # §5.4 契约版本门闸：脚本模板过旧/过新时状态栏提醒（不阻断使用）
        self._warn_version_compat(meta)

    def _warn_version_compat(self, meta) -> None:
        """脚本模板版本与外壳不一致时状态栏提醒（§5.4，不阻断）。"""
        if getattr(meta, "version_compat", "ok") == "ok":
            return
        if meta.version_compat == "older":
            self._main.show_status(
                f"⚠ 脚本模板过旧（v{meta.template_version}），建议重新导入更新",
                4000)
        else:
            self._main.show_status(
                f"⚠ 脚本模板较新（v{meta.template_version}），请升级主程序以完整支持",
                4000)

    def _update_key_warn(self, meta) -> None:
        """检测脚本 API KEY 状态，未配置时显示黄色警告条。

        参数：meta: 当前脚本元数据。
        """
        if detect_key_status(self._script_abs_path(meta), meta) == "ok":
            self._key_warn.hide()
            return
        env = meta.key_env or "对应环境变量"
        self._key_warn.set_text(
            f"⚠ 脚本尚未配置 API KEY（脚本内 API_KEY 或环境变量 {env}），"
            "真实生成将失败，可先体验演示模式。"
        )
        self._key_warn.show()

    # ------------------------------------------------------------------
    # 生成
    # ------------------------------------------------------------------

    def _start_generate(self, mock: bool = False) -> None:
        """启动一次视频生成：收集参数 → 写任务文件 → 后台线程跑脚本。

        参数：mock: True 时走演示链路（生成占位 GIF，无需 API KEY）。
        """
        meta = self._current_meta()
        if meta is None:
            self._main.show_status("未找到可用脚本，请检查 scripts/ 目录", 3000)
            return
        prompt = self._prompt.toPlainText().strip()
        if not prompt:
            self._main.show_status("请先填写视频描述", 2500)
            return

        # 首帧图必填校验（首帧生视频脚本 need_image=True 时，§3.2）
        ref_image = ""
        if meta.need_image:
            ref_image = self._drop_zone.selected_file()
            if not ref_image:
                self._main.show_status(
                    "该脚本为首帧生视频，请先上传首帧图片（必填）", 3500)
                return

        # 按时间戳建输出目录，收集界面参数
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        out_dir = paths.OUTPUT_VIDEO_DIR / stamp
        self._last_output_dir = str(out_dir)
        params = build_video_params(
            prompt=prompt,
            ratio=self._params.value("ratio"),
            resolution=self._params.value("resolution"),
            duration=self._params.value("duration"),
            mode=self._params.value("mode"),
            output_dir=out_dir,
            seed=self._params.seed_value(),
            # 直读勾选框状态（修复：原按控件文本比对，文字一改即失效）
            sound=self._params.check_value("sound"),
            mock=mock,
            ref_image=ref_image or None,
        )
        # 记录本次生成参数（历史落库用，§7）
        self._last_params = {
            k: v for k, v in params.items()
            if k not in ("output_dir", "timeout")
        }
        # 参数落盘为 job JSON，脚本从文件读取
        job_file = write_job_file(paths.JOBS_DIR / f"job_video_{stamp}.json",
                                  **params)

        # 进入"生成中"状态
        self._gen_btn.setEnabled(False)
        self._prog.setStyleSheet(
            "background:#f0f7ff; border:1px solid #b3d9f7; color:#0078d4;"
            " font-size:12px; padding:3px 7px; border-radius:1px;"
        )
        self._prog.show()
        self._gen_timer.start()   # 计时进度：文本由 _on_gen_tick 持续刷新
        self._main.show_status("生成中，请稍候…", 0)

        # 后台线程执行脚本，信号跨线程回传 UI 线程更新界面
        # 视频生成耗时长：脚本内部预算 600 秒，外壳留 60 秒余量后再强杀
        worker = GenerateWorker(self._script_abs_path(meta), job_file, timeout=660.0, parent=self)
        worker.finished_ok.connect(self._on_gen_ok)      # 成功 → 播放器加载产物
        worker.finished_err.connect(self._on_gen_err)    # 失败 → 显示错误
        worker.finished.connect(worker.deleteLater)      # 线程结束自动释放
        self._worker = worker
        worker.start()

    def demo_generate(self) -> None:
        """演示模式：mock 链路生成占位 GIF（截图/测试用，无需 KEY）。"""
        self._start_generate(mock=True)

    def _on_gen_tick(self, seconds: float) -> None:
        """计时器回调（0.5 秒一次）：把"已等待 N 秒"刷新到进度提示区。"""
        self._prog.setPlainText(f"⟳ 生成中… 已等待 {seconds:.0f} 秒")

    def _on_gen_ok(self, result: RunResult) -> None:
        """生成成功回调（UI 线程）：恢复按钮 → 历史落库 → 播放器加载产物。

        参数：result: 脚本执行结果。
        """
        self._gen_timer.stop()
        self._gen_btn.setEnabled(True)
        self._prog.hide()
        files = [f for f in result.files if Path(f).exists()]
        self._write_history(result)
        if files:
            self._player.load(files[0])
            self._echo.set_text(self._prompt.toPlainText())
            self._main.show_status(
                f"生成完成，耗时 {result.elapsed:.1f} 秒", 3000)
        else:
            # 脚本 stdout 可能未报告产物路径 → 兜底扫描输出目录找视频文件
            scanned: list[str] = []
            if self._last_output_dir:
                od = Path(self._last_output_dir)
                if od.is_dir():
                    scanned = sorted(
                        str(p) for p in od.rglob("*")
                        if p.is_file() and p.suffix.lower()
                        in (".mp4", ".gif", ".webm", ".avi", ".mov")
                    )
            if scanned:
                self._player.load(scanned[0])
                self._echo.set_text(self._prompt.toPlainText())
                self._main.show_status(
                    f"生成完成，共 {len(scanned)} 个文件（从产物目录发现）", 3000)
            else:
                # 无产物：黄色警告 + 显示脚本输出片段
                detail = "生成完成，但没有产物文件"
                if result.stdout_tail:
                    detail += f"\n脚本输出：{result.stdout_tail[:200]}"
                self._prog.setStyleSheet(
                    "background:#fff8e1; border:1px solid #f0c040;"
                    " color:#b8860b; font-size:12px; padding:3px 7px;"
                    " border-radius:1px;"
                )
                self._prog.setPlainText(f"⚠ {detail}")
                self._prog.show()
                self._main.show_status(detail, 5000)

    def _on_gen_err(self, result: RunResult) -> None:
        """生成失败回调（UI 线程）：红色错误提示 + 失败历史 + KEY 警告刷新。

        参数：result: 脚本执行结果（含错误码与错误信息）。
        """
        self._gen_timer.stop()
        self._gen_btn.setEnabled(True)
        self._prog.setStyleSheet(
            "background:#fff5f5; border:1px solid #f0b0b0; color:#d32f2f;"
            " font-size:12px; padding:3px 7px; border-radius:1px;"
        )
        self._prog.setPlainText(f"✕ {result.code}：{result.message}")
        self._prog.show()
        self._write_fail_history(result)
        self._main.show_status(f"生成失败：{result.message}", 4000)
        # 认证失败 → 重新检测 KEY 状态并显示警告条
        if result.code == "AUTH_FAILED":
            meta = self._current_meta()
            if meta is not None:
                self._update_key_warn(meta)

    # ------------------------------------------------------------------
    # 历史 / 产物
    # ------------------------------------------------------------------

    def _write_history(self, result: RunResult) -> None:
        """成功记录写入 SQLite 历史库并刷新历史条。

        参数：result: 脚本执行结果。
        """
        self._db.add_record(
            category="video", script_key=self._current_key,
            prompt=self._prompt.toPlainText(),
            params=dict(self._last_params),   # §7：历史记录含实际参数
            files=result.files, ok=True, elapsed=result.elapsed,
        )
        self._refresh_history()

    def _write_fail_history(self, result: RunResult) -> None:
        """失败记录写入 SQLite 历史库（含错误码/信息）并刷新。

        参数：result: 脚本执行结果。
        """
        self._db.add_record(
            category="video", script_key=self._current_key,
            prompt=self._prompt.toPlainText(),
            params=dict(self._last_params),   # 失败记录也保留参数
            files=[],
            ok=False, code=result.code, message=result.message,
            elapsed=result.elapsed,
        )
        self._refresh_history()

    def _refresh_history(self) -> None:
        """从历史库读取最近 10 条视频记录，重新渲染历史条。"""
        records = self._db.list_records(category="video", limit=10)
        self._hist.load_records(records)

    def _play_hist(self, index: int) -> None:
        """播放历史视频：加载产物并用系统播放器打开，同时回显提示词。

        参数：index: 历史条目索引。
        """
        records = self._hist.records()
        if not (0 <= index < len(records)):
            return
        record = records[index]
        files = record.get("files") or []
        if files and Path(files[0]).exists():
            self._player.load(files[0])
            self._player.open_external()
        self._echo.set_text(record.get("prompt", ""))
        self._main.show_status("已播放历史视频", 2500)

    def _open_output_dir(self) -> None:
        """用系统文件管理器打开视频输出根目录 output/video/。"""
        paths.OUTPUT_VIDEO_DIR.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(
            QUrl.fromLocalFile(str(paths.OUTPUT_VIDEO_DIR)))
