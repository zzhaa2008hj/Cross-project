"""E4：手动备份触发与运行期库锁。"""
import pytest


@pytest.fixture()
def backup_env(tmp_path, monkeypatch):
    """把备份目录指到临时位置，避免污染真实数据目录。"""
    monkeypatch.setenv("CP_BACKUP_DIR", str(tmp_path / "backups"))
    return tmp_path


def test_backup_run_endpoint_publishes_backup(client, backup_env):
    client.post("/api/projects", json={"name": "甲项目"})

    resp = client.post("/api/backup/run")

    assert resp.status_code == 200
    body = resp.json()
    assert body["stamp"]
    assert body["db_path"].endswith("crossproject.db")
    backups = backup_env / "backups"
    published = [p for p in backups.iterdir() if p.is_dir()]
    assert len(published) == 1
    # 备份就是纯 SQLite 副本，没有导出产物
    assert [p.name for p in published[0].iterdir()] == ["crossproject.db"]


def test_backup_run_endpoint_repeated_in_same_second_still_succeeds(
    client, backup_env, monkeypatch
):
    """同一秒内重复触发备份：不应因版本号冲突直接失败。"""
    monkeypatch.setattr("app.api_backup.default_stamp", lambda: "20261102T000000Z")
    client.post("/api/projects", json={"name": "甲项目"})

    first = client.post("/api/backup/run")
    second = client.post("/api/backup/run")

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["stamp"] != second.json()["stamp"]
    published = [p for p in (backup_env / "backups").iterdir() if p.is_dir()]
    assert len(published) == 2
    assert all((p / "crossproject.db").exists() for p in published)


def test_app_holds_db_lock_while_running(client):
    """应用运行期持库锁：此时离线恢复必须被拒绝。"""
    from app.config import db_path
    from app.services.restore import assert_app_stopped, lock_path_for

    assert lock_path_for(db_path()).exists()
    with pytest.raises(RuntimeError):
        assert_app_stopped(db_path())
