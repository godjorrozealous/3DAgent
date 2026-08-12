"""诊断结果集持久化：每次诊断（实时+复盘）写入 backend/data/diagnosis_records.json。"""
import json
import logging
from pathlib import Path

RECORDS_FILE = Path(__file__).parent / "data" / "diagnosis_records.json"


def _load() -> list:
    try:
        return json.loads(RECORDS_FILE.read_text(encoding="utf-8"))
    except Exception:
        logging.getLogger(__name__).warning("诊断记录文件损坏或不可读，按空记录处理: %s", RECORDS_FILE)
        return []


def _write(recs: list):
    RECORDS_FILE.parent.mkdir(parents=True, exist_ok=True)
    RECORDS_FILE.write_text(json.dumps(recs, ensure_ascii=False, indent=1), encoding="utf-8")


def list_records() -> list:
    return _load()


def get_record(rid: int):
    return next((r for r in _load() if r.get("id") == rid), None)


def create_record(line: str, time: str) -> dict:
    recs = _load()
    rec = {
        "id": max((r.get("id", 0) for r in recs), default=0) + 1,
        "line": line, "time": time,
        "realtime": None, "replays": [],
        "objections": [], "strategies": [],
    }
    recs.append(rec)
    _write(recs)
    return rec


def _update(rid: int, fn):
    recs = _load()
    for r in recs:
        if r.get("id") == rid:
            fn(r)
            _write(recs)
            return


def attach_realtime(rid: int, report: str, summary: dict):
    _update(rid, lambda r: r.__setitem__("realtime", {"report": report, "summary": summary}))


def attach_replay(rid: int, report: str, summary: dict):
    _update(rid, lambda r: r.setdefault("replays", []).append({"report": report, "summary": summary}))


def set_objections(rid: int, objections: list):
    _update(rid, lambda r: r.__setitem__("objections", list(objections)))


def attach_strategy(rid: int, name: str):
    _update(rid, lambda r: r.setdefault("strategies", []).append(name))


def delete_records(ids: list[int]) -> int:
    """按 id 批量删除记录,返回实际删除条数(幂等)。"""
    recs = _load()
    drop = set(ids)
    keep = [r for r in recs if r.get("id") not in drop]
    deleted = len(recs) - len(keep)
    if deleted:
        _write(keep)
    return deleted
