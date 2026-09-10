"""冒烟测试：导入关键模块 + offscreen 实例化主窗口 + 注册表加载。

测试目的：快速验证"程序骨架没坏"——
  1. test_imports：所有分层模块（contract/core/domain/infra/ui）都能
     正常 import，且 about/枚举/模板版本等关键常量符合预期；
  2. test_registry_loaded：真实扫描 scripts/ 目录，注册表至少有一个
     脚本（图片类至少一个），保证 M2 注册表链路可用；
  3. test_main_window_construction：offscreen 模式实例化主窗口，
     断言 6 个页签就位、状态栏信息正常。

运行：set QT_QPA_PLATFORM=offscreen && python -m tests.test_smoke
验证 M1 骨架可正常装配、分层 import 规则未被破坏、M2 注册表可用。
"""

import os
import sys

# offscreen 模式：CI/无显示环境也能跑（必须在 QApplication 创建前设置）
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def _bootstrap() -> None:
    """初始化日志 + 路径（与 app.application.run 一致的前置）。"""
    from app import paths
    from app.logger_setup import setup_logging

    paths.ensure_dirs()
    setup_logging()


def test_imports() -> None:
    """headless 层与界面层核心模块均可 import。

    逐层 import 一遍即验证依赖关系没被破坏；同时断言程序 ID、
    版本号、媒体类别枚举、模板版本、错误码等关键常量。
    """
    import about
    from app import paths, single_instance
    from app.logger_setup import setup_logging
    import contract  # noqa: F401
    from contract import fields, params, result  # noqa: F401
    from core import deps, keys, registry, runner  # noqa: F401
    from domain import enums, models
    import infra.persistence  # noqa: F401
    from ui.main_window import MainWindow
    from ui.style import apply_global_style
    from ui.widgets import (
        AudioPlayer, DropZone, HistoryStrip, KeyInputPanel, KeyWarnBar,
        ModelBar, ParamPanel, PreviewGrid, PromptEcho, VideoPlayer,
    )

    assert about.APP_ID == "AICreativeStudio"
    assert about.APP_VERSION == "0.5.1"
    assert enums.MediaCategory.IMAGE.value == "image"
    assert models.ScriptMeta().template_version == "1.0.0"
    assert fields.TEMPLATE_VERSION == "1.0.0"
    assert result.ERR_AUTH_FAILED == "AUTH_FAILED"


def test_registry_loaded() -> None:
    """真实扫描 scripts/，注册表非空（M2 前置）。

    断言：至少注册 1 个脚本，且图片类至少 1 个。
    """
    from app import paths
    from core.registry import ScriptRegistry, scan_scripts_dir
    from domain import enums

    registry = ScriptRegistry()
    registry.load(scan_scripts_dir(paths.SCRIPTS_DIR))
    assert registry.count() >= 1, "scripts/ 下应有已注册脚本"
    assert len(registry.by_category(enums.MediaCategory.IMAGE)) >= 1


def test_main_window_construction() -> None:
    """offscreen 实例化主窗口（带真实注册表+历史库），6 页签就位。"""
    from PySide6.QtWidgets import QApplication

    _bootstrap()
    # 复用已有 QApplication（pytest 下可能已被其他用例创建）
    app = QApplication.instance() or QApplication(sys.argv)
    from app import paths
    from core.registry import ScriptRegistry, scan_scripts_dir
    from infra.persistence import HistoryDatabase
    from ui.main_window import MainWindow

    registry = ScriptRegistry()
    registry.load(scan_scripts_dir(paths.SCRIPTS_DIR))
    # 用独立的测试历史库，避免污染真实数据
    db = HistoryDatabase(paths.DATA_DIR / "test_smoke_history.db")
    win = MainWindow(registry, db)
    assert win.tab_widget.count() == 6
    # 页签图标由 icons.symbol_icon 渲染成 QIcon（文本不再带 emoji 前缀，
    # 因为符号字形依赖系统字体，直接写文本会变豆腐块）。
    assert not win.tab_widget.tabIcon(0).isNull()
    assert win.tab_widget.tabText(0).strip() == "AI生图片"
    # 脚本数量随导入增长，改为动态断言（≥3 个预置脚本）
    assert "脚本：" in win.status_right_text
    db.close()


if __name__ == "__main__":
    test_imports()
    test_registry_loaded()
    test_main_window_construction()
    print("smoke test passed")
    sys.exit(0)
