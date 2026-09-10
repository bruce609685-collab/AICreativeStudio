"""AI 生图片页（还原预览文档 page-image）。

界面布局：左栏是"提示词 + 生成参数 + 批量数量 + 生成按钮"，
右栏是"图片宫格预览 + 提示词回看 + 历史记录条"。

生成流程（本页核心链路）：
  1. 用户点"生成图片" → _start_generate 收集参数并写 job 任务文件；
  2. 启动 GenerateWorker（QThread 后台线程）执行脚本，界面不卡死；
  3. 脚本跑完后通过信号 finished_ok / finished_err 回到 UI 线程，
     分别走 _on_gen_ok（展示产物图片）或 _on_gen_err（显示失败原因）；
  4. 每次生成结果都写入 SQLite 历史库并刷新底部历史条。

M1：静态演示；M2：注册表驱动 + 真实生成链路；M3：历史记录落库 SQLite
（历史条显示真实记录，点击回看提示词）+ 打开产物文件夹。
"""

from datetime import datetime
import os
from pathlib import Path

from PySide6.QtCore import QUrl, Qt
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QGroupBox, QHBoxLayout, QLabel, QPlainTextEdit, QPushButton,
    QScrollArea, QSpinBox, QVBoxLayout, QWidget,
)

from app import paths
from core.keys import detect_key_status
from core.registry import ScriptRegistry
from core.runner import RunResult, build_image_params, write_job_file
from core.services import HistoryDatabase
from domain.enums import MediaCategory
from ui.widgets import (
    DropZone, ElapsedTimer, HistoryStrip, KeyWarnBar, ModelBar, ParamPanel,
    PreviewGrid, PromptEcho,
)
from ui.workers import GenerateWorker

# 风格标签选项（点击单选，作为提示词的风格修饰）
STYLE_TAGS = ["默认", "赛博朋克", "油画风", "写实摄影", "二次元", "风景大片"]
# 提示词输入框的默认示例文案
DEFAULT_PROMPT = "一只赛博朋克风格的猫咪坐在霓虹灯闪烁的东京街头，雨夜，倒影，超写实"


