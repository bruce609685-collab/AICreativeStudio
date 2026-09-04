"""生成 Windows 版本资源文件（version_info.txt）——从 about.py 字段动态生成。

用法：python packaging/build_version.py > packaging/version_info.txt
PyInstaller spec 里以 version= 引用，把 程序名/版本/作者 固化进 exe 属性。
"""

import sys
from pathlib import Path

# 项目根加入 sys.path，确保能 import about
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import about  # noqa: E402


def _ver_tuple(version: str) -> tuple[int, int, int, int]:
    parts = version.split(".")
    nums = []
    for p in parts[:4]:
        try:
            nums.append(int(p))
        except ValueError:
            nums.append(0)
    while len(nums) < 4:
        nums.append(0)
    return tuple(nums)


def main() -> None:
    ver = _ver_tuple(about.APP_VERSION)
    print(f"""# UTF-8
VSVersionInfo(
  ffi=FixedFileInfo(
    filevers={ver},
    prodvers={ver},
    mask=0x3f,
    flags=0x0,
    OS=0x40004,
    fileType=0x1,
    subtype=0x0,
    date=(0, 0)
  ),
  kids=[
    StringFileInfo([
      StringTable(
        '040904B0',
        [StringStruct('CompanyName', '{about.AUTHOR}'),
         StringStruct('FileDescription', '{about.APP_NAME}'),
         StringStruct('FileVersion', '{about.APP_VERSION}.0'),
         StringStruct('InternalName', '{about.APP_ID}'),
         StringStruct('LegalCopyright', '© 2026 {about.AUTHOR} · {about.LICENSE}'),
         StringStruct('OriginalFilename', '{about.APP_ID}.exe'),
         StringStruct('ProductName', '{about.APP_NAME}'),
         StringStruct('ProductVersion', '{about.APP_VERSION}'),
         StringStruct('Comments', 'Build {about.BUILD_DATE} · {about.RELEASE_URL}')])
    ]),
    VarFileInfo([VarStruct('Translation', [1033, 1200])])
  ]
)""")


if __name__ == "__main__":
    main()