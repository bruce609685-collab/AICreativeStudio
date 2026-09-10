"""界面符号字形全量体检：扫描源码中硬编码的符号，验证系统字体是否有字形。

动机：模型无法读图，肉眼走查不可靠。改用程序化方式——把 ui/ 与 app/
下所有源码里的非 ASCII 符号字符抽出来，逐个用 QRawFont 验字形
（索引 0 = 该字体无此字形），凡是所有候选字体都画不出来的，
就是潜在的"豆腐块"（空心方块）来源。

排除中文：汉字由 Microsoft YaHei UI 提供，无需检查（也不该被误报）。

运行：QT_QPA_PLATFORM=offscreen python -m tests.verify_glyphs
返回码：0=无缺失；1=存在缺失符号（需替换）。
"""

import os
import re
import sys
import unicodedata
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtGui import QFont, QFontDatabase, QRawFont  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
SCAN_DIRS = [ROOT / "ui", ROOT / "app"]

# 候选字体（与 ui/icons.py 保持一致）
FONT_CANDIDATES = [
    "Segoe UI Emoji",
    "Segoe UI Symbol",
    "Segoe UI",
    "Microsoft YaHei UI",
]

# 字体文件：部分字体不注册的话 Qt 查不到（与 ui/style.py 一致）
FONT_FILES = ["seguiemj.ttf", "seguisym.ttf", "seguisym2.ttf"]


def _is_symbol(ch: str) -> bool:
    """判断字符是否为"需要字体字形的符号"（排除汉字、标点与 ASCII）。

    只关注 Unicode 分类为 So（其它符号）的字符——emoji、箭头、几何图形
    这类。全角标点（，。：；！？（））分类是 Po，由雅黑覆盖，不参与检查；
    否则会把满屏中文标点误报成"缺字形"。

    参数：ch: 单个字符。
    返回：True=需要检查字形。
    """
    if ord(ch) < 0x80:
        return False                      # ASCII：基础字体覆盖
    return unicodedata.category(ch) == "So"


def _collect_symbols() -> dict[str, list[str]]:
    """扫描源码目录，收集符号字符 → 出现位置（文件名:行号）。

    返回：符号到位置列表的映射。
    """
    found: dict[str, list[str]] = {}
    for base in SCAN_DIRS:
        for path in base.rglob("*.py"):
            if "__pycache__" in path.parts:
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            rel = path.relative_to(ROOT).as_posix()
            for lineno, line in enumerate(text.splitlines(), 1):
                for ch in line:
                    if _is_symbol(ch):
                        found.setdefault(ch, []).append(f"{rel}:{lineno}")
    return found


def _font_has_glyph(family: str, ch: str) -> bool:
    """用 QRawFont 精确判断某字体是否含该字符字形。

    参数：family: 字体族名；ch: 待检查字符。
    返回：True=有字形。
    """
    raw = QRawFont.fromFont(QFont(family, 14))
    if not raw.isValid():
        return False
    idx = raw.glyphIndexesForString(ch)
    return bool(idx) and idx[0] != 0


def main() -> int:
    """体检主流程：注册字体 → 扫描符号 → 逐个验字形 → 输出报告。

    返回：0=全部有字形；1=存在缺失。
    """
    app = QApplication.instance() or QApplication(sys.argv)
    fonts_dir = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts"
    for name in FONT_FILES:
        fpath = fonts_dir / name
        if fpath.exists():
            QFontDatabase.addApplicationFont(str(fpath))

    available = set(QFontDatabase.families())
    missing_candidates = [f for f in FONT_CANDIDATES if f not in available]
    if missing_candidates:
        print(f"[提示] 本机缺少候选字体：{missing_candidates}")

    symbols = _collect_symbols()
    print(f"[扫描] ui/ 与 app/ 共发现 {len(symbols)} 个非 ASCII 符号字符\n")

    blocked: list[tuple[str, str, list[str]]] = []
    for ch in sorted(symbols):
        hit = None
        for fam in FONT_CANDIDATES:
            if fam in available and _font_has_glyph(fam, ch):
                hit = fam
                break
        locs = symbols[ch]
        if hit is None:
            blocked.append((ch, "无", locs))
        else:
            print(f"  {ch}  U+{ord(ch):04X}  {unicodedata.name(ch, '?'):<32} {hit}")

    print()
    if blocked:
        print(f"===== 发现 {len(blocked)} 个缺字形的符号（会显示成方块）=====")
        for ch, _, locs in blocked:
            print(f"  {ch}  U+{ord(ch):04X}  {unicodedata.name(ch, '?')}")
            for loc in locs[:5]:
                print(f"        ↳ {loc}")
            if len(locs) > 5:
                print(f"        ↳ ...共 {len(locs)} 处")
        return 1

    print("===== 全部符号均有可用字形，不会出现豆腐块 =====")
    return 0


if __name__ == "__main__":
    sys.exit(main())
