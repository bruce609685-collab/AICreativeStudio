"""发布收尾脚本：源码 zip + 发行 zip + 数据规程 + Key 终扫。

用法（项目根目录）：
    python packaging/release.py <dist_dir> <tag>
例：python packaging/release.py dist_v0.1.0r v0.5_build0910

做四件事：
1. 发行包数据规程（§18.5）：<dist>/AICreativeStudio/data/ 只保留空 config.json + 空 jobs/，
   删除 history.db / cache / 任何 *.db；
2. 源码 zip：AI影音创造工坊_源码_<ver>.zip（排除 dist/build/__pycache__/探针/截图/db）；
3. 发行 zip：AICreativeStudio_<tag>.zip；
4. 终扫：两个 zip 内 .py/.json/.txt 搜 "sk-" 与真实 API_KEY 赋值；history.db 不得存在。
"""
from __future__ import annotations

import json
import re
import shutil
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC_DIRS = ["app", "contract", "core", "domain", "infra", "packaging",
            "scripts", "templates", "tests", "ui"]
SRC_FILES = [".gitignore", "AICreativeStudio.spec", "LICENSE", "README.md",
             "about.py", "main.py", "requirements.txt"]
SKIP_PARTS = {"__pycache__", ".pytest_cache", "screenshots"}
SKIP_SUFFIX = {".pyc", ".png", ".db", ".zip"}
# 真实 Key 形态：sk- 后跟 ≥20 位字母数字（测试假 Key 如 sk-test-123 不命中）
SK_RE = re.compile(r"sk-[A-Za-z0-9_\-]{20,}")
# API_KEY 赋值：值 ≥20 位且不含 { （排除 keys.py 的 f-string 注入模板）
KEY_RE = re.compile(r'API_KEY\s*=\s*["\'][^"\'{}]{20,}["\']')


def _skip(p: Path) -> bool:
    if p.is_dir():
        return True
    if SKIP_PARTS & set(p.parts):
        return True
    if p.suffix in SKIP_SUFFIX:
        return True
    return p.name.startswith("_probe") or p.name.startswith("_fix")


def enforce_data_rule(app_dir: Path) -> None:
    data = app_dir / "data"
    if data.exists():
        shutil.rmtree(data)
    (data / "jobs").mkdir(parents=True)
    (data / "config.json").write_text("{}\n", encoding="utf-8")
    print(f"[data] 规程就位：{data}（空 config.json + 空 jobs/）")


def zip_source(version: str) -> Path:
    out = ROOT / f"AI影音创造工坊_源码_{version}.zip"
    n = 0
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for f in SRC_FILES:
            z.write(ROOT / f, f)
            n += 1
        for d in SRC_DIRS:
            for p in sorted((ROOT / d).rglob("*")):
                if _skip(p):
                    continue
                z.write(p, p.relative_to(ROOT).as_posix())
                n += 1
    print(f"[src] {out.name}: {n} files, {out.stat().st_size // 1024} KB")
    return out


def zip_dist(dist_dir: Path, tag: str) -> Path:
    app_dir = dist_dir / "AICreativeStudio"
    out = ROOT / f"AICreativeStudio_{tag}.zip"
    n = 0
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for p in sorted(app_dir.rglob("*")):
            rel = ("AICreativeStudio" / p.relative_to(app_dir)).as_posix()
            if p.is_dir():
                if not any(p.iterdir()):  # 空目录（如 data/jobs/）也要进包
                    z.writestr(zipfile.ZipInfo(rel + "/"), b"")
                continue
            z.write(p, rel)
            n += 1
    print(f"[dist] {out.name}: {n} files, {out.stat().st_size // (1024 * 1024)} MB")
    return out


def scan_zip(path: Path) -> list[str]:
    hits: list[str] = []
    with zipfile.ZipFile(path) as z:
        for name in z.namelist():
            if name.endswith("history.db") or "/cache/" in name:
                hits.append(f"数据残留: {name}")
            if not name.endswith((".py", ".json", ".txt", ".md")):
                continue
            text = z.read(name).decode("utf-8", "ignore")
            if SK_RE.search(text):
                hits.append(f"sk- 真实形态: {name}")
            if KEY_RE.search(text):
                hits.append(f"API_KEY 非空: {name}")
    return hits


def main() -> int:
    if len(sys.argv) != 3:
        print(__doc__)
        return 2
    dist_dir = ROOT / sys.argv[1]
    tag = sys.argv[2]
    version = tag.split("_")[0]
    app_dir = dist_dir / "AICreativeStudio"
    if not (app_dir / "AICreativeStudio.exe").exists():
        print(f"未找到 exe：{app_dir}")
        return 1
    enforce_data_rule(app_dir)
    src_zip = zip_source(version)
    dist_zip = zip_dist(dist_dir, tag)
    problems = scan_zip(src_zip) + scan_zip(dist_zip)
    if problems:
        print("[scan] 发现问题：")
        for p in problems:
            print("   -", p)
        return 1
    print("[scan] Key / 数据终扫：零残留")
    return 0


if __name__ == "__main__":
    sys.exit(main())
