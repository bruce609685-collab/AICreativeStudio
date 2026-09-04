"""历史记录库单测：建表 / 增删查 / 类别过滤 / JSON 字段往返。

测试分组：
  - test_add_and_list：写入一条完整记录（含 params/files 等 JSON 字段），
    再读出来逐字段比对，验证"写入→读出"往返不失真；
  - test_category_filter_and_fail_record：成功记录与失败记录（带错误码）
    混存，验证按类别过滤计数是否正确；
  - test_order_and_limit：连写多条后限制条数读取，验证"最新在前"的倒序；
  - test_clear：先按类别清一部分，再清空，验证删除计数与剩余条数。

每个测试都用 tempfile.TemporaryDirectory() 建一个**一次性的临时 SQLite
文件**，测完自动删除，绝不污染用户真实的历史数据库。

运行：python -m tests.test_history_db
"""

import sys
import tempfile
from pathlib import Path

from infra.persistence import HistoryDatabase


def test_add_and_list() -> None:
    """写入一条带完整字段的记录，读出后逐字段比对。

    重点验证 params（参数字典）和 files（输出文件列表）这两个
    结构化字段：SQLite 本身没有字典/列表类型，HistoryDatabase
    内部把它们序列化成 JSON 文本存储，读出时再反序列化回来。
    这里断言"存进去是什么、读出来还是什么"。
    """
    with tempfile.TemporaryDirectory() as tmp:
        db = HistoryDatabase(Path(tmp) / "history.db")
        rid = db.add_record(
            category="image", script_key="image_scripts/grok_3_image.py",
            prompt="测试提示词", params={"batch": 2, "mock": True},
            files=["C:/x/a.png", "C:/x/b.png"], ok=True, elapsed=1.5,
        )
        assert rid >= 1  # 返回的自增主键，首条记录应 >= 1
        rows = db.list_records(category="image")
        assert len(rows) == 1
        r = rows[0]
        assert r["ok"] is True
        assert r["params"] == {"batch": 2, "mock": True}   # JSON 往返后应完全一致
        assert r["files"] == ["C:/x/a.png", "C:/x/b.png"]
        assert r["prompt"] == "测试提示词"
        db.close()


def test_category_filter_and_fail_record() -> None:
    """混存成功/失败两类记录，验证类别过滤计数与失败详情字段。

    生成失败时（如 KEY 无效），记录会额外带 code（错误码）和
    message（错误信息）两个字段——历史页展示失败原因就靠它们。
    """
    with tempfile.TemporaryDirectory() as tmp:
        db = HistoryDatabase(Path(tmp) / "history.db")
        db.add_record(category="image", script_key="a.py", prompt="p1", ok=True)
        db.add_record(category="video", script_key="b.py", prompt="p2",
                      ok=False, code="AUTH_FAILED", message="KEY 无效")
        assert db.count() == 2                 # 总数
        assert db.count(category="image") == 1  # 按类别分别计数
        assert db.count(category="video") == 1

        vids = db.list_records(category="video")
        assert vids[0]["ok"] is False
        assert vids[0]["code"] == "AUTH_FAILED"
        assert vids[0]["message"] == "KEY 无效"
        db.close()


def test_order_and_limit() -> None:
    """连写 5 条后只取 3 条，验证"时间倒序、最新在前"。

    历史页永远把最新记录排在最上面，靠的就是 list_records
    默认按写入时间倒序（rows[0] 应是最后写入的 p4）。
    """
    with tempfile.TemporaryDirectory() as tmp:
        db = HistoryDatabase(Path(tmp) / "history.db")
        for i in range(5):
            db.add_record(category="image", script_key="a.py",
                          prompt=f"p{i}", ok=True)
        rows = db.list_records(limit=3)
        assert len(rows) == 3
        assert rows[0]["prompt"] == "p4"   # 时间倒序，最新在前
        db.close()


def test_clear() -> None:
    """先按类别清一部分，再全部清空，验证删除计数与剩余条数。

    clear(category=...) 对应历史页"清空图片历史"这类按钮；
    clear() 不带参数则是全部清空。
    """
    with tempfile.TemporaryDirectory() as tmp:
        db = HistoryDatabase(Path(tmp) / "history.db")
        db.add_record(category="image", script_key="a.py", prompt="p1")
        db.add_record(category="video", script_key="b.py", prompt="p2")
        assert db.clear(category="image") == 1  # 只删了 image 那 1 条
        assert db.count() == 1                  # 还剩 video 1 条
        assert db.clear() == 1                  # 清空剩余，又删 1 条
        assert db.count() == 0
        db.close()


if __name__ == "__main__":
    test_add_and_list()
    test_category_filter_and_fail_record()
    test_order_and_limit()
    test_clear()
    print("history db test passed")
    sys.exit(0)
