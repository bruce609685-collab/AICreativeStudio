# AICreativeStudio · AI影音创造工坊

一个 **外壳式** 桌面软件：主程序本身不内置任何 AI 模型调用逻辑，全部生图 / 生视频 / 生语音能力都来自 `scripts/` 目录下的**制式 Python 脚本**。

## 更新日志

| 版本 | 说明 |
|---|---|
| v0.1 | 初始版本 |
| v0.2 | 大幅度修改软件框架，由程序执行改为脚本执行 |
| v0.3 | 使用 Kimi K3 和 GLM-5.3 进行重构，首个公开版本 |

## 核心功能

1. **造脚本（智能导入）**：粘贴任意模型厂商的 API 接入文档，软件调用 LLM 解析文档，自动生成符合「脚本契约」的 Python 脚本
2. **用脚本（参数传入 + 产物展示）**：界面填参数 → 传给对应脚本执行 → 调用模型 API → 图片 / 视频 / 语音产物回传展示、播放、下载
3. **历史记录**：SQLite 落库，缩略图点击在预览宫格内回看
4. **模型设置**：API KEY 写入脚本文件；代码折叠编辑；未保存检测
5. **依赖管理**：FFmpeg 一键下载 + pip 依赖按脚本元数据自动检测安装

## 下载使用

从 [Releases](https://github.com/bruce609685-collab/AICreativeStudio/releases) 下载 `AICreativeStudio_v0.3_build0904.zip`，**解压即用**（零安装，Windows 10 / 11）。

首次使用：在「模型设置」或「智能导入」页填入你自己的 API KEY 与 LLM 接口配置即可。

## 开发

```bash
pip install -r requirements.txt
python main.py
```

技术栈：Python 3.12 + PySide6 + SQLite + pydantic，严格分层架构（domain / contract / infra / core 为 headless，仅 ui / bootstrap 引入 Qt）。

## 安全说明

- 仓库与发行包**零硬编码密钥**：示例脚本 `API_KEY` 一律置空，运行时从环境变量或「模型设置」注入
- LLM 配置不预填接口地址，需用户自行填写
- 请勿将你的 API KEY 提交到公开仓库

## License

本项目基于 **GNU GPL v3** 开源：

- ✅ 可以随意复制、修改、分发（含商用）
- ⚠️ 所有衍生作品必须以 GPL v3 同样开源，**不能闭源**
- ⚠️ 必须保留原作者版权声明

完整许可文本见 [LICENSE](LICENSE)。
