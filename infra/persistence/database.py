"""历史记录持久化（headless，SQLite 单文件 data/history.db）。

"持久化"指把数据长期保存到磁盘，程序关掉再打开数据还在。本文件
负责把每一次生成任务（无论成功失败）记入一个 SQLite 数据库——
它是 Python 内置的轻量级文件数据库，整个库就是 history.db 一个文件。

M3 实现：建表 / 增记录 / 按类别查询 / 清空。
三个生成页共用一张表，category 字段区分（image / video / audio）。
M3 起本库是历史记录的唯一权威来源（替换 M1 各页内置的演示数据）。
"""

from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path

# 允许的类别取值，与 domain.enums.MediaCategory 保持一致（文本形式）
CATEGORIES = ("image", "video", "audio")

# 建表语句（schema = 数据表的"图纸"）：
# - IF NOT EXISTS：表已存在就跳过，保证重复启动不报错；
# - DEFAULT ''：写入时漏掉的字段自动补空值，不强制每项都传；
# - 索引 idx_history_category 让"按类别查询"更快（不用全表扫描）
_SCHEMA = """
CREATE TABLE IF NOT EXISTS history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,               -- 完成时间（YYYY-MM-DD HH:MM:SS）
    category TEXT NOT NULL,         -- image / video / audio
    script_key TEXT NOT NULL DEFAULT '',
    prompt TEXT NOT NULL DEFAULT '',     -- 提示词/文本（失败记录也保留）
    params TEXT NOT NULL DEFAULT '{}',   -- 参数 JSON
    files TEXT NOT NULL DEFAULT '[]',    -- 产物文件 JSON（绝对路径列表）
    ok INTEGER NOT NULL DEFAULT 1,       -- 1 成功 / 0 失败
    code TEXT NOT NULL DEFAULT '',       -- 失败错误码（成功为空）
    message TEXT NOT NULL DEFAULT '',    -- 失败消息
    elapsed REAL NOT NULL DEFAULT 0      -- 耗时秒
);
CREATE INDEX IF NOT EXISTS idx_history_category ON history(category);
"""


class HistoryDatabase:
    """SQLite 历史库。headless（无 PySide6 依赖），可独立测试。

    关键属性：
    - _path：数据库文件路径（data/history.db）；
    - _conn：sqlite3 连接对象，后续所有读写都通过它。
    使用场景：启动时创建一次（见 app/application.py 的 run()），
    三个生成页共享同一实例读写历史记录。
    """

    def __init__(self, db_path: Path | str) -> None:
        """连接数据库并确保表结构就绪。

        参数 db_path：数据库文件路径（字符串或 Path 均可）。
        文件不存在会自动创建；父目录不存在也一并创建。
        """
        self._path = Path(db_path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self._path))
        # row_factory=Row：查询结果可以用列名访问（如 row["prompt"]），
        # 比默认的按下标访问更不容易读错列
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(_SCHEMA)
        self._conn.commit()

    # ------------------------------------------------------------------
    # 写
    # ------------------------------------------------------------------

    def add_record(self, *, category: str, script_key: str, prompt: str,
                   params: dict | None = None, files: list[str] | None = None,
                   ok: bool = True, code: str = "", message: str = "",
                   elapsed: float = 0.0) -> int:
        """插入一条历史记录，返回自增 id。

        参数（均为关键字参数）：
        - category：类别（image/video/audio，非法值抛 ValueError）；
        - script_key：脚本标识；prompt：提示词或文本（失败也保留，
          方便用户直接复用重试）；
        - params：参数字典；files：产物绝对路径列表（两者会被序列化
          成 JSON 文本存储）；
        - ok：成功与否；code/message：失败时的错误码与消息；
        - elapsed：耗时秒数。
        返回值：新记录的自增主键 id。
        """
        if category not in CATEGORIES:
            raise ValueError(f"category 必须是 {CATEGORIES}，实际为 {category!r}")
        # dict/list 不能直接存进 SQLite，先用 json.dumps 转成文本；
        # `or {}` / `or []` 把 None 统一成空容器
        cur = self._conn.execute(
            "INSERT INTO history (ts, category, script_key, prompt, params,"
            " files, ok, code, message, elapsed) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (
                time.strftime("%Y-%m-%d %H:%M:%S"),
                category,
                script_key or "",
                prompt or "",
                json.dumps(params or {}, ensure_ascii=False),
                json.dumps(files or [], ensure_ascii=False),
                1 if ok else 0,  # SQLite 没有布尔类型，用 1/0 表示
                code or "",
                message or "",
                float(elapsed or 0),
            ),
        )
        # commit 把改动真正写进文件；不提交的话断电/崩溃会丢这条记录
        self._conn.commit()
        return int(cur.lastrowid)

    # ------------------------------------------------------------------
    # 读
    # ------------------------------------------------------------------

    def list_records(self, category: str | None = None,
                     limit: int = 30) -> list[dict]:
        """按时间倒序查记录；category 为空查全部。每条含完整字段。

        参数 category：只查该类别（None = 不限）；limit：最多返回条数。
        返回值：字典列表（最新的在最前），其中 params/files 已从 JSON
        文本还原成字典/列表，ok 已转回布尔值，可直接供界面使用。
        """
        sql = "SELECT * FROM history"
        args: list = []
        if category:
            # 用 ? 占位符传参（而不是拼接字符串）是防 SQL 注入的标准做法
            sql += " WHERE category = ?"
            args.append(category)
        # id 是自增的，所以按 id 倒序 = 按时间倒序
        sql += " ORDER BY id DESC LIMIT ?"
        args.append(max(1, int(limit)))  # 防止 limit 传 0 或负数导致 SQL 报错
        rows = self._conn.execute(sql, args).fetchall()

        # 逐行做"类型还原"：数据库里存的是文本/整数，这里转回
        # 界面需要的 dict / list / bool
        records: list[dict] = []
        for row in rows:
            d = dict(row)
            d["ok"] = bool(d["ok"])
            try:
                d["params"] = json.loads(d["params"] or "{}")
            except json.JSONDecodeError:
                d["params"] = {}  # 脏数据兜底：解析失败也不让界面崩
            try:
                d["files"] = json.loads(d["files"] or "[]")
            except json.JSONDecodeError:
                d["files"] = []
            records.append(d)
        return records

    def count(self, category: str | None = None) -> int:
        """统计记录条数。参数 category：只统计该类别（None = 全部）。

        返回值：满足条件的记录总数（整数）。
        """
        if category:
            cur = self._conn.execute(
                "SELECT COUNT(*) FROM history WHERE category = ?", (category,))
        else:
            cur = self._conn.execute("SELECT COUNT(*) FROM history")
        # fetchone()[0]：COUNT 查询固定返回一行一列，取第一列即条数
        return int(cur.fetchone()[0])

    # ------------------------------------------------------------------
    # 清空 / 关闭
    # ------------------------------------------------------------------

    def clear(self, category: str | None = None) -> int:
        """清空记录（可只清某类别），返回删除条数。

        参数 category：只清该类别（None = 全部清空）。
        返回值：实际删除的记录条数。
        """
        if category:
            cur = self._conn.execute(
                "DELETE FROM history WHERE category = ?", (category,))
        else:
            cur = self._conn.execute("DELETE FROM history")
        self._conn.commit()
        # rowcount 是 DELETE/INSERT/UPDATE 影响的行数
        return int(cur.rowcount)

    def close(self) -> None:
        """关闭数据库连接。程序退出前调用，确保数据完整落盘。"""
        self._conn.close()