class ImagePage(QWidget):
    """生图片页：左参数 / 右预览+历史。

    左栏固定宽 372px（脚本选择、参数、生成按钮），右栏弹性伸展（宫格、历史）。
    """

    def __init__(self, main_window, registry: ScriptRegistry,
                 db: HistoryDatabase, parent=None) -> None:
        """构造生图片页。

        参数：
            main_window: 主窗口引用（用于 show_status / switch_tab 联动）
            registry: 脚本注册表，提供本类别的可用脚本列表
            db: 历史数据库，用于记录每次生成结果
        """
        super().__init__(parent)
        self._main = main_window
        self._registry = registry
        self._db = db
        self._current_key = ""            # 当前选中脚本的 key（相对路径）
        self._worker: GenerateWorker | None = None  # 当前后台生成线程
        self._last_output_dir = ""        # 最近一次生成的输出目录（打开产物用）
        self._last_params: dict = {}      # 最近一次生成的参数快照（历史落库用）
        # §3.1 计时进度：生成中每 0.5 秒更新"已等待 N 秒"
        self._gen_timer = ElapsedTimer(self, self._on_gen_tick)

        # 左右两栏布局：左栏固定宽，右栏弹性伸展
        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(12)

        layout.addWidget(self._build_left(), stretch=0)
        layout.addWidget(self._build_right(), stretch=1)

        # 初始选中第一个脚本（ModelBar 构造时的 script_changed 在 connect 前已 emit，
        # 因此必须手动触发一次 _on_script_changed 设好 self._current_key）。
        metas = self._registry.by_category(MediaCategory.IMAGE)
        self._on_script_changed(metas[0].file_path if metas else "")
        self._batch.setValue(4)   # 默认批量 4 张
        self._refresh_history()   # 启动时从 SQLite 读历史记录

    def refresh_scripts(self) -> None:
        """导入新脚本后刷新脚本下拉列表（由 import_page 导入完成后调用）。

        保留当前选中脚本；若当前脚本已不存在则回退到第一个。
        """
        scripts = {
            m.file_path: m.display_name
            for m in self._registry.by_category(MediaCategory.IMAGE)
        }
        self._model_bar.reload(scripts)
        if not self._current_key or self._current_key not in scripts:
            metas = self._registry.by_category(MediaCategory.IMAGE)
            self._on_script_changed(metas[0].file_path if metas else "")

    # ------------------------------------------------------------------
    # 左栏
    # ------------------------------------------------------------------

    def _build_left(self) -> QWidget:
        """构建左栏：脚本选择条 + KEY 警告条 + 参数区 + 批量 + 生成按钮。

        返回：组装好的左栏 QWidget（固定宽 372px）。
        """
        col = QWidget()
        col.setFixedWidth(372)
        outer = QVBoxLayout(col)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(7)

        # 脚本选择条：从注册表取图片类脚本填充下拉框
        scripts = {
            m.file_path: m.display_name
            for m in self._registry.by_category(MediaCategory.IMAGE)
        }
        self._model_bar = ModelBar(scripts)
        # 信号槽：用户切换脚本 → 触发参数区显隐更新
        self._model_bar.script_changed.connect(self._on_script_changed)
        outer.addWidget(self._model_bar)

        # API KEY 未填写时的黄色警告条
        self._key_warn = KeyWarnBar()
        outer.addWidget(self._key_warn)

        # 中间滚动区：参数较多时左栏可上下滚动
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        inner = QWidget()
        outer.addWidget(scroll, stretch=1)
        s = QVBoxLayout(inner)
        s.setContentsMargins(0, 0, 2, 0)
        s.setSpacing(7)

        # 图片描述：提示词输入框 + 风格标签行
        desc_box = QGroupBox("图片描述")
        dv = QVBoxLayout(desc_box)
        self._prompt = QPlainTextEdit(DEFAULT_PROMPT)
        self._prompt.setFixedHeight(80)
        dv.addWidget(self._prompt)
        dv.addLayout(self._tag_row())
        s.addWidget(desc_box)

        # 生成参数（选项由脚本元数据 ACS_META 驱动）：
        # 各行先注册占位，具体选项在 set_caps 里按脚本能力动态填充
        param_box = QGroupBox("生成参数")
        self._params = ParamPanel()
        self._params.add_combo_row("ratio", "画面比例", [])
        self._params.add_combo_row("resolution", "分辨率", [])
        self._params.add_combo_row("quality", "图片质量", [])
        self._params.add_combo_row("format", "输出格式", [])
        self._params.add_seed_row("seed", visible=False)
        self._params.add_check_row([("stream", "流式输出"), ("web_search", "联网搜索")])
        dv2 = QVBoxLayout(param_box)
        dv2.addWidget(self._params)
        s.addWidget(param_box)

        # 参考图上传（图生图时显示）：脚本 need_image=True 才可见
        self._upload_box = QGroupBox("参考图片（必填，1张）")
        uv = QVBoxLayout(self._upload_box)
        self._drop_zone = DropZone("点击选择或拖放图片", "JPG / PNG / WebP · 最大 30MB")
        uv.addWidget(self._drop_zone)
        self._upload_box.hide()
        s.addWidget(self._upload_box)

        # 批量生成：数量 1-9，改变时同步更新右侧宫格数
        batch_box = QGroupBox("批量生成")
        bv = QHBoxLayout(batch_box)
        bv.addWidget(QLabel("生成数量"))
        self._batch = QSpinBox()
        self._batch.setRange(1, 9)
        self._batch.setFixedWidth(56)
        self._batch.setFixedHeight(26)
        self._batch.setAlignment(Qt.AlignmentFlag.AlignCenter)
        # 信号槽：数量变化 → 更新提示文字和预览宫格
        self._batch.valueChanged.connect(self._on_batch)
        bv.addWidget(self._batch)
        bv.addWidget(QLabel("张（1–9）"))
        bv.addStretch(1)
        self._batch_tip = QLabel("单次生成 4 张图片")
        self._batch_tip.setStyleSheet("font-size:11px; color:#888;")
        dv3 = QVBoxLayout(batch_box)
        dv3.addLayout(bv)
        dv3.addWidget(self._batch_tip)
        s.addWidget(batch_box)

        # 生成按钮 + 进度提示区（生成中显示，结束后隐藏/变色）
        gen_box = QWidget()
        gv = QVBoxLayout(gen_box)
        gv.setContentsMargins(0, 4, 0, 0)
        self._gen_btn = QPushButton("✨ 生成图片")
        # class=primary 使按钮套用全局样式的蓝色主按钮外观
        self._gen_btn.setProperty("class", "primary")
        # 信号槽：点击生成 → 启动后台生成流程
        self._gen_btn.clicked.connect(self._start_generate)
        gv.addWidget(self._gen_btn)
        self._prog_label = QPlainTextEdit("")
        self._prog_label.setReadOnly(True)
        self._prog_label.setFixedHeight(48)
        self._prog_label.setStyleSheet(
            "background:#f0f7ff; border:1px solid #b3d9f7; color:#0078d4;"
            " font-size:12px; padding:3px 7px; border-radius:1px;"
        )
        self._prog_label.hide()
        gv.addWidget(self._prog_label)
        s.addWidget(gen_box)
        s.addStretch(1)

        scroll.setWidget(inner)
        return col

    def _tag_row(self) -> QHBoxLayout:
        """构建风格标签行：一排可点选的按钮（单选，默认选第一个）。

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
            # 信号槽：点击标签 → _pick_tag 单选高亮（lambda 固定住当前按钮引用）
            tag.clicked.connect(lambda _=False, b=tag: self._pick_tag(b))
            self._tags.append(tag)
            row.addWidget(tag)
        row.addStretch(1)
        return row

    def _pick_tag(self, picked) -> None:
        """单选高亮：只让被点的标签呈蓝色选中态，其余恢复灰色。

        参数：picked: 被点击的标签按钮。
        """
        for tag in self._tags:
            tag.setChecked(tag is picked)
            if tag is picked:
                tag.setStyleSheet(
                    "padding:2px 7px; font-size:11px; border:1px solid #0078d4;"
                    " background:#e5f1fb; color:#0078d4; border-radius:1px;"
                )
            else:
                tag.setStyleSheet(
                    "padding:2px 7px; font-size:11px; border:1px solid #d4d4d4;"
                    " background:#f3f3f3; color:#555; border-radius:1px;"
                )

    # ------------------------------------------------------------------
    # 右栏
    # ------------------------------------------------------------------

    def _build_right(self) -> QWidget:
        """构建右栏：图片宫格预览 + 提示词回看 + 打开文件夹按钮 + 历史条。

        返回：组装好的右栏 QWidget（弹性伸展占满剩余空间）。
        """
        col = QWidget()
        outer = QVBoxLayout(col)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(6)

        # 宫格预览区：1/2/4/9 宫格自适应批量数量
        preview_box = QGroupBox()
        preview_box.setStyleSheet("QGroupBox{border:1px solid #d4d4d4; margin-top:0px;}")
        pv = QVBoxLayout(preview_box)
        pv.setContentsMargins(0, 0, 0, 0)
        self._grid = PreviewGrid()
        # 信号槽：点击宫格 → 用系统看图打开该图 + 更新提示词回看（§3.1）
        self._grid.cell_clicked.connect(self._on_cell_clicked)
        pv.addWidget(self._grid)
        outer.addWidget(preview_box, stretch=1)

        # 提示词回看条：点历史/预览格后显示当时的提示词，可复制
        self._echo = PromptEcho(DEFAULT_PROMPT)
        outer.addWidget(self._echo)

        # 底部两个按钮：打开最近产物 / 打开整个图片输出目录
        actions = QHBoxLayout()
        actions.setSpacing(6)
        # 文案区分：左边打开"本次产物所在目录"，右边打开"图片输出根目录"
        dl = QPushButton("📂 本次产物")
        dl.clicked.connect(self._open_last_output)
        open_btn = QPushButton("📁 输出目录")
        open_btn.clicked.connect(self._open_output_dir)
        for b in (dl, open_btn):
            b.setStyleSheet("padding:5px 0px;")
            actions.addWidget(b, stretch=1)
        outer.addLayout(actions)

        # 历史记录条：从 SQLite 加载最近 10 条，点击回看提示词
        self._hist = HistoryStrip("历史记录",
                                  "点击缩略图：回看提示词")
        # 信号槽：点击历史条目 → 更新提示词回看区
        self._hist.item_clicked.connect(self._on_hist_click)
        outer.addWidget(self._hist)
        return col

    # ------------------------------------------------------------------
    # 脚本元数据驱动（M2）
    # ------------------------------------------------------------------

    def _current_meta(self):
        """返回当前选中脚本的元数据（ScriptMeta）；未选中时返回 None。"""
        if not self._current_key:
            return None
        return self._registry.get(self._current_key)

    def _script_abs_path(self, meta) -> Path:
        """把脚本相对路径拼成绝对路径（scripts/ 目录 + 相对路径）。"""
        return paths.SCRIPTS_DIR / meta.file_path

    @staticmethod
    def _meta_to_caps(meta) -> dict:
        """ScriptMeta → ParamPanel.set_caps 能力字典。

        把脚本元数据（支持哪些比例/分辨率/质量/格式等）翻译成
        参数面板能理解的"能力字典"，用于驱动参数行的显隐与选项。
        """
        return {
            "seed": meta.seed,
            "need_image": meta.need_image,
            "stream": meta.stream,
            "web_search": meta.web_search,
            "ratio": meta.ratios,
            "resolution": meta.resolutions,
            "quality": meta.qualities,
            "format": meta.formats,
        }

    def _on_script_changed(self, key: str) -> None:
        """切换脚本后的联动更新：刷新参数区显隐、参考图框、KEY 警告。

        参数：key: 新选中脚本的 key（相对路径），空串表示无可选脚本。
        """
        self._current_key = key or ""
        meta = self._current_meta()
        if meta is None:
            # 没有可用脚本：参数区全部隐藏、提示消失
            self._params.set_caps({})
            self._upload_box.hide()
            self._key_warn.hide()
            return
        # 按脚本能力刷新参数区（set_caps 控制各行显隐与下拉选项）
        self._params.set_caps(self._meta_to_caps(meta))
        # 图生图脚本才显示"参考图片"上传框
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
        # KEY 缺失：提示去哪配 KEY（脚本内 API_KEY 或环境变量）
        env = meta.key_env or "对应环境变量"
        self._key_warn.set_text(
            f"⚠ 脚本尚未配置 API KEY（脚本内 API_KEY 或环境变量 {env}），"
            "真实生成将失败，可先体验演示模式。"
        )
        self._key_warn.show()

    # ------------------------------------------------------------------
    # 交互
    # ------------------------------------------------------------------

    def _on_batch(self, n: int) -> None:
        """批量数量变化：更新提示文字并同步调整预览宫格数。

        参数：n: 新的生成数量（1-9）。
        """
        n = max(1, min(9, n))
        self._batch_tip.setText(f"单次生成 {n} 张图片")
        self._grid.set_count(n)

    @staticmethod
    def _open_file_externally(path: str) -> bool:
        """用系统默认程序打开文件（看图/播放通用）。

        先走 QDesktopServices（Qt 标准方式）；失败时降级 os.startfile
        （Windows 原生 ShellExecute，Qt 桌面服务偶发静默失败时兜底）。
        两级都失败返回 False，由调用方给出提示。

        参数：path: 文件绝对路径。
        返回：是否成功触发打开。
        """
        if not Path(path).exists():
            return False
        if QDesktopServices.openUrl(QUrl.fromLocalFile(path)):
            return True
        try:
            os.startfile(path)   # Windows 专属兜底（Qt 服务失败时）
            return True
        except OSError:
            return False

    def _on_cell_clicked(self, cell) -> None:
        """点击宫格图片：用系统看图程序打开，并把本次提示词回显到回看区。

        参数：cell: 被点击的 _Cell（携带该格图片路径）。
        """
        # 从宫格取该格显示的图片路径（无图/占位格静默忽略）
        index = -1
        for i, c in enumerate(self._grid._cells):   # noqa: SLF001（同模块控件联动）
            if c is cell:
                index = i
                break
        path = self._grid.image_at(index) if index >= 0 else ""
        if path and Path(path).exists():
            if self._open_file_externally(path):
                self._echo.set_text(self._prompt.toPlainText())
                self._main.show_status("已用系统看图打开该图片", 2000)
            else:
                self._main.show_status("打开失败：系统拒绝打开该文件", 3000)

    def _on_hist_click(self, index: int) -> None:
        """点击历史条目：在预览宫格中回看该记录的图片 + 回看提示词。

        参数：index: 被点击的历史条目索引。
        """
        records = self._hist.records()
        if not (0 <= index < len(records)):
            return
        record = records[index]
        self._echo.set_text(record.get("prompt", ""))
        # 产物存在 → 载入预览宫格回看（不跳系统看图，2026-09-04 需求变更）
        files = [f for f in (record.get("files") or []) if Path(f).exists()][:9]
        if files:
            self._grid.set_count(len(files))
            for i, f in enumerate(files):
                self._grid.set_image_at(i, f)
            self._main.show_status(
                f"已在预览区显示该历史记录的 {len(files)} 张图片", 2500)
        else:
            self._main.show_status("已回看历史提示词（图片文件已不在原位置）", 2500)

    # ------------------------------------------------------------------
    # 生成（真实链路）
    # ------------------------------------------------------------------

    def _start_generate(self, mock: bool = False) -> None:
        """启动一次生成：收集参数 → 写任务文件 → 后台线程跑脚本。

        参数：mock: True 时走演示链路（生成占位图，无需 API KEY）。
        """
        meta = self._current_meta()
        if meta is None:
            self._main.show_status("未找到可用脚本，请检查 scripts/ 目录", 3000)
            return
        prompt = self._prompt.toPlainText().strip()
        if not prompt:
            self._main.show_status("请先填写图片描述", 2500)
            return

        # 参考图必填校验（图生图脚本 need_image=True 时，§3.1/§11）
        ref_image = ""
        if meta.need_image:
            ref_image = self._drop_zone.selected_file()
            if not ref_image:
                self._main.show_status(
                    "该脚本为图生图，请先上传参考图片（必填）", 3500)
                return

        # 按时间戳建本次生成的输出目录（如 output/image/20260901_120000）
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        out_dir = paths.OUTPUT_IMAGE_DIR / stamp
        self._last_output_dir = str(out_dir)   # 存下来供 _on_gen_ok 兜底扫描
        # 收集界面参数 → 组装成脚本需要的参数字典
        params = build_image_params(
            prompt=prompt,
            ratio=self._params.value("ratio"),
            resolution=self._params.value("resolution"),
            quality=self._params.value("quality"),
            format_=self._params.value("format"),
            batch=self._batch.value(),
            output_dir=out_dir,
            seed=self._params.seed_value(),
            mock=mock,
            ref_image=ref_image or None,
        )
        # 记录本次生成参数（历史落库用，§7"含提示词、参数、状态、耗时"）
        self._last_params = {
            k: v for k, v in params.items()
            if k not in ("output_dir", "timeout")   # 路径/超时不入历史
        }
        # 参数落盘为 job JSON 文件（脚本从文件读参数，而非命令行）
        job_file = write_job_file(paths.JOBS_DIR / f"job_{stamp}.json", **params)

        # 进入"生成中"状态：禁用按钮 + 显示进度提示 + 状态栏常驻提示
        self._gen_btn.setEnabled(False)
        self._prog_label.setStyleSheet(
            "background:#f0f7ff; border:1px solid #b3d9f7; color:#0078d4;"
            " font-size:12px; padding:3px 7px; border-radius:1px;"
        )
        self._prog_label.show()
        self._gen_timer.start()   # 计时进度：文本由 _on_gen_tick 持续刷新
        self._main.show_status("生成中，请稍候…", 0)

        # 启动后台线程跑脚本（信号跨线程回传，UI 线程安全更新界面）
        worker = GenerateWorker(self._script_abs_path(meta), job_file, parent=self)
        worker.finished_ok.connect(self._on_gen_ok)      # 成功 → 展示产物
        worker.finished_err.connect(self._on_gen_err)    # 失败 → 显示错误
        worker.finished.connect(worker.deleteLater)      # 线程结束自动释放
        self._worker = worker
        worker.start()

    def demo_generate(self) -> None:
        """演示模式：mock 链路生成占位图（截图 / 测试用，无需 KEY）。"""
        self._start_generate(mock=True)

    def _on_gen_ok(self, result: RunResult) -> None:
        """生成成功回调（GenerateWorker.finished_ok 信号触发，UI 线程）。

        依次处理：恢复按钮 → 记录历史 → 展示产物图片到宫格。
        若脚本 stdout 未报告产物路径，则兜底扫描输出目录找图片文件。

        参数：result: 脚本执行结果（含产物文件列表、耗时等）。
        """
        self._finish_generate()
        files = [f for f in result.files if Path(f).exists()]
        self._write_history(result)
        if files:
            # 正常路径：按产物数量铺宫格并逐格显示图片
            self._grid.set_count(len(files))
            for i, f in enumerate(files):
                self._grid.set_image_at(i, f)
            self._echo.set_text(self._prompt.toPlainText())
            self._last_output_dir = str(Path(files[0]).parent)
            self._main.show_status(
                f"生成完成，共 {len(files)} 张，耗时 {result.elapsed:.1f} 秒", 3000)
        else:
            # 脚本 stdout 可能未报告产物路径 → 兜底扫描输出目录
            scanned: list[str] = []
            if self._last_output_dir:
                od = Path(self._last_output_dir)
                if od.is_dir():
                    scanned = sorted(
                        str(p) for p in od.rglob("*")
                        if p.is_file() and p.suffix.lower()
                        in (".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp")
                    )
            if scanned:
                self._grid.set_count(len(scanned))
                for i, f in enumerate(scanned):
                    self._grid.set_image_at(i, f)
                self._echo.set_text(self._prompt.toPlainText())
                self._main.show_status(
                    f"生成完成，共 {len(scanned)} 张（从产物目录发现）", 3000)
            else:
                # 既无报告也无产物：黄色警告提示 + 显示脚本输出片段辅助排查
                self._prog_label.setStyleSheet(
                    "background:#fff8e1; border:1px solid #f0c040;"
                    " color:#b8860b; font-size:12px; padding:3px 7px;"
                    " border-radius:1px;"
                )
                detail = "生成完成，但没有产物文件"
                if result.stdout_tail:
                    detail += f"\n脚本输出：{result.stdout_tail[:200]}"
                self._prog_label.setPlainText(f"⚠ {detail}")
                self._prog_label.show()
                self._main.show_status(detail, 5000)

    def _on_gen_err(self, result: RunResult) -> None:
        """生成失败回调（GenerateWorker.finished_err 信号触发，UI 线程）。

        红色提示错误码与原因，写入失败历史；AUTH_FAILED 时刷新 KEY 警告条。

        参数：result: 脚本执行结果（含错误码 code 与说明 message）。
        """
        self._finish_generate()
        self._prog_label.setStyleSheet(
            "background:#fff5f5; border:1px solid #f0b0b0; color:#d32f2f;"
            " font-size:12px; padding:3px 7px; border-radius:1px;"
        )
        self._prog_label.setPlainText(
            f"✕ {result.code}：{result.message}")
        self._prog_label.show()
        self._write_fail_history(result)
        self._main.show_status(f"生成失败：{result.message}", 4000)
        # 认证失败说明 KEY 有问题 → 重新检测并显示警告条
        if result.code == "AUTH_FAILED":
            meta = self._current_meta()
            if meta is not None:
                self._update_key_warn(meta)

    def _finish_generate(self) -> None:
        """收尾：停计时、恢复生成按钮可点、隐藏进度提示区（成功/失败共用）。"""
        self._gen_timer.stop()
        self._gen_btn.setEnabled(True)
        self._prog_label.hide()

    def _on_gen_tick(self, seconds: float) -> None:
        """计时器回调（0.5 秒一次）：把"已等待 N 秒"刷新到进度提示区。"""
        self._prog_label.setPlainText(f"⟳ 生成中… 已等待 {seconds:.0f} 秒")

    # ------------------------------------------------------------------
    # 历史 / 产物（M3：SQLite 落库）
    # ------------------------------------------------------------------

    def _write_history(self, result: RunResult) -> None:
        """成功记录写入 SQLite 历史库并刷新历史条。

        参数：result: 脚本执行结果（取产物文件列表与耗时）。
        """
        self._db.add_record(
            category="image", script_key=self._current_key,
            prompt=self._prompt.toPlainText(),
            params=dict(self._last_params),   # §7：历史记录含实际参数
            files=result.files, ok=True, elapsed=result.elapsed,
        )
        self._refresh_history()

    def _write_fail_history(self, result: RunResult) -> None:
        """失败记录写入 SQLite 历史库（含错误码/错误信息）并刷新。

        参数：result: 脚本执行结果（取错误码与错误信息）。
        """
        self._db.add_record(
            category="image", script_key=self._current_key,
            prompt=self._prompt.toPlainText(),
            params=dict(self._last_params),   # 失败记录也保留参数，便于重试
            files=[],
            ok=False, code=result.code, message=result.message,
            elapsed=result.elapsed,
        )
        self._refresh_history()

    def _refresh_history(self) -> None:
        """从历史库读取最近 10 条图片记录，重新渲染历史条。"""
        records = self._db.list_records(category="image", limit=10)
        self._hist.load_records(records)

    def _open_output_dir(self) -> None:
        """用系统文件管理器打开图片输出根目录 output/image/。"""
        paths.OUTPUT_IMAGE_DIR.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(
            QUrl.fromLocalFile(str(paths.OUTPUT_IMAGE_DIR)))

    def _open_last_output(self) -> None:
        """打开最近一次生成的输出目录（无记录时回退到输出根目录）。"""
        target = self._last_output_dir or paths.OUTPUT_IMAGE_DIR
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(target)))
