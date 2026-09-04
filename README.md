# AICreativeStudio · AI影音创造工坊

一个外壳式 AI 影音创作桌面工具：主程序本身**不内置任何模型调用逻辑**，生图、生视频、生语音的能力全部来自使用LLM智能生成的 Python 脚本。软件只负责三件事——生成脚本、把参数传给脚本并执行、在软件中展示产物。

## 📜 更新日志

| 版本 | 说明 |
|---|---|
| v0.1 | 初始版本 |
| v0.2 | 大幅度修改软件框架，由程序执行改为脚本执行 |
| v0.3 | 使用 Kimi K3 和 GLM-5.3 进行重构，首个公开版本 |

> ⚠️ **当前为 v0.3 版**：还有很多 BUG，界面也很粗糙，欢迎提交 Issue / PR 帮忙改进！

## ✨ 功能一览

- **智能生成脚本**：在「智能导入」页面配置 LLM 模型，粘贴任意模型厂商的 API 接入文档，软件会调用 LLM 解析文档，自动生成符合软件使用要求的 Python 脚本——接入一个新模型，不用手写一行代码
- **三类创作页签**：AI 生图片 / AI 生视频 / AI 生语音，包含输入参数和输出预览
- **历史记录**：SQLite 落库，缩略图点击直接在预览宫格内回看，提示词一键回显
- **模型设置**：API KEY 写入脚本文件，代码折叠编辑，未保存切换有提醒
- **依赖自检**：FFmpeg 一键下载，pip 依赖按脚本元数据自动检测并引导安装

## 📥 下载安装

从 [Releases](https://github.com/bruce609685-collab/AICreativeStudio/releases) 下载最新 zip，**解压即用**（零安装，Windows 10 / 11）。

**首次使用**：

1. 打开「智能导入」页，配置你的 LLM 接口地址与密钥
2. 打开「模型设置」页，为你想用的脚本填入 API KEY
3. 打开生成页签，写提示词、选参数、点生成

## 🚀 从源码运行

```bash
git clone https://github.com/bruce609685-collab/AICreativeStudio.git
cd AICreativeStudio
pip install -r requirements.txt
python main.py
```

## 📂 项目结构

```
AICreativeStudio/
├── main.py          # 唯一入口
├── about.py         # 程序身份信息（名称/版本/作者/发布页）
├── scripts/         # 制式脚本（图/视/音三目录，官方示例 7 个）
├── templates/       # 提示词模板（智能导入用）
├── ui/              # 界面层（6 页签 + 控件库）
├── core/            # 核心服务（脚本注册/执行/导入管线）
├── contract/        # 外壳与脚本之间的接口约定
├── infra/           # 基础设施（SQLite 历史库/网络/媒体）
├── domain/          # 领域模型
├── tests/           # 测试（pytest，67 用例）
└── packaging/       # exe 版本资源生成
```

## 🛠 技术栈

| 层 | 选型 |
|---|---|
| 语言 | Python 3.12 |
| 界面 | PySide6（Qt） |
| 数据库 | SQLite |
| 打包 | PyInstaller（onedir，解压即用） |

架构上严格分层：`domain / contract / infra / core` 为 headless（不依赖 Qt），仅 `ui/` 引入 PySide6；脚本与主程序通过子进程 + JSON 协议通信，脚本崩溃不会拖垮主程序。

## 🔒 安全说明

- 请勿将你的 API KEY 提交到公开仓库

## 📄 License

本项目基于 **GNU GPL v3** 开源：

- ✅ 可以随意复制、修改、分发（含商用）
- ⚠️ 所有衍生作品必须以 GPL v3 同样开源，**不能闭源**
- ⚠️ 必须保留原作者版权声明

完整许可文本见 [LICENSE](LICENSE)。
