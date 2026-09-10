"""脚本选择条 + KEY 警告条 + 动态参数区。

本模块包含三个可复用控件：
  - ModelBar：顶部"当前脚本"下拉选择条，切换时发出 script_changed 信号；
  - KeyWarnBar：API KEY 未填写时的黄色警告条；
  - ParamPanel：动态参数面板（本模块核心）——页面先用 add_combo_row /
    add_duration_row / add_seed_row / add_check_row 注册各种参数行，
    再由 set_caps(能力字典) 统一控制每行的显隐与下拉选项。
    能力字典来自脚本元数据 ACS_META（core/registry 的 ScriptMeta）。

关键交互：
  - add_duration_row 视频时长输入框：QIntValidator(2,15) 限制只能输数字，
    _check_duration 检测超范围（<2 或 >15 秒）时弹窗警告并回退默认值 5；
  - add_seed_row 随机种子：🎲随机 生成 0~2147483647 整数，↺ 重置为 -1。

M1 演示版：由页面传入"能力字典"驱动显隐（复刻预览文档 IMG_CAPS 逻辑）；
M2 起改由 core/registry 提供的 ScriptMeta（ACS_META 解析结果）驱动。
"""

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QComboBox, QFrame, QGridLayout, QHBoxLayout, QLabel, QLineEdit,
    QMessageBox, QPushButton, QVBoxLayout, QWidget,
)
from PySide6.QtGui import QIntValidator

from ui import style

# 随机种子的默认值（-1 表示不指定，交给模型随机）
DEFAULT_SEED = "-1"


class ModelBar(QWidget):
    """顶部脚本选择条（还原 .model-bar）。

    一个"当前脚本："标签 + 下拉框；切换时发出 script_changed 信号，
    宿主页面据此刷新参数区显隐。
    """

    # 信号：脚本切换，参数是脚本 key（相对路径）
    script_changed = Signal(str)

    def __init__(self, scripts: dict[str, str], parent=None) -> None:
        """构建选择条。

        参数：scripts: {key: 显示名}，顺序即显示顺序。
        """
        super().__init__(parent)
        self._scripts = scripts
        row = QHBoxLayout(self)
        row.setContentsMargins(9, 6, 9, 6)
        row.setSpacing(7)

        label = QLabel("当前脚本：")
        label.setStyleSheet("font-weight:600; font-size:12px;")
        self._combo = QComboBox()
        # addItem(显示名, data)：data 存脚本 key，业务上用 key 而非文字
        for key, name in scripts.items():
            self._combo.addItem(name, key)
        # 信号槽：下拉切换 → 发出 script_changed
        self._combo.currentIndexChanged.connect(self._on_changed)
        row.addWidget(label)
        row.addWidget(self._combo, stretch=1)

    def _on_changed(self, _index: int) -> None:
        """下拉切换内部处理：发出 script_changed 信号携带当前 key。"""
        self.script_changed.emit(self.current_key())

    def current_key(self) -> str:
        """返回当前选中脚本的 key。"""
        return self._combo.currentData()

    def set_current_key(self, key: str) -> None:
        """按 key 选中对应脚本（找不到则不变）。

        参数：key: 脚本 key。
        """
        index = self._combo.findData(key)
        if index >= 0:
            self._combo.setCurrentIndex(index)

    def reload(self, scripts: dict[str, str]) -> None:
        """替换脚本列表（导入新脚本后刷新用），保持当前选中不变。

        重建下拉时临时 blockSignals 防止触发多余的 script_changed。

        参数：scripts: 新的 {key: 显示名} 映射。
        """
        current = self.current_key()
        self._combo.blockSignals(True)
        self._combo.clear()
        for key, name in scripts.items():
            self._combo.addItem(name, key)
        self._combo.blockSignals(False)
        if current in scripts:
            self.set_current_key(current)
        elif scripts:
            self._combo.setCurrentIndex(0)


