"""LLM 配置持久化（data/config.json 的 "llm" 键）。

用户在"模型设置"页面填写的 LLM 连接信息（接口地址、API KEY、模型名、
是否用离线 mock 模式等）需要保存到磁盘，下次启动时自动恢复——这个
"存档 / 读档"工作就由本模块完成。配置统一放在 data/config.json 这一个
JSON 文件里，本模块只负责其中 "llm" 这一个键，读写时都保留文件里
其他键不动，做到互不干扰。

配置文件同时承载界面偏好等后续键；本模块只管 llm 键，读写幂等。
"""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

from core.importer.llm_client import LLMConfig

# data/config.json 中 LLM 配置所在的键名
_LLM_KEY = "llm"


def _read_all(config_file: Path) -> dict:
    """读取整个 config.json 的内容。

    Args:
        config_file: 配置文件路径。

    Returns:
        解析出的 dict；文件不存在或内容不是合法 JSON 时返回空 dict
        （不抛异常，让上层按"没有配置"处理）。
    """
    try:
        return json.loads(config_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def load_llm_config(config_file: Path | str) -> LLMConfig:
    """读配置；缺文件/坏文件返回默认（mock=False）。

    Args:
        config_file: 配置文件路径（data/config.json）。

    Returns:
        LLMConfig 对象；"llm" 键不存在时返回各字段的默认值。
    """
    data = _read_all(config_file).get(_LLM_KEY) or {}
    if not isinstance(data, dict):
        return LLMConfig()
    # 只挑 LLMConfig 认识的键，手改 config.json 多写了字段（或旧版本
    # 遗留键）也不会让程序启动崩溃
    known = LLMConfig.__dataclass_fields__
    return LLMConfig(**{k: v for k, v in data.items() if k in known})


def save_llm_config(config_file: Path | str, cfg: LLMConfig) -> None:
    """合并写回 llm 键（保留其他键），目录自动创建。

    Args:
        config_file: 配置文件路径；父目录不存在会自动创建。
        cfg: 要保存的 LLM 配置对象（会转成 dict 写入）。
    """
    config_file = Path(config_file)
    config_file.parent.mkdir(parents=True, exist_ok=True)
    data = _read_all(config_file)
    # 只覆盖 "llm" 键，文件里其他键（界面偏好等）原样保留
    data[_LLM_KEY] = asdict(cfg)
    config_file.write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
