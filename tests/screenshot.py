"""界面走查截图：offscreen 渲染六个页签，逐页存 PNG。

M3 增强：三个生成页各跑一次 mock 生成（图→渐变 PNG、视频→GIF 动画、
语音→真实 WAV），产物进宫格/播放器，历史记录落库显示——验证
"三类产物生成/播放/下载"全链路。

这不是 pytest 测试，而是一个**可视化走查脚本**：它在没有显示器的
环境里（QT_QPA_PLATFORM=offscreen 让 Qt 离屏渲染）把主窗口六个
页签依次"摆好内容"后截图存盘，供人工检查界面是否正常、或作为
文档/README 的界面示意图。

脚本流程（main）：
  1. 起应用 → 注册脚本 → 建主窗口；
  2. 图/视/音三个生成页各跑一次 mock 生成并等待完成
     （产物进宫格/播放器、历史记录落库）；
  3. 导入页用真实流式回调跑一次 mock 导入（日志区实时滚动 LLM 输出）；
  4. 逐页 grab() 截图 → tests/screenshots/page_<n>_<name>.png。

运行：set QT_QPA_PLATFORM=offscreen && python -m tests.screenshot
产物：tests/screenshots/page_<n>_<name>.png
"""

import os
import sys
import time

# 必须在导入 PySide6 之前设置：offscreen 表示"离屏渲染"，
# 不需要真实显示器也能创建窗口并截图（CI 服务器/无头环境必需）。
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from app import paths  # noqa: E402
from app.logger_setup import setup_logging  # noqa: E402
from core.registry import ScriptRegistry, scan_scripts_dir  # noqa: E402
from infra.persistence import HistoryDatabase  # noqa: E402
from ui.main_window import MainWindow  # noqa: E402
from ui.style import apply_global_style  # noqa: E402

OUT_DIR = paths.BASE_DIR / "tests" / "screenshots"  # 截图输出目录


def _demo_generate_and_wait(win, tab_index: int, timeout_s: float = 10.0) -> None:
    """在指定页签跑一次 mock 生成，等 worker 完成后返回（截图取证用）。

    难点：Qt 界面靠"事件循环"驱动，而这里没有 app.exec() 主循环在跑，
    所以用 QApplication.processEvents() 手动泵事件——既让界面刷新，
    也让 worker 的信号（进度/完成）能送达 UI 线程。

    参数：
        win: 主窗口，用于取到页签控件；
        tab_index: 页签下标（image/video/audio 之一）；
        timeout_s: 最长等待秒数，防止 worker 卡死导致脚本挂住。
    """
    page = win.tab_widget.widget(tab_index)
    page.demo_generate()  # 页面自带的"演示生成"入口（内部起 GenerateWorker）
    deadline = time.time() + timeout_s
    # 阶段一：泵事件直到 worker 线程结束（isFinished）
    while time.time() < deadline:
        QApplication.processEvents()
        worker = getattr(page, "_worker", None)
        if worker is not None and worker.isFinished():
            break
        time.sleep(0.02)
    # 阶段二：worker 线程结束了，但它的 finished_ok 信号还在队列里排队，
    # 需要再泵几轮事件，让 _on_gen_ok 把产物摆进宫格/播放器、写完历史
    for _ in range(40):
        QApplication.processEvents()
        time.sleep(0.01)


def main() -> int:
    """脚本主流程：建窗口 → 三页 mock 生成 → 导入页流式演示 → 逐页截图。

    返回 0 表示全程无异常（退出码，供命令行判断）。
    """
    setup_logging()
    paths.ensure_dirs()
    app = QApplication.instance() or QApplication(sys.argv)  # 已有实例就复用
    apply_global_style(app)

    registry = ScriptRegistry()
    registry.load(scan_scripts_dir(paths.SCRIPTS_DIR))
    print(f"scripts registered: {registry.count()}")

    db = HistoryDatabase(paths.HISTORY_DB)
    win = MainWindow(registry, db)
    win.resize(1280, 800)
    win.show()

    out_dir = OUT_DIR
    out_dir.mkdir(parents=True, exist_ok=True)

    # —— 第一步：三个生成页各跑一次 mock 生成（产物进宫格/播放器 + 历史落库）——
    for tab in (win.TAB_IMAGE, win.TAB_VIDEO, win.TAB_AUDIO):
        win.switch_tab(tab)
        QApplication.processEvents()
        _demo_generate_and_wait(win, tab)
        print(f"demo generate done: tab {tab}")
    print(f"history counts: image={db.count('image')} "
          f"video={db.count('video')} audio={db.count('audio')}")

    # —— 第二步：导入页 mock 流式导入 ——
    # 日志区实时显示 LLM 生成内容，截图取证"流式输出"效果。
    # 注意：不走 _start_import（完成后会弹模态预览对话框，offscreen 下阻塞），
    # 直接调底层管线 + 真实流式回调，展示"LLM 正在输出"的界面状态。
    win.switch_tab(win.TAB_IMPORT)
    app.processEvents()
    imp = win.tab_widget.widget(win.TAB_IMPORT)
    # 填一段典型接口文档作为"待导入"素材
    imp._doc.setPlainText(
        "接口地址：https://api.example.com/v1/images/generations\n"
        "认证方式：Authorization: Bearer <API_KEY>\n"
        "模型 ID：demo-image-1，支持 seed、stream 参数。\n"
    )
    imp._mock.setChecked(True)
    from core.importer.llm_client import LLMConfig
    from core.importer.pipeline import import_from_document

    # on_chunk 回调接到页面的 _on_llm_chunk：LLM 每吐一段文字就实时追加到日志区
    result = import_from_document(
        imp._doc.toPlainText(), LLMConfig(mock=True),
        templates_dir=paths.TEMPLATES_DIR, scripts_dir=paths.SCRIPTS_DIR,
        on_log=imp._append_log,
        on_chunk=lambda t: imp._on_llm_chunk(t),
    )
    app.processEvents()
    imp._bar.setValue(100)  # 手动把进度条推满，模拟完成态
    imp._pct.setText("100%")
    imp._step_label.setText("✨ 完成" if result.ok else "✕ 失败")
    print("import demo done (stream log visible)")

    # —— 第三步：逐页截图 ——
    names = ["image", "video", "audio", "settings", "import", "about"]
    for index, name in enumerate(names):
        win.switch_tab(index)
        app.processEvents()
        QTimer.singleShot(50, lambda: None)  # 留 50ms 渲染缓冲
        app.processEvents()

        pix = win.grab()  # 把整个窗口渲染成一张位图
        path = out_dir / f"page_{index}_{name}.png"
        pix.save(str(path))
        print(f"saved {path}")

    # 主窗口整体（页签 0）
    win.switch_tab(0)
    app.processEvents()
    win.grab().save(str(out_dir / "main_overview.png"))
    print("saved main_overview.png")
    return 0


if __name__ == "__main__":
    sys.exit(main())
