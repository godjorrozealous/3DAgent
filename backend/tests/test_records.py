import records


def test_record_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setattr(records, "RECORDS_FILE", tmp_path / "recs.json")
    rec = records.create_record("500kV雅湖线 跳闸", "10:00:00")
    assert rec["id"] == 1
    records.attach_realtime(rec["id"], "# 实时报告", {"fault_type": "雷击"})
    records.attach_replay(rec["id"], "# 复盘报告", {"fault_type": "雷击"})
    records.set_objections(rec["id"], [{"kind": "diagnosis_objection", "text": "要考虑地形"}])
    records.attach_strategy(rec["id"], "夏季策略")
    got = records.get_record(1)
    assert got["realtime"]["report"] == "# 实时报告"
    assert got["replays"][0]["report"] == "# 复盘报告"
    assert got["objections"][0]["text"] == "要考虑地形"
    assert got["strategies"] == ["夏季策略"]
    assert len(records.list_records()) == 1


def test_corrupt_file_returns_empty(tmp_path, monkeypatch):
    f = tmp_path / "recs.json"
    f.write_text("not json", encoding="utf-8")
    monkeypatch.setattr(records, "RECORDS_FILE", f)
    assert records.list_records() == []
