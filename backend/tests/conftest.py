"""测试隔离：records 持久化一律写临时目录，不触碰真实 backend/data/。"""
import pytest

import agent_manager
import records


@pytest.fixture(autouse=True)
def _isolate_records_file(tmp_path, monkeypatch):
    monkeypatch.setattr(records, "RECORDS_FILE", tmp_path / "diagnosis_records.json")


@pytest.fixture(autouse=True)
def _stub_history_relation(monkeypatch):
    """诊断流会触发历史关联后台预取；默认桩为空结果，避免测试误连真实 PLD。

    需要验证预取行为的测试自行 monkeypatch 覆盖（后设置生效）。
    """
    async def _fake(sid):
        return {"success": True, "sections": []}

    monkeypatch.setattr(agent_manager.pld_client, "history_relation", _fake)