class KeyWarnBar(QFrame):
    """API KEY 未填写警告条（还原 .key-warn，黄底）。

    默认隐藏，宿主页面检测到 KEY 缺失时 set_text + show。
    """

    # 默认提示文字
    TEXT = "⚠ 该脚本的 API KEY 尚未填写，请前往「模型设置」填写后再使用。"

    def __init__(self, parent=None) -> None:
        """构建警告条（黄色背景，默认隐藏）。"""
        super().__init__(parent)
        self.setStyleSheet(
            f"background:{style.WARN_BG}; border:1px solid {style.WARN_BORDER};"
            f" color:{style.WARN_TEXT}; font-size:11px; border-radius:1px;"
        )
        lay = QHBoxLayout(self)
        lay.setContentsMargins(8, 5, 8, 5)
        self._label = QLabel(self.TEXT)
        # 警告文字较长（含环境变量名），必须允许换行——否则窄窗口下被截断，
        # 用户看不到"去哪里填 KEY"这个关键信息
        self._label.setWordWrap(True)
        lay.addWidget(self._label)
        self.hide()

    def set_text(self, text: str) -> None:
        """自定义警告文字（如提示具体的环境变量名）。

        参数：text: 警告文字。
        """
        self._label.setText(text)


class ParamPanel(QWidget):
    """元数据驱动的动态参数区。

    页面注册字段行 → set_caps(能力字典) 统一控制显隐与选项：
      {"seed": True, "stream": False, "quality": ["standard","high"], ...}
    """

    def __init__(self, parent=None) -> None:
        """初始化两列网格与内部状态字典。"""
        super().__init__(parent)
        self._grid = QGridLayout()
        self._grid.setContentsMargins(0, 0, 0, 0)
        self._grid.setHorizontalSpacing(6)
        self._grid.setVerticalSpacing(6)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addLayout(self._grid)

        self._rows: dict[str, QWidget] = {}       # key → 行容器
        self._combos: dict[str, QComboBox] = {}   # key → 下拉框
        self._combo_caps_keys: dict[str, str] = {}  # 下拉 key → caps 字典键
        self._durations_edit: QLineEdit | None = None  # 视频时长输入框
        self._durations_row: QWidget | None = None     # 视频时长行容器
        self._next_cell = 0                        # 两列网格的下一个空位

    # ------------------------------------------------------------------
    # 行注册
    # ------------------------------------------------------------------

    def _label(self, text: str) -> QLabel:
        """构建统一风格的小号字段标签。

        参数：text: 标签文字。
        返回：QLabel。
        """
        lab = QLabel(text)
        lab.setStyleSheet("font-size:11px; font-weight:600; color:#555;")
        return lab

    def _place_row(self, key: str, row: QWidget, editor: QWidget | None,
                   span: bool = False) -> None:
        """加入两列网格；span=True 时整行跨两列。

        内部维护 _next_cell 游标：普通行占 1 格，跨列行占 2 格，
        网格按 "序号 // 2 行, 序号 % 2 列" 定位。

        参数：
            key: 行标识；row: 行容器；editor: 行内编辑控件（QComboBox 会登记）；
            span: 是否跨两列。
        """
        self._rows[key] = row
        if span:
            self._grid.addWidget(row, self._next_cell // 2, 0, 1, 2)
        else:
            col = self._next_cell % 2
            self._grid.addWidget(row, self._next_cell // 2, col)
        self._next_cell += (2 if span else 1)
        if editor is not None and isinstance(editor, QComboBox):
            self._combos[key] = editor

    def add_combo_row(self, key: str, label: str, options: list[str],
                      visible: bool = True, caps_key: str | None = None) -> None:
        """注册一行下拉框。caps_key：set_caps 字典里取选项的键（默认同 key）。

        参数：
            key: 行标识（value(key) 取值用）；label: 标签文字；
            options: 初始选项；visible: 初始是否可见；caps_key: 能力字典键名。
        """
        row = QWidget()
        v = QVBoxLayout(row)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(2)
        v.addWidget(self._label(label))
        combo = QComboBox()
        combo.addItems(options)
        v.addWidget(combo)
        row.setVisible(visible)
        self._place_row(key, row, combo)
        self._combo_caps_keys[key] = caps_key or key

    def add_duration_row(self, key: str, label: str,
                         visible: bool = True) -> None:
        """注册视频时长输入行：QLineEdit + QIntValidator [2, 15] + 校验。

        QIntValidator 只拦非数字；具体范围（2-15 秒）由 _check_duration
        在文本变化时校验，超范围弹窗警告并回退默认值 5。

        参数：key: 行标识；label: 标签文字；visible: 初始是否可见。
        """
        row = QWidget()
        v = QVBoxLayout(row)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(2)
        v.addWidget(self._label(label))
        self._durations_edit = QLineEdit("5")
        self._durations_edit.setFixedWidth(100)
        # 输入校验第一层：只允许整数（仍允许暂时超范围，交给 _check_duration）
        self._durations_edit.setValidator(QIntValidator(2, 15))
        # 信号槽：文本变化 → 范围校验（超 2-15 秒弹窗）
        self._durations_edit.textChanged.connect(self._check_duration)
        hint = QLabel("(2-15 秒)")
        hint.setStyleSheet("font-size:10px; color:#999;")
        line = QHBoxLayout()
        line.setSpacing(5)
        line.addWidget(self._durations_edit)
        line.addWidget(hint)
        line.addStretch(1)
        v.addLayout(line)
        self._durations_row = row
        row.setVisible(visible)
        self._place_row(key, row, None)

    def _check_duration(self, text: str) -> None:
        """校验时长输入，超出 [2, 15] 范围时弹出警告。

        校验失败时把输入框回退为默认值 5，保证后续生成拿到合法参数。

        参数：text: 输入框当前文本。
        """
        if not text.strip():
            return
        try:
            n = int(text.strip())
        except ValueError:
            return
        if n < 2 or n > 15:
            QMessageBox.warning(
                self, "参数错误",
                f"视频时长超出范围（2-15 秒），当前输入：{n} 秒，请重新输入。",
            )
            # 回退到默认值 5
            self._durations_edit.setText("5")

    def add_seed_row(self, key: str = "seed", visible: bool = False) -> None:
        """随机种子行：输入框 + 🎲随机 + ↺重置。

        随机生成 0~2147483647 的整数；重置回 -1（不指定）。

        参数：key: 行标识；visible: 初始是否可见（默认隐藏，按脚本能力显隐）。
        """
        row = QWidget()
        v = QVBoxLayout(row)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(2)
        v.addWidget(self._label("随机种子"))
        line = QHBoxLayout()
        line.setSpacing(5)
        self._seed_edit = QLineEdit(DEFAULT_SEED)
        self._seed_edit.setFixedWidth(100)
        btn_rand = QPushButton("🎲 随机")
        btn_rand.setStyleSheet("font-size:11px; padding:2px 9px;")
        # 信号槽：点随机 → 填入一个随机整数
        btn_rand.clicked.connect(self._random_seed)
        btn_reset = QPushButton("↺ -1")
        btn_reset.setStyleSheet("font-size:11px; padding:2px 9px;")
        # 信号槽：点重置 → 恢复默认 -1
        btn_reset.clicked.connect(lambda: self._seed_edit.setText(DEFAULT_SEED))
        line.addWidget(self._seed_edit)
        line.addWidget(btn_rand)
        line.addWidget(btn_reset)
        line.addStretch(1)
        v.addLayout(line)
        row.setVisible(visible)
        self._place_row(key, row, None, span=True)

    def add_check_row(self, checks: list[tuple[str, str]]) -> None:
        """能力勾选行：[(key, 文本), ...]，跨两列。

        各勾选框默认隐藏，由 set_caps 按脚本能力决定是否显示；
        每次切换脚本后勾选状态重置。

        参数：checks: [(能力键, 勾选框文字), ...] 列表。
        """
        row = QWidget()
        v = QVBoxLayout(row)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(2)
        line = QHBoxLayout()
        line.setSpacing(18)
        from PySide6.QtWidgets import QCheckBox

        self._checks: dict[str, QCheckBox] = {}
        for key, text in checks:
            box = QCheckBox(text)
            self._checks[key] = box
            box.hide()
            line.addWidget(box)
        line.addStretch(1)
        v.addLayout(line)
        self._place_row("__checks__", row, None, span=True)

    # ------------------------------------------------------------------
    # 能力驱动（M1: 演示 caps 字典；M2: ScriptMeta）
    # ------------------------------------------------------------------

    def set_caps(self, caps: dict) -> None:
        """按能力字典统一控制显隐。缺省 key 视为 False/空。

        这是"脚本能力 → 界面"的统一入口：切换脚本时页面把脚本元数据
        打包成 caps 传进来，本方法负责：
          1. 种子行按 caps["seed"] 布尔值显隐；
          2. 视频时长行按 caps["duration"] 是否非空显隐；
          3. 所有下拉行按各自 caps_key 取选项——空列表隐藏整行，
             单选项禁用下拉（没得选），多选项正常可换；
          4. 勾选框按 caps 对应键显隐，并重置为未勾选。

        参数：caps: 能力字典，如 {"seed": True, "quality": ["standard","high"]}。
        """
        # 种子 / 参考图类布尔
        if "seed" in self._rows:
            self._rows["seed"].setVisible(bool(caps.get("seed")))
        # 视频时长行（durations 能力键）
        if self._durations_row is not None:
            dur_opts = caps.get("duration") or []
            self._durations_row.setVisible(bool(dur_opts))
        # 所有下拉行：按 caps_key 取选项，单选项禁用，空列表隐藏整行
        for key, combo in self._combos.items():
            meta_key = self._combo_caps_keys.get(key, key)
            options = caps.get(meta_key) or []
            self._set_combo(key, options)
        # 勾选类
        if hasattr(self, "_checks"):
            for key, box in self._checks.items():
                box.setVisible(bool(caps.get(key)))
                box.setChecked(False)

    def _set_combo(self, key: str, options: list[str]) -> None:
        """刷新单个下拉框：重建选项并按选项数决定显隐/禁用。

        blockSignals 防止重建过程触发 currentIndexChanged 联动。

        参数：key: 行标识；options: 新选项列表。
        """
        combo = self._combos[key]
        combo.blockSignals(True)
        combo.clear()
        combo.addItems(options)
        # 单选项（没得选）禁用；空选项整行隐藏
        combo.setEnabled(len(options) > 1)
        self._rows[key].setVisible(bool(options))
        combo.blockSignals(False)

    # ------------------------------------------------------------------
    # 取值
    # ------------------------------------------------------------------

    def _random_seed(self) -> None:
        """🎲随机：生成 0~2147483647 的随机整数填入种子框。"""
        import random

        self._seed_edit.setText(str(random.randint(0, 2147483647)))

    def value(self, key: str) -> str:
        """读取指定参数行的当前值。

        参数：key: 行标识（"seed"/"duration" 走专用输入框，其余查下拉框）。
        返回：当前值文本；行不存在返回空串。
        """
        if key == "seed":
            return self._seed_edit.text()
        if key == "duration" and self._durations_edit is not None:
            return self._durations_edit.text()
        combo = self._combos.get(key)
        return combo.currentText() if combo else ""

    def seed_value(self) -> str:
        """返回随机种子输入框的当前值。"""
        return self._seed_edit.text()

    def check_value(self, key: str) -> bool:
        """返回指定能力勾选框是否勾选（#12 修复：布尔值直读而非文本比对）。

        参数：key: 能力键（如 "sound" / "stream" / "web_search"）。
        返回：勾选返回 True；勾选框不存在返回 False。
        """
        box = getattr(self, "_checks", {}).get(key)
        return bool(box and box.isChecked())
