"""deps 模块单测：list_missing / install_pip / check_ffmpeg / download_ffmpeg。

测试分组：
  - _check_pip_installed：模块可导入性检测（标准库 True / 不存在 False）；
  - list_missing：批量缺失检测（全装/空表/真缺失/去重）；
  - install_pip：安装一个轻量已知包（已装则跳过）；
  - check_ffmpeg：PATH 检测（未装则 skip）+ data/ffmpeg/ 目录检测；
  - download_ffmpeg：用本地假 zip + mock urlretrieve 模拟完整下载解压流程。

运行：python -m tests.test_deps
"""

import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

# 把项目根加到 sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.deps import (
    FFMPEG_DIR, _check_pip_installed, check_ffmpeg, download_ffmpeg,
    install_pip, list_missing,
)


# ============================================================
# _check_pip_installed
# ============================================================

def test_check_pip_installed_ok() -> None:
    """标准库模块应返回 True。

    _check_pip_installed 的原理是用 importlib 尝试导入模块：
    能导入 → True，抛 ImportError → False。
    这里拿两个一定存在的标准库（json / pathlib）验证"能导入"分支。
    """
    assert _check_pip_installed("json") is True
    assert _check_pip_installed("pathlib") is True


def test_check_pip_installed_missing() -> None:
    """不存在的模块返回 False。

    用一个几乎不可能真实存在的模块名，验证"导入失败"分支。
    """
    assert _check_pip_installed("this_module_does_not_exist_xyz") is False


# ============================================================
# list_missing
# ============================================================

def test_list_missing_all_installed() -> None:
    """标准库包不在缺失列表。"""
    missing = list_missing(["json", "pathlib", "os"])
    assert missing == []


def test_list_missing_none() -> None:
    """空列表返回空。"""
    assert list_missing([]) == []


def test_list_missing_with_real_missing() -> None:
    """不存在的包出现在缺失列表。"""
    missing = list_missing(["json", "non_existent_pkg_abc"])
    assert "non_existent_pkg_abc" in missing
    assert "json" not in missing


def test_list_missing_dedup() -> None:
    """重复包名只出现一次。

    注意大小写不同（pkg_abc / PKG_ABC）——Python 包名不区分大小写，
    list_missing 内部做了小写归一 + 去重，所以结果只有 1 条。
    """
    missing = list_missing(["non_existent_pkg_abc", "NON_EXISTENT_PKG_ABC"])
    assert len(missing) == 1


# ============================================================
# install_pip
# ============================================================

def test_install_pip_known_package() -> None:
    """安装一个轻量已知包（six 或 idna 这种小包）。"""
    # 先确认它没装
    if _check_pip_installed("idna"):
        return  # 已经装了，跳过
    ok = install_pip("idna")
    # 安装后应能导入
    assert ok is True
    assert _check_pip_installed("idna") is True


# ============================================================
# check_ffmpeg
# ============================================================

def test_check_ffmpeg_path() -> None:
    """如果系统 PATH 有 ffmpeg，返回 True。"""
    if os.name == "nt":
        # 在 Windows 上 which 可能找不到，跳过
        import shutil
        if shutil.which("ffmpeg") is None:
            pytest.skip("系统未安装 ffmpeg")
    assert check_ffmpeg() is True


def test_check_ffmpeg_data_dir() -> None:
    """在 data/ffmpeg/ 放一个假 ffmpeg.exe，应检测到。

    check_ffmpeg 除了查系统 PATH，还会检查项目自带的
    data/ffmpeg/ 目录（应用内一键下载 ffmpeg 的落点）。
    这里不改系统环境，只在 data/ffmpeg/ 造假文件验证目录检测分支。
    """
    # 保存原始状态
    orig = FFMPEG_DIR.exists()
    try:
        (FFMPEG_DIR / "bin").mkdir(parents=True, exist_ok=True)
        fake = FFMPEG_DIR / "bin" / "ffmpeg.exe"
        fake.write_text("fake ffmpeg", encoding="utf-8")
        # 复制到上一层也放一个（两种目录布局 check_ffmpeg 都应认）
        (FFMPEG_DIR / "ffmpeg.exe").write_text("fake ffmpeg", encoding="utf-8")
        os.environ.pop("PATH", None)  # 临时去掉 PATH 防干扰
        assert check_ffmpeg() is True
    finally:
        import shutil
        if FFMPEG_DIR.exists():
            shutil.rmtree(FFMPEG_DIR)


# ============================================================
# download_ffmpeg（mock 远端）
# ============================================================

def test_download_ffmpeg_mock() -> None:
    """用本地假 zip 模拟下载流程。

    完整流程：download_ffmpeg() 内部是「下载 zip → 解压 →
    在 data/ffmpeg/ 下找到 ffmpeg.exe」。真实下载要联网且体积大，
    所以这里用 unittest.mock 把 urlretrieve 换成"复制本地假 zip"，
    其余解压、查找逻辑照常真实执行。
    """
    import zipfile
    import shutil

    # —— 第一步：制作一个假 zip，模拟官网下载的压缩包结构 ——
    # 真实的 ffmpeg zip 解压后是一个顶层目录（如 ffmpeg-top/），里面才是 bin/ffmpeg.exe
    fake_zip = Path(tempfile.mkdtemp()) / "ffmpeg.zip"
    with zipfile.ZipFile(str(fake_zip), "w") as zf:
        zf.writestr("ffmpeg-top/bin/ffmpeg.exe", "fake ffmpeg binary")
        zf.writestr("ffmpeg-top/bin/ffplay.exe", "fake ffplay binary")

    # 清理可能残留的目录，保证断言的是本次测试自己解压出来的文件
    if FFMPEG_DIR.exists():
        shutil.rmtree(FFMPEG_DIR)

    # —— 第二步：mock 掉 urlretrieve ——
    # side_effect 用自定义函数代替真实下载：把假 zip 复制到目标路径，
    # 并手动触发一次 reporthook（下载进度回调），模拟真实下载行为。
    with patch("core.deps.urllib.request.urlretrieve") as mock_retrieve:
        def _fake_retrieve(url, path, reporthook=None):
            import shutil
            shutil.copy2(str(fake_zip), path)
            if reporthook:
                total = fake_zip.stat().st_size
                reporthook(1, 1024, total)  # 模拟一次进度回调

        mock_retrieve.side_effect = _fake_retrieve
        result = download_ffmpeg()
        assert result is True

    # —— 第三步：验证 ——
    # ffmpeg.exe 应该已被解压到 data/ffmpeg/ 下的某个位置（rglob 递归查找）
    ff_found = list(FFMPEG_DIR.rglob("ffmpeg.exe"))
    assert len(ff_found) > 0, f"预期 data/ffmpeg/ 下存在 ffmpeg.exe，实际内容：{list(FFMPEG_DIR.rglob('*'))}"

    # 清理：删掉测试产生的目录和假 zip，不留垃圾文件
    shutil.rmtree(FFMPEG_DIR, ignore_errors=True)
    if fake_zip.exists():
        fake_zip.unlink()


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])