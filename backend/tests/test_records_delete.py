"""记录删除:delete_records 单删/多删/幂等 + WS delete_records 路由。"""
import json

import agent_manager
import records
from tests.test_agent_manager import FakeWS


def setup_tmp(monkeypatch, tmp_path):
    f = tmp_path / "diagnosis_records.json"
    monkeypatch.setattr(records, "RECORDS_FILE", f)
    return f


def test_delete_single_and_multi(monkeypatch, tmp_path):
    """删单条/多条:文件内容正确,返回删除条数。"""
    setup_tmp(monkeypatch, tmp_path)
    ids = [records.create_record(f"线路{i}", "12:00:00")["id"] for i in range(3)]
    assert records.delete_records([ids[0]]) == 1
    assert [r["id"] for r in records.list_records()] == [ids[1], ids[2]]
    assert records.delete_records([ids[1], ids[2]]) == 2
    assert records.list_records() == []


def test_delete_nonexistent_is_noop(monkeypatch, tmp_path):
    """删除不存在的 id:返回 0,文件不变(幂等不报错)。"""
    setup_tmp(monkeypatch, tmp_path)
    rec = records.create_record("线路A", "12:00:00")
    assert records.delete_records([999]) == 0
    assert len(records.list_records()) == 1
    assert records.get_record(rec["id"]) is not None


async def test_ws_delete_records_broadcasts_list(monkeypatch, tmp_path):
    """WS delete_records 路由:删除后广播最新 records_list。"""
    setup_tmp(monkeypatch, tmp_path)
    ids = [records.create_record(f"线路{i}", "12:00:00")["id"] for i in range(2)]
    mgr = agent_manager.AgentManager()
    ws = FakeWS()
    await mgr.connect(ws)
    ws.events.clear()
    await mgr.handle_message({"type": "delete_records", "ids": [ids[0]]})
    rl = [e for e in ws.events if e["type"] == "records_list"]
    assert len(rl) == 1
    assert [r["id"] for r in rl[0]["records"]] == [ids[1]]
