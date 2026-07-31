"""测试隔离：records 持久化一律写临时目录，不触碰真实 backend/data/。"""
import pytest

import records


@pytest.fixture(autouse=True)
def _isolate_records_file(tmp_path, monkeypatch):
    monkeypatch.setattr(records, "RECORDS_FILE", tmp_path / "diagnosis_records.json")
