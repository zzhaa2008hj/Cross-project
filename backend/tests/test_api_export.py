"""E4 Task 5：导出预览 API 与手动备份触发。"""
import json
from pathlib import Path

import pytest


@pytest.fixture()
def export_env(tmp_path, monkeypatch):
    """把预览目录与备份目录指到临时位置，避免污染真实数据目录。"""
    monkeypatch.setenv("CP_EXPORT_DIR", str(tmp_path / "exports"))
    monkeypatch.setenv("CP_BACKUP_DIR", str(tmp_path / "backups"))
    return tmp_path


def test_preview_returns_snapshot_and_diff(client, export_env):
    client.post("/api/projects", json={"name": "甲项目"})

    resp = client.post("/api/export/preview")

    assert resp.status_code == 200
    body = resp.json()
    assert body["preview_id"]
    assert body["generated_at"]
    assert body["snapshot_id"].startswith("snap-")
    assert body["counts"]["projects"] == 1
    assert body["diff"]["is_first"] is True
    assert body["diff"]["tables"]["projects"]["added"] == 1
    assert "甲项目" in body["markdown"]
    assert "甲项目" in body["obsidian"]


def test_preview_diff_reflects_change_between_previews(client, export_env):
    client.post("/api/projects", json={"name": "甲项目"})
    client.post("/api/export/preview")

    client.post("/api/projects", json={"name": "乙项目"})
    body = client.post("/api/export/preview").json()

    assert body["diff"]["is_first"] is False
    projects = body["diff"]["tables"]["projects"]
    assert projects["added"] == 1
    assert projects["changed"] == 0


def test_preview_download_json_markdown_obsidian(client, export_env):
    client.post("/api/projects", json={"name": "甲项目"})
    preview_id = client.post("/api/export/preview").json()["preview_id"]

    as_json = client.get(f"/api/export/previews/{preview_id}/json")
    assert as_json.status_code == 200
    payload = json.loads(as_json.text)
    assert payload["counts"]["projects"] == 1

    markdown = client.get(f"/api/export/previews/{preview_id}/markdown")
    assert markdown.status_code == 200
    assert "# 跨项目管理软件导出" in markdown.text

    obsidian = client.get(f"/api/export/previews/{preview_id}/obsidian")
    assert obsidian.status_code == 200
    assert "跨项目管理软件摘要" in obsidian.text


def test_preview_list_returns_recent_previews(client, export_env):
    client.post("/api/export/preview")
    client.post("/api/export/preview")

    items = client.get("/api/export/previews").json()["items"]

    assert len(items) == 2
    assert items[0]["preview_id"]
    assert items[0]["snapshot_id"]


def test_unknown_preview_id_returns_404(client, export_env):
    resp = client.get("/api/export/previews/does-not-exist/json")
    assert resp.status_code == 404


def test_preview_id_with_traversal_returns_404(client, export_env):
    resp = client.get("/api/export/previews/..%2F..%2Fetc%2Fpasswd/json")
    assert resp.status_code == 404


def test_app_holds_db_lock_while_running(client):
    """应用运行期持库锁：此时离线恢复必须被拒绝。"""
    from app.config import db_path
    from app.services.restore import assert_app_stopped, lock_path_for

    assert lock_path_for(db_path()).exists()
    with pytest.raises(RuntimeError):
        assert_app_stopped(db_path())


def test_backup_run_endpoint_publishes_backup(client, export_env):
    client.post("/api/projects", json={"name": "甲项目"})

    resp = client.post("/api/backup/run")

    assert resp.status_code == 200
    body = resp.json()
    assert body["stamp"]
    backups = export_env / "backups"
    published = [p for p in backups.iterdir() if p.is_dir()]
    assert len(published) == 1
    assert (published[0] / "export.json").exists()
    assert (published[0] / "crossproject.db").exists()
