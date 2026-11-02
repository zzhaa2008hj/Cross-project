from datetime import date

from sqlalchemy import inspect

from app.models import Allocation, HistoryEntry, Milestone, MilestoneDependency, Person, Project


def test_health_and_meta(client):
    assert client.get("/api/health").json()["status"] == "ok"
    meta = client.get("/api/meta").json()
    assert meta["project_states"] == ["active", "on-hold", "done", "maintenance"]
    assert len(meta["milestone_states"]) == 6
    assert meta["allocation_supported"] is True


def test_project_crud_and_archive_keeps_history(client, db):
    created = client.post("/api/projects", json={"name": "北京仓储", "state": "active", "priority": "P1"})
    assert created.status_code == 201
    pid = created.json()["id"]

    updated = client.patch(f"/api/projects/{pid}", json={"state": "on-hold"})
    assert updated.status_code == 200
    assert updated.json()["state"] == "on-hold"

    # 非法状态
    bad = client.patch(f"/api/projects/{pid}", json={"state": "unknown"})
    assert bad.status_code == 422

    archived = client.post(f"/api/projects/{pid}/archive")
    assert archived.status_code == 200
    assert archived.json()["archived"] is True
    assert db.query(Project).filter(Project.id == pid).one().archived is True
    # 历史仍在
    assert db.query(HistoryEntry).filter(HistoryEntry.entity_id == pid).count() >= 3


def test_milestone_crud_assignee_no_allocation(client, db):
    pid = client.post("/api/projects", json={"name": "项目一"}).json()["id"]
    person = client.post("/api/persons", json={"name": "郑伊平", "roles": "执行"}).json()
    created = client.post(
        f"/api/projects/{pid}/milestones",
        json={
            "name": "节点一",
            "state": "未开始",
            "start_date": "2026-11-02",
            "commit_date": "2026-11-13",
            "assignee_id": person["id"],
        },
    )
    assert created.status_code == 201
    body = created.json()
    assert body["assignee_name"] == "郑伊平"
    assert body["buffer"]["window_workdays"] == 10
    assert body["buffer"]["internal_target"] == "2026-11-11"
    # 节点分派/执行人不产生任何占用记录（E2 起占用只由 Allocation 表达）
    assert db.query(Milestone).one().assignee_id == person["id"]
    assert db.query(Allocation).count() == 0
    week = client.get(f"/api/persons/{person['id']}/weeks/2026-11-02").json()
    assert week["total_days"] == 0
    assert week["allocations"] == []


def test_delete_with_reference_is_rejected_history_preserved(client, db):
    pid = client.post("/api/projects", json={"name": "项目二"}).json()["id"]
    a = client.post(f"/api/projects/{pid}/milestones", json={"name": "A"}).json()
    b = client.post(
        f"/api/projects/{pid}/milestones", json={"name": "B", "predecessor_ids": [a["id"]]}
    ).json()
    assert b["predecessor_ids"] == [a["id"]]

    resp = client.delete(f"/api/milestones/{a['id']}")
    assert resp.status_code == 409
    resp = client.delete(f"/api/projects/{pid}")
    assert resp.status_code == 409
    assert db.query(Milestone).count() == 2
    assert db.query(MilestoneDependency).count() == 1


def test_dependency_cycle_rejected(client):
    pid = client.post("/api/projects", json={"name": "项目三"}).json()["id"]
    a = client.post(f"/api/projects/{pid}/milestones", json={"name": "A"}).json()
    b = client.post(
        f"/api/projects/{pid}/milestones", json={"name": "B", "predecessor_ids": [a["id"]]}
    ).json()
    # B 依赖 A，再让 A 依赖 B → 成环，整笔拒绝
    resp = client.patch(f"/api/milestones/{a['id']}", json={"predecessor_ids": [b["id"]]})
    assert resp.status_code == 400
    assert "循环" in resp.json()["detail"]


def test_reschedule_api_preview_and_apply(client):
    pid = client.post("/api/projects", json={"name": "项目四"}).json()["id"]
    a = client.post(
        f"/api/projects/{pid}/milestones",
        json={
            "name": "A",
            "start_date": "2026-11-02",
            "commit_date": "2026-11-13",
            "state": "进行中",
        },
    ).json()
    b = client.post(
        f"/api/projects/{pid}/milestones",
        json={
            "name": "B",
            "start_date": "2026-11-16",
            "commit_date": "2026-11-20",
            "state": "未开始",
            "predecessor_ids": [a["id"]],
        },
    ).json()
    preview = client.post(
        "/api/reschedule/preview",
        json={
            "milestone_id": a["id"],
            "new_commit_date": "2026-11-15",
            "mode": "cascade",
        },
    )
    assert preview.status_code == 200
    payload = preview.json()
    assert payload["delta_days"] == 2
    assert {c["name"]: c["new_commit_date"] for c in payload["changes"]} == {
        "A": "2026-11-15",
        "B": "2026-11-22",
    }
    assert payload["versions"]

    # 缺原因
    bad = client.post(
        "/api/reschedule/apply",
        json={"preview_id": payload["preview_id"], "reason": "", "mode": "cascade"},
    )
    assert bad.status_code == 400

    applied = client.post(
        "/api/reschedule/apply",
        json={"preview_id": payload["preview_id"], "reason": "客户原因", "mode": "cascade"},
    )
    assert applied.status_code == 200
    assert {u["name"] for u in applied.json()["updated"]} == {"A", "B"}
    detail = client.get(f"/api/milestones/{b['id']}").json()
    assert detail["commit_date"] == "2026-11-22"


def test_demo_seed_creates_diamond(client):
    resp = client.post("/api/demo/seed")
    assert resp.status_code == 200
    body = resp.json()
    names = {m["name"] for m in body["milestones"]}
    assert {"节点A", "节点B", "节点C", "节点D"} <= names
    # 幂等
    again = client.post("/api/demo/seed").json()
    assert again["id"] == body["id"]
    assert len(again["milestones"]) == len(body["milestones"])


def test_import_api_dry_run_then_apply(client, db, tmp_path):
    from tests.test_importer import MILESTONE_TABLE, PERSONNEL, PROJECT_NOTE

    (tmp_path / "20_项目").mkdir(parents=True)
    (tmp_path / "99_系统").mkdir(parents=True)
    (tmp_path / "20_项目" / "里程碑.md").write_text(MILESTONE_TABLE, encoding="utf-8")
    (tmp_path / "99_系统" / "人员.md").write_text(PERSONNEL, encoding="utf-8")
    (tmp_path / "20_项目" / "示例项目.md").write_text(PROJECT_NOTE, encoding="utf-8")

    dry = client.post("/api/imports", json={"source_root": str(tmp_path)})
    assert dry.status_code == 201
    body = dry.json()
    assert body["mode"] == "dry_run"
    assert body["applied"] is False
    assert body["read_count"] == body["imported_count"] + body["skipped_count"] + body["failed_count"]
    assert db.query(Project).count() == 0

    applied = client.post("/api/imports", json={"source_root": str(tmp_path), "apply": True})
    assert applied.status_code == 201
    assert applied.json()["applied"] is True
    assert db.query(Project).count() == 1

    md = client.get(f"/api/imports/{applied.json()['id']}/report.md")
    assert md.status_code == 200
    assert "读入" in md.text
