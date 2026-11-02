"""E4 Task 1：一致性快照与导出数据读取。"""
import base64
import sqlite3
import threading
import time
from pathlib import Path

import pytest

from app.services.snapshot import read_tables, snapshot_db, table_columns


def _make_db(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("CREATE TABLE projects (id INTEGER PRIMARY KEY, name TEXT)")
    conn.execute(
        "CREATE TABLE milestones (id INTEGER PRIMARY KEY, project_id INTEGER, name TEXT)"
    )
    conn.execute(
        "CREATE TABLE capacities (id INTEGER PRIMARY KEY, person_id INTEGER, days REAL)"
    )
    conn.commit()
    return conn


def test_snapshot_db_copies_all_tables(tmp_path):
    src = tmp_path / "src.db"
    conn = _make_db(src)
    conn.execute("INSERT INTO projects (id, name) VALUES (1, 'A')")
    conn.commit()
    conn.close()

    dest = tmp_path / "snap.db"
    assert snapshot_db(src, dest) == dest

    tables = read_tables(dest)
    assert tables["projects"][0]["name"] == "A"
    assert "milestones" in tables
    assert "capacities" in tables


def test_snapshot_db_refuses_to_overwrite_existing_file(tmp_path):
    src = tmp_path / "src.db"
    conn = _make_db(src)
    conn.commit()
    conn.close()

    dest = tmp_path / "snap.db"
    dest.write_text("stale")
    with pytest.raises(FileExistsError):
        snapshot_db(src, dest)
    assert dest.read_text() == "stale"


def test_snapshot_under_concurrent_write_is_consistent(tmp_path):
    src = tmp_path / "src.db"
    conn = _make_db(src)
    conn.commit()
    conn.close()

    stop = threading.Event()
    counter = {"n": 0}
    lock = threading.Lock()

    def writer():
        c = sqlite3.connect(src, timeout=10)
        i = 0
        while not stop.is_set():
            try:
                c.execute("BEGIN IMMEDIATE")
                i += 1
                c.execute(
                    "INSERT INTO projects (id, name) VALUES (?, ?)", (i, f"P{i}")
                )
                c.execute(
                    "INSERT INTO milestones (id, project_id, name) VALUES (?,?,?)",
                    (i, i, f"M{i}"),
                )
                c.commit()
                with lock:
                    counter["n"] = i
            except sqlite3.OperationalError:
                c.rollback()
        c.close()

    t = threading.Thread(target=writer, daemon=True)
    t.start()
    try:
        deadline = time.time() + 5
        while counter["n"] < 5 and time.time() < deadline:
            time.sleep(0.01)
        assert counter["n"] >= 5, "写入线程没有跑起来"

        snap = None
        deadline = time.time() + 15
        while time.time() < deadline:
            with lock:
                before = counter["n"]
            dest = tmp_path / f"snap-{before}.db"
            snapshot_db(src, dest)
            with lock:
                after = counter["n"]
            if after > before:
                snap = dest
                break
        assert snap is not None, "未能构造出快照期间存在并发写入的场景"

        tables = read_tables(snap)
        project_ids = {row["id"] for row in tables["projects"]}
        milestones = tables["milestones"]
        assert milestones, "快照里应当有数据"
        for row in milestones:
            assert row["project_id"] in project_ids, "快照出现了孤儿节点行"
    finally:
        stop.set()
        t.join(timeout=5)


def test_read_tables_keeps_null_and_zero_distinct(tmp_path):
    path = tmp_path / "c.db"
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE capacities (id INTEGER PRIMARY KEY, days REAL)")
    conn.execute("INSERT INTO capacities (id, days) VALUES (1, 0.0)")
    conn.execute("INSERT INTO capacities (id, days) VALUES (2, NULL)")
    conn.commit()
    conn.close()

    rows = {row["id"]: row for row in read_tables(path)["capacities"]}
    assert rows[1]["days"] == 0.0
    assert rows[2]["days"] is None


def test_read_tables_encodes_bytes_as_base64(tmp_path):
    path = tmp_path / "b.db"
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE blobs (id INTEGER PRIMARY KEY, payload BLOB)")
    conn.execute("INSERT INTO blobs (id, payload) VALUES (1, ?)", (b"\x00\x01\x02",))
    conn.commit()
    conn.close()

    row = read_tables(path)["blobs"][0]
    assert row["payload"] == base64.b64encode(b"\x00\x01\x02").decode("ascii")


def test_read_tables_skips_sqlite_internal_tables(tmp_path):
    path = tmp_path / "s.db"
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE projects (id INTEGER PRIMARY KEY)")
    conn.execute("CREATE INDEX idx_projects ON projects(id)")
    conn.commit()
    conn.close()

    tables = read_tables(path)
    assert list(tables) == ["projects"]


def test_table_columns_reports_primary_keys(tmp_path):
    path = tmp_path / "p.db"
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE projects (id INTEGER PRIMARY KEY, name TEXT)")
    conn.commit()
    conn.close()

    columns = table_columns(path)
    assert [c["name"] for c in columns["projects"]] == ["id", "name"]
    pk = [c for c in columns["projects"] if c["pk"]]
    assert [c["name"] for c in pk] == ["id"]
