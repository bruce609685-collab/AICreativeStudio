"""样式级联 BUG 专项验证（offscreen 像素采样）。

背景：Qt 中不带选择器的样式表（如 setStyleSheet("border:1px solid ...")）
会级联到该控件的所有子控件；改用 #objectName{...} 限定作用域可阻断级联。

本脚本做两件事：
  1. 对照实验：无选择器 vs #objectName 两种写法，各放一个子 QLabel，
     统计渲染后灰色边框像素数量，证明级联被阻断。
  2. 实际控件复扫：遍历六页所有 class=primary 主按钮，采样其背景色，
     确认没有出现"白字白底看不见"。

运行：QT_QPA_PLATFORM=offscreen python -m tests.verify_cascade
"""

import os
import sys
from collections import Counter

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtGui import QColor  # noqa: E402
from PySide6.QtWidgets import (  # noqa: E402
    QApplication, QFrame, QLabel, QPushButton, QVBoxLayout, QWidget,
)

# 目标灰色（#d4d4d4）容差范围内的像素判定
TARGET = QColor("#d4d4d4")
TOL = 12


def _gray_pixel_count(pixmap) -> int:
    """统计图像中接近 #d4d4d4 的灰色像素数量（边框线的痕迹）。

    参数：pixmap: 待统计的 QPixmap。
    返回：匹配像素个数。
    """
    img = pixmap.toImage()
    n = 0
    for y in range(img.height()):
        for x in range(img.width()):
            c = img.pixelColor(x, y)
            if (abs(c.red() - TARGET.red()) <= TOL
                    and abs(c.green() - TARGET.green()) <= TOL
                    and abs(c.blue() - TARGET.blue()) <= TOL):
                n += 1
    return n


def _make_case(scoped: bool) -> QFrame:
    """构造对照用容器：内含一个子 QLabel。

    参数：scoped: True=用 #objectName 限定；False=无选择器（会级联）。
    返回：容器 QFrame。
    """
    frame = QFrame()
    frame.setFixedSize(160, 60)
    if scoped:
        frame.setObjectName("caseBox")
        frame.setStyleSheet(
            "#caseBox{border:1px solid #d4d4d4; border-radius:1px;}")
    else:
        frame.setStyleSheet("border:1px solid #d4d4d4; border-radius:1px;")
    v = QVBoxLayout(frame)
    v.setContentsMargins(0, 0, 0, 0)
    label = QLabel("子控件")
    v.addWidget(label)
    return frame


def check_cascade() -> bool:
    """对照实验：证明无选择器写法会让子控件也多出一圈边框。

    返回：True=实验符合预期（修复有效）。
    """
    app = QApplication.instance() or QApplication(sys.argv)
    bad = _make_case(scoped=False)
    good = _make_case(scoped=True)
    bad.show()
    good.show()
    app.processEvents()

    n_bad = _gray_pixel_count(bad.grab())
    n_good = _gray_pixel_count(good.grab())

    print(f"[对照实验] 无选择器（级联）灰边像素 = {n_bad}")
    print(f"[对照实验] #objectName（限定）灰边像素 = {n_good}")
    # 级联时子控件额外画一圈边框 → 灰像素明显更多
    ok = n_bad > n_good * 1.5
    print(f"[对照实验] 结论：{'通过（级联已被阻断）' if ok else '异常'}")
    return ok


def _dominant_color(button: QPushButton) -> str:
    """采样按钮中心区域的主色（众数色）。

    参数：button: 待采样的按钮。
    返回：十六进制颜色字符串。
    """
    img = button.grab().toImage()
    w, h = img.width(), img.height()
    # 避开圆角与文字，取中上部一条横向带
    y = max(2, h // 4)
    colors = Counter()
    for x in range(w // 5, w * 4 // 5):
        colors[img.pixelColor(x, y).name()] += 1
    return colors.most_common(1)[0][0] if colors else "#000000"


def check_primary_buttons() -> bool:
    """遍历六页主按钮，确认背景不是白色/浅灰（即没被容器级联盖掉）。

    返回：True=全部通过。
    """
    from app import paths
    from core.registry import ScriptRegistry, scan_scripts_dir
    from infra.persistence import HistoryDatabase
    from ui.main_window import MainWindow
    from ui.style import apply_global_style

    app = QApplication.instance() or QApplication(sys.argv)
    apply_global_style(app)
    registry = ScriptRegistry()
    registry.load(scan_scripts_dir(paths.SCRIPTS_DIR))
    db = HistoryDatabase(paths.DATA_DIR / "verify_cascade_history.db")
    win = MainWindow(registry, db)
    win.resize(1280, 800)
    win.show()
    app.processEvents()

    bad = []
    total = 0
    for i in range(win.tab_widget.count()):
        win.switch_tab(i)
        for _ in range(5):
            app.processEvents()
        page = win.tab_widget.widget(i)
        for btn in page.findChildren(QPushButton):
            if btn.property("class") == "primary" and btn.isVisible():
                total += 1
                color = _dominant_color(btn)
                c = QColor(color)
                # 白色/近白/浅灰 = 被盖掉（BAD）
                is_light = c.lightness() > 200
                flag = "BAD" if is_light else "OK "
                print(f"[主按钮] 页{i} {btn.text()[:14]:<16} 背景={color} {flag}")
                if is_light:
                    bad.append((i, btn.text(), color))
    print(f"[主按钮] 共扫描 {total} 个，异常 {len(bad)} 个")
    db.close()
    return not bad


if __name__ == "__main__":
    ok1 = check_cascade()
    ok2 = check_primary_buttons()
    print("\n===== 汇总 =====")
    print(f"样式级联对照：{'通过' if ok1 else '未通过'}")
    print(f"主按钮背景复扫：{'通过' if ok2 else '未通过'}")
    sys.exit(0 if (ok1 and ok2) else 1)
