import os
import tempfile

# 必须在导入 app.* 之前设置，engine 在导入期读取路径
_TMP = tempfile.mkdtemp(prefix="cp-e1-test-")
os.environ["CP_DATA_DIR"] = _TMP
os.environ.setdefault("CP_VAULT_DIR", "/home/hui/MyData/AI/my-vault")

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.db import Base, SessionLocal, engine  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Milestone, MilestoneDependency, Person, Project  # noqa: E402


@pytest.fixture()
def db():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture()
def client(db):
    def override_get_db():
        try:
            yield db
        finally:
            pass

    app.dependency_overrides[get_db_override_key()] = override_get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def get_db_override_key():
    from app.db import get_db

    return get_db


def make_project(db, name="测试项目", **kwargs) -> Project:
    project = Project(name=name, **kwargs)
    db.add(project)
    db.commit()
    db.refresh(project)
    return project


def make_milestone(db, project, name, **kwargs) -> Milestone:
    milestone = Milestone(project_id=project.id, name=name, **kwargs)
    db.add(milestone)
    db.commit()
    db.refresh(milestone)
    return milestone


def link(db, milestone_id, predecessor_id) -> None:
    db.add(MilestoneDependency(milestone_id=milestone_id, predecessor_id=predecessor_id))
    db.commit()
