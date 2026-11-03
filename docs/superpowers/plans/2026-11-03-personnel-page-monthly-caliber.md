# 人员页月度口径改版 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把人员页从「四张卡片竖堆、只读周口径」改成「一张可横向对比的月度人员表 + 表下三标签页详情区」，并把新增 / 修改 / 启用禁用全部收到表上。

**Architecture:** 后端给 `Person` 加 `monthly_capacity` 列，新增只读月度服务 `services/monthly.py` 与两个接口（`GET /persons/roster`、`GET /persons/{id}/month`）；占用仍只从 `Allocation` 汇总，只是把汇总窗口从「一周」换成「自然月」。前端新增 `month.ts` / `useMonthParam.ts` 基建、`PersonFormDialog` 弹窗、`PersonMonthPanel` 面板，重写 `PersonPage.tsx`。工作台与项目页的周口径一律不动——工作台只改跳转链接的参数名。

**Tech Stack:** FastAPI + SQLAlchemy 2.x（同步 `Session`）+ SQLite（WAL）+ pytest；React 18 + TypeScript + Vite + vitest + @testing-library/react。

**Spec:** `docs/superpowers/specs/2026-11-03-personnel-page-monthly-caliber-design.md`

## Global Constraints

- 占用只认 `Allocation`；`Assignment` 只表达角色，**永不计入占用**。
- 人天粒度 0.5、非负；非法值返回 422，沿用 `backend/app/schemas.py:validate_days`。
- 周键 = 周一（Asia/Shanghai）；月 = 自然月；跨月周按「周一所在月」**整周**归属。
- 「未知 ≠ 0」只在周口径有效；人员页的核定人天**必填数字、默认 30、不留未知**。
- 后端 FastAPI + SQLAlchemy 2.x 同步 `Session` + SQLite（WAL）。
- **没有 Alembic**：加列走 `backend/app/db.py` 的 `_ADDED_COLUMNS` + 幂等 `ALTER TABLE ... ADD COLUMN`。
- 后端测试 `pytest backend/tests/<file> -v`（仓库根目录执行）；前端测试 `cd frontend && npx vitest run`；类型检查 `cd frontend && npx tsc --noEmit`。
- `frontend/src/components/WeekPanel.tsx`、`frontend/src/useWeekParam.ts` **不动**；工作台与项目页的周口径不动。
- 「核定人天」与「周容量」**不共用字段**（30 人天/月 vs 5 人天/周）；迁移时存量人员的 `weekly_capacity` 保持 5.0 不变。
- 不给已禁用的人加后端拦截：`POST /allocations` 不动。
- 提交信息中文，格式 `feat(<范围>): <内容>`；当前分支 `develop`，不改 `main`。

## Review Focus

规格是愿景文档：它说软件必须做什么，没说它会遇到什么输入。下面五条是规格暗示、但没有任何任务的测试直接覆盖的输入 / 失败模式，按「最容易咬到使用的人」排序；每条都在所属任务里补了钉住它的测试。

1. **月末跨月周**：周一落在本月、`week_end` 落在下月的那一周（2026-11-30 ~ 12-06），其分配必须整周算进 11 月；`week_end` 不参与归属判断。→ Task 2 的 `test_person_month_cross_month_week_belongs_to_november`
2. **非法月份参数**：`2026-13`、`2026-1`、`abc`、空串必须返回 400，不能 500。→ Task 3 的 `test_roster_invalid_month_returns_400`
3. **空库 / 无人的月份**：`roster` 仍返回该月全部周（4 或 5 个），`people` 为空列表，不报错。→ Task 3 的 `test_roster_empty_month_still_lists_weeks`
4. **已禁用的人仍可查详情、可改历史**：`GET /persons/{id}/month` 对已禁用的人照常返回完整数据；`include_archived=false` 时他只从 roster 消失，不从详情接口消失。→ Task 3 的 `test_archived_person_absent_from_roster_but_detail_ok`
5. **两个接口口径必须一致**：`/persons/roster` 与 `/persons/{id}/month` 对同人同月的 `used_days` 必须相等（roster 复用 `person_month` 的汇总，不另写一套）。→ Task 3 的 `test_roster_and_detail_agree_on_used_days`

---

### Task 1: `monthly_capacity` 数据层（模型 / 迁移 / Schema / 人员接口）

**Files:**
- Modify: `backend/app/models.py`（`Person` 类，`weekly_capacity` 之后加一列；`from sqlalchemy import (...)` 补 `text`）
- Modify: `backend/app/db.py:48-51`（`_ADDED_COLUMNS["persons"]`）
- Modify: `backend/app/schemas.py:50-96`（`PersonCreate` / `PersonUpdate` / `PersonOut`）
- Modify: `backend/app/api.py:112-155`（`create_person` / `update_person`）
- Test: `backend/tests/test_persons_capacity.py`（新建）
- Test: `backend/tests/test_migration.py`（扩展既有用例）

**Interfaces:**
- Consumes: `backend/app/schemas.py:validate_days`（`None`→`None`；拒 bool / 非有限 / 非数字 / 负数 / 非 0.5 步长）
- Produces:
  - `Person.monthly_capacity: Mapped[float]` — 非空，`default=30.0`，`server_default=text("30")`
  - `PersonCreate.monthly_capacity: float = 30.0`
  - `PersonUpdate.monthly_capacity: float | None = None` — **显式传 `null` 报 422**；字段缺失则不改动
  - `PersonOut.monthly_capacity: float`

- [ ] **Step 1: 写失败测试 `backend/tests/test_persons_capacity.py`**

```python
from app.models import Person


def _person(db, name="李四", monthly=30.0):
    p = Person(name=name, monthly_capacity=monthly, edited_in_app=True)
    db.add(p)
    db.commit()
    db.refresh(p)
    return p


def test_create_person_defaults_monthly_capacity_to_30(client):
    r = client.post("/persons", json={"name": "李四"})
    assert r.status_code == 201
    assert r.json()["monthly_capacity"] == 30.0


def test_create_person_accepts_monthly_capacity(client):
    r = client.post("/persons", json={"name": "李四", "monthly_capacity": 20.5})
    assert r.status_code == 201
    assert r.json()["monthly_capacity"] == 20.5


def test_patch_monthly_capacity(client, db):
    p = _person(db)
    r = client.patch(f"/persons/{p.id}", json={"monthly_capacity": 12})
    assert r.status_code == 200
    assert r.json()["monthly_capacity"] == 12.0


def test_patch_explicit_null_monthly_capacity_is_422(client, db):
    r = client.patch(f"/persons/{_person(db).id}", json={"monthly_capacity": None})
    assert r.status_code == 422


def test_patch_non_half_step_is_422(client, db):
    r = client.patch(f"/persons/{_person(db).id}", json={"monthly_capacity": 0.3})
    assert r.status_code == 422


def test_patch_without_field_leaves_value_untouched(client, db):
    r = client.patch(f"/persons/{_person(db).id}", json={"note": "只改备注"})
    assert r.status_code == 200
    assert r.json()["monthly_capacity"] == 30.0
```

- [ ] **Step 2: 跑测试确认失败**

Run: `pytest backend/tests/test_persons_capacity.py -v`
Expected: FAIL — 响应里没有 `monthly_capacity` 这个 key，且 `Person(...)` 不接受该构造参数。

- [ ] **Step 3: 在 `backend/app/models.py` 的 `Person` 上加列**

`weekly_capacity` 之后加：

```python
# 核定人天：每人每月的核定值，月度口径（默认 30，不留「未知」）
monthly_capacity: Mapped[float] = mapped_column(
    Float, nullable=False, default=30.0, server_default=text("30")
)
```

并在 `backend/app/models.py:10-19` 的 `from sqlalchemy import (...)` 里补上 `text`。

- [ ] **Step 4: 在 `backend/app/db.py:50` 的 `_ADDED_COLUMNS["persons"]` 补一条**

```python
"persons": [("skills", "TEXT DEFAULT ''"), ("monthly_capacity", "REAL NOT NULL DEFAULT 30")],
```

不需要单独的回填脚本：SQLite 的 `ADD COLUMN ... NOT NULL DEFAULT 30` 会把存量行直接补成 30。

- [ ] **Step 5: 在 `backend/app/schemas.py` 给三个模型加字段**

- `PersonCreate` 加 `monthly_capacity: float = 30.0`，并把字段名加进已有 `_check_days` 的 `field_validator` 目标列表。
- `PersonUpdate` 加 `monthly_capacity: float | None = None`，**单独**一个校验器（不要和 `weekly_capacity` 共用）：

```python
@field_validator("monthly_capacity", mode="before")
@classmethod
def _check_monthly(cls, v):
    if v is None:
        raise ValueError("核定人天不能为空，请填数字（默认 30）")
    return validate_days(v)
```

  Pydantic v2 默认不跑缺失字段的 `mode="before"` 校验器，所以「字段缺失」与「显式 null」可以区分：缺失 → 不改动；显式 null → 422。`weekly_capacity` 的既有校验器不动（它仍允许 `None` = 未知）。
- `PersonOut` 加 `monthly_capacity: float`。

- [ ] **Step 6: 在 `backend/app/api.py` 的 `create_person` / `update_person` 里传新字段**

- `create_person` 的 `Person(...)` 构造加 `monthly_capacity=payload.monthly_capacity`。
- `update_person` 里 `for field in ("roles", "skills", "note")` 那个空值归一化循环**不加** `monthly_capacity`（显式 null 已在 schema 层挡成 422，走不到这里）；`for field, value in data.items(): setattr(...)` 会自然带上它。

- [ ] **Step 7: 跑测试确认通过**

Run: `pytest backend/tests/test_persons_capacity.py -v`
Expected: PASS

- [ ] **Step 8: 扩展 `backend/tests/test_migration.py`，钉住存量行与周容量**

改 `test_add_person_skills_column_keeps_existing_values`：SELECT 加上 `monthly_capacity`，断言加两条——存量行被 `ADD COLUMN ... DEFAULT 30` 补成 30，且存量的 `weekly_capacity`（该用例插入的是 `4.5`）原样保留。注意取行是属性访问（`row.name`），不是 `row["name"]`：

```python
        with engine.connect() as conn:
            row = conn.execute(
                text(
                    "SELECT name, roles, weekly_capacity, skills, monthly_capacity"
                    " FROM persons WHERE id = 9001"
                )
            ).one()
        assert row.name == "老同事"
        assert row.roles == "统筹管理"
        assert row.weekly_capacity == 4.5
        assert row.skills in (None, "")
        # 存量人员的核定人天补成 30
        assert row.monthly_capacity == 30.0
```

**4.5 不是笔误**：该用例插入的存量周容量就是 `4.5`（老同事只给半天容量）。写 `5.0` 会让测试失败。

- [ ] **Step 9: 跑迁移测试确认通过**

Run: `pytest backend/tests/test_migration.py -v`
Expected: PASS

- [ ] **Step 10: 提交**

```bash
git add backend/app/models.py backend/app/db.py backend/app/schemas.py backend/app/api.py backend/tests/test_persons_capacity.py backend/tests/test_migration.py
git commit -m "feat(人员页): 核定人天列 monthly_capacity（默认 30）与存量迁移"
```

---

### Task 2: 月度原语 + 单人月度详情接口

**Files:**
- Create: `backend/app/services/monthly.py`
- Modify: `backend/app/schemas.py`（加 `MonthProjectUse` / `MonthWeekOut` / `MonthPersonDetail`）
- Modify: `backend/app/api.py`（加 `GET /persons/{person_id}/month`）
- Test: `backend/tests/test_monthly.py`（新建）

**Interfaces:**
- Consumes:
  - `backend/app/services/weekly.py`：`week_end(week: date) -> date`、`allocation_out(db, alloc) -> AllocationOut`、`assignment_out(db, item) -> AssignmentOut`、`is_reviewed(db, person_id, week) -> bool`
  - `backend/app/models.py`：`Person`、`Project`、`Allocation`、`Assignment`
- Produces:
  - `monthly.parse_month(month: str) -> tuple[int, int]` — 非法格式抛 `HTTPException(status_code=400)`
  - `monthly.month_weeks(month: str) -> list[str]` — 该月各周周一的 ISO 字符串，升序
  - `monthly.person_month(db: Session, person: Person, month: str) -> MonthPersonDetail`
  - `MonthWeekOut(week: str, week_end: str, total_days: float, reviewed: bool, allocations: list[AllocationOut])`
  - `MonthProjectUse(project_id: int, project_name: str, roles: list[str] = [], days: float = 0.0, has_allocation: bool = False, has_assignment: bool = False)`
  - `MonthPersonDetail(person_id: int, month: str, monthly_capacity: float, used_days: float, over_days: float | None, remaining_days: float | None, reviewed: bool, weeks: list[MonthWeekOut], assignments: list[AssignmentOut], projects: list[MonthProjectUse])`
  - `GET /persons/{person_id}/month?month=YYYY-MM` → `MonthPersonDetail`

- [ ] **Step 1: 写失败测试 `backend/tests/test_monthly.py`**

```python
from datetime import date

from app.models import Allocation, Assignment, Person, Project, WeekReview
from tests.conftest import make_milestone


def _person(db, name="傅相杰", monthly=30.0):
    p = Person(name=name, monthly_capacity=monthly, edited_in_app=True)
    db.add(p)
    db.commit()
    db.refresh(p)
    return p


def _project(db, name):
    proj = Project(name=name, state="active", edited_in_app=True)
    db.add(proj)
    db.commit()
    db.refresh(proj)
    return proj


def _alloc(db, person, project, week, days, milestone_id=None):
    a = Allocation(
        person_id=person.id,
        project_id=project.id,
        week=date.fromisoformat(week),
        days=days,
        milestone_id=milestone_id,
    )
    db.add(a)
    db.commit()
    db.refresh(a)
    return a


def _review(db, person, week, reviewed=True):
    db.add(WeekReview(person_id=person.id, week=date.fromisoformat(week), reviewed=reviewed))
    db.commit()


def test_person_month_weeks_and_occupancy(client, db):
    p = _person(db)
    proj = _project(db, "贵州矿产预测")
    _alloc(db, p, proj, "2026-11-02", 10)
    _alloc(db, p, proj, "2026-11-02", 0.5)
    _alloc(db, p, proj, "2026-11-09", 5)
    # 上一个月的分配不计入本月
    _alloc(db, p, proj, "2026-10-26", 8)

    r = client.get(f"/persons/{p.id}/month", params={"month": "2026-11"})
    assert r.status_code == 200
    body = r.json()
    # MonthPersonDetail.weeks 是 list[MonthWeekOut]（对象），不是字符串列表；
    # 字符串列表的是 MonthRosterOut.weeks（见 Task 3）。
    assert [w["week"] for w in body["weeks"]] == [
        "2026-11-02", "2026-11-09", "2026-11-16", "2026-11-23", "2026-11-30",
    ]
    assert body["used_days"] == 15.5
    assert body["over_days"] is None
    # 本月有分配的周还没核对 → 不给精确剩余
    assert body["remaining_days"] is None
    assert body["reviewed"] is False


def test_person_month_cross_month_week_belongs_to_november(client, db):
    p = _person(db)
    proj = _project(db, "贵州矿产预测")
    # 周一 2026-11-30，week_end 是 12-06 —— 整周算进 11 月
    _alloc(db, p, proj, "2026-11-30", 4)
    _alloc(db, p, proj, "2026-10-26", 99)  # 10 月的周，不算

    body = client.get(f"/persons/{p.id}/month", params={"month": "2026-11"}).json()
    assert body["used_days"] == 4
    # MonthWeekOut 是对象；下一行断言 week 键，再下一行取整条对象
    assert body["weeks"][-1]["week"] == "2026-11-30"
    detail = body["weeks"][-1]
    assert detail["total_days"] == 4
    assert detail["week_end"] == "2026-12-06"


def test_person_month_over_days(client, db):
    p = _person(db, monthly=20.0)
    proj = _project(db, "贵州矿产预测")
    _alloc(db, p, proj, "2026-11-02", 18.5)
    _review(db, p, "2026-11-02")

    body = client.get(f"/persons/{p.id}/month", params={"month": "2026-11"}).json()
    assert body["used_days"] == 18.5
    assert body["over_days"] is None
    assert body["remaining_days"] == 1.5
    assert body["reviewed"] is True


def test_person_month_over_days_when_exceeded(client, db):
    p = _person(db, monthly=10.0)
    proj = _project(db, "贵州矿产预测")
    _alloc(db, p, proj, "2026-11-02", 12.5)
    _review(db, p, "2026-11-02")

    body = client.get(f"/persons/{p.id}/month", params={"month": "2026-11"}).json()
    assert body["over_days"] == 2.5
    # 超额时剩余为负值也照给（口径：剩余 = capacity - used）
    assert body["remaining_days"] == -2.5


def test_person_month_remaining_blocked_by_unreviewed_alloc_week(client, db):
    p = _person(db, monthly=20.0)
    proj = _project(db, "贵州矿产预测")
    _alloc(db, p, proj, "2026-11-02", 5)
    _alloc(db, p, proj, "2026-11-09", 7)
    _review(db, p, "2026-11-02")          # 只有一周核对过

    body = client.get(f"/persons/{p.id}/month", params={"month": "2026-11"}).json()
    assert body["reviewed"] is False
    assert body["remaining_days"] is None


def test_person_month_empty_weeks_do_not_block_reviewed(client, db):
    p = _person(db, monthly=20.0)
    proj = _project(db, "贵州矿产预测")
    _alloc(db, p, proj, "2026-11-02", 5)
    _review(db, p, "2026-11-02")
    # 本月其余周都是空周，且没核对 —— 不参与判定

    body = client.get(f"/persons/{p.id}/month", params={"month": "2026-11"}).json()
    assert body["reviewed"] is True
    assert body["remaining_days"] == 15.0


def test_person_month_zero_allocation_is_fully_remaining(client, db):
    p = _person(db, monthly=30.0)

    body = client.get(f"/persons/{p.id}/month", params={"month": "2026-11"}).json()
    assert body["used_days"] == 0
    assert body["reviewed"] is True
    assert body["remaining_days"] == 30.0
    assert body["projects"] == []


def test_person_month_adding_alloc_to_reviewed_week_reverts_review(client, db):
    p = _person(db, monthly=30.0)
    proj = _project(db, "贵州矿产预测")
    mile = make_milestone(db, proj, "节点一")
    _alloc(db, p, proj, "2026-11-02", 5)
    _review(db, p, "2026-11-02")
    assert client.get(f"/persons/{p.id}/month", params={"month": "2026-11"}).json()["reviewed"] is True

    # 往一个空周加分配 → 该周未核对 → 整月退回「待核对」
    r = client.post(
        "/allocations",
        json={"person_id": p.id, "project_id": proj.id, "week": "2026-11-16",
              "days": 2, "milestone_id": mile.id},
    )
    assert r.status_code == 201
    body = client.get(f"/persons/{p.id}/month", params={"month": "2026-11"}).json()
    assert body["reviewed"] is False
    assert body["remaining_days"] is None
    assert body["used_days"] == 7


def test_person_month_projects_merge_allocation_and_assignment(client, db):
    p = _person(db)
    p1 = _project(db, "贵州矿产预测")
    p2 = _project(db, "北京仓储")
    _alloc(db, p, p1, "2026-11-02", 10)
    db.add(Assignment(person_id=p.id, project_id=p2.id, role="项目负责人"))
    db.add(Assignment(person_id=p.id, project_id=p2.id, role="业务对接"))
    db.commit()

    body = client.get(f"/persons/{p.id}/month", params={"month": "2026-11"}).json()
    by_id = {row["project_id"]: row for row in body["projects"]}
    assert by_id[p1.id] == {
        "project_id": p1.id, "project_name": "贵州矿产预测", "roles": [],
        "days": 10.0, "has_allocation": True, "has_assignment": False,
    }
    assert by_id[p2.id] == {
        "project_id": p2.id, "project_name": "北京仓储",
        "roles": ["项目负责人", "业务对接"],
        "days": 0.0, "has_allocation": False, "has_assignment": True,
    }


def test_person_month_invalid_month_returns_400(client, db):
    p = _person(db)
    for bad in ("2026-13", "2026-1", "abc", ""):
        assert client.get(f"/persons/{p.id}/month", params={"month": bad}).status_code == 400
```

`make_milestone` 是 `conftest.py` 里的**普通函数**，不是 fixture（签名 `make_milestone(db, project, name, **kwargs)`），所以在文件头 `from tests.conftest import make_milestone` 直接调用即可（`backend/tests/test_reschedule.py:6` 就是这么用的），不要在本文件里重写。`db.add(Assignment(...))` 需要 `Assignment` 已从 `app.models` 导入——第 221 行的 import 已含它。

- [ ] **Step 2: 跑测试确认失败**

Run: `pytest backend/tests/test_monthly.py -v`
Expected: FAIL — `ImportError: cannot import name 'monthly' from 'app.services'`（模块还不存在）。

- [ ] **Step 3: 在 `backend/app/schemas.py` 加三个响应模型**

按 Interfaces 里写的形状加 `MonthProjectUse` / `MonthWeekOut` / `MonthPersonDetail`。`MonthProjectUse.roles` 必须是 `list[str]`（`Assignment` 唯一键含 role，同人同项目可挂多个角色），默认 `[]`。

- [ ] **Step 4: 写 `backend/app/services/monthly.py`**

`parse_month` + `month_weeks` 是规格钉死的算法，照抄（文件头需要 `import calendar`、`from datetime import date, timedelta`、`from fastapi import HTTPException`）：

```python
def parse_month(month: str) -> tuple[int, int]:
    """解析 YYYY-MM；非法格式返回 400，不抛 500。"""
    parts = (month or "").split("-")
    if len(parts) != 2 or not all(p.isdigit() for p in parts):
        raise HTTPException(status_code=400, detail="月份格式应为 YYYY-MM")
    year, mon = int(parts[0]), int(parts[1])
    if not 1 <= mon <= 12:
        raise HTTPException(status_code=400, detail="月份格式应为 YYYY-MM")
    return year, mon


def month_weeks(month: str) -> list[str]:
    """该自然月内所有「周一落在该月」的日期，升序。"""
    year, mon = parse_month(month)
    last_day = calendar.monthrange(year, mon)[1]
    d = date(year, mon, 1)
    while d.weekday() != 0:          # 找到该月第一个周一
        d = d + timedelta(days=1)
    out = []
    # 收尾条件必须是「日期」比较，不能是 d.day：
    # 2026-11-30 那一周收完后 d 变成 2026-12-07，d.day == 7 <= 30 会把它错收进 11 月，
    # 再往后每跨一个月都继续收，直到溢出。
    while d <= date(year, mon, last_day):   # 周一落在本月才收，跨月的不收
        out.append(d.isoformat())
        d = d + timedelta(days=7)
    return out
```

`person_month(db, person, month)` 的步骤：

1. `weeks = [date.fromisoformat(w) for w in month_weeks(month)]`
2. 分配：`select(Allocation).where(Allocation.person_id == person.id, Allocation.week.in_(weeks))`
3. 职责：`select(Assignment).where(Assignment.person_id == person.id)`
4. `used_days = round(sum(a.days for a in allocations), 4)`；`over_days = round(used - person.monthly_capacity, 4) if used > person.monthly_capacity else None`
5. 核对判定：`alloc_weeks = {a.week for a in allocations}`；`reviewed = all(is_reviewed(db, person.id, w) for w in alloc_weeks)` —— 空集合上 `all()` 为 `True`，正好命中「零分配的人 `reviewed=True`、`remaining == capacity`」这条口径，不用写特例。
6. `remaining_days = round(person.monthly_capacity - used, 4) if reviewed else None`
7. `projects`：先按 `project_id` 建 `MonthProjectUse` 字典，分配的累加 `days` 并置 `has_allocation=True`，职责的把 `role` 并进 `roles` 并置 `has_assignment=True`；补 `project_name`（用 `db.get(Project, pid)`）；最后按 `project_id` 升序输出。
8. `weeks` 明细：每周一格 `MonthWeekOut`，`week` 是 `w.isoformat()`，`week_end` 用 `weekly_service.week_end(w).isoformat()`，`total_days` 是该周分配之和，`reviewed` 用 `is_reviewed`，`allocations` 用 `weekly_service.allocation_out(db, a)`。
   - **`week`/`week_end` 必须显式 `.isoformat()`**：`MonthWeekOut.week` 是 `str`，而 `Allocation.week`/`WeekReview.week` 在 SQLAlchemy 里都是 `Date` 列，取出来就是 `datetime.date`。Pydantic v2 默认**不**把 `date` 自动转成 `str`（会抛 ValidationError），所以不转字符串接口直接 500。
   - `Allocation.week` 是 `Date` 列，所以第 5 步的 `alloc_weeks` 里装的已经是 `date`，`is_reviewed(db, person.id, w)` 直接传 `w` 即可，**不要**再 `date.fromisoformat(w)`（那是对字符串才需要的）。
9. `assignments` 用 `weekly_service.assignment_out(db, item)`。

- [ ] **Step 5: 在 `backend/app/api.py` 加路由**

```python
@router.get("/persons/{person_id}/month", response_model=MonthPersonDetail)
def get_person_month(
    person_id: int, month: str = Query(...), db: Session = Depends(get_db)
):
    """某人某个自然月的全量视图（只读）。"""
    person = db.get(Person, person_id)
    if person is None:
        raise HTTPException(status_code=404, detail="人员不存在")
    return monthly_service.person_month(db, person, month)
```

`monthly_service` 按 `backend/app/api.py:44-46` 既有风格导入（`from .services import monthly as monthly_service`）；`MonthPersonDetail` 加进 `backend/app/api.py:23-47` 的 schema import 块。

- [ ] **Step 6: 跑测试确认通过**

Run: `pytest backend/tests/test_monthly.py -v`
Expected: PASS

- [ ] **Step 7: 提交**

```bash
git add backend/app/services/monthly.py backend/app/schemas.py backend/app/api.py backend/tests/test_monthly.py
git commit -m "feat(人员页): 月度原语与单人月度详情接口"
```

---

### Task 3: roster 表接口

**Files:**
- Modify: `backend/app/services/monthly.py`（加 `roster`）
- Modify: `backend/app/schemas.py`（加 `MonthPersonRow` / `MonthRosterOut`）
- Modify: `backend/app/api.py`（加 `GET /persons/roster`）
- Test: `backend/tests/test_monthly.py`（追加用例）

**Interfaces:**
- Consumes: `monthly.person_month(db, person, month) -> MonthPersonDetail`、`monthly.month_weeks(month) -> list[str]`
- Produces:
  - `monthly.roster(db: Session, month: str, include_archived: bool) -> MonthRosterOut`
  - `MonthPersonRow(person_id: int, name: str, skills: str, roles: str, note: str, monthly_capacity: float, weekly_capacity: float | None, used_days: float, over_days: float | None, remaining_days: float | None, reviewed: bool, archived: bool, projects: list[MonthProjectUse])`
  - `MonthRosterOut(month: str, weeks: list[str], people: list[MonthPersonRow])`
  - `GET /persons/roster?month=YYYY-MM&include_archived=false` → `MonthRosterOut`

- [ ] **Step 1: 追加失败测试到 `backend/tests/test_monthly.py`**

```python
def _roster(client, month="2026-11", include_archived=False):
    r = client.get(
        "/persons/roster",
        params={"month": month, "include_archived": include_archived},
    )
    assert r.status_code == 200
    return r.json()


def test_roster_lists_active_people_sorted_by_name(client, db):
    a = _person(db, "张三2")
    b = _person(db, "傅相杰")
    body = _roster(client)
    assert [p["name"] for p in body["people"]] == ["傅相杰", "张三2"]
    assert body["month"] == "2026-11"
    assert len(body["weeks"]) == 5


def test_roster_excludes_archived_by_default_and_appends_at_end(client, db):
    active = _person(db, "傅相杰")
    dead = _person(db, "张三2")
    dead.archived = True
    db.commit()

    assert [p["name"] for p in _roster(client)["people"]] == ["傅相杰"]

    body = _roster(client, include_archived=True)
    assert [p["name"] for p in body["people"]] == ["傅相杰", "张三2"]
    assert body["people"][-1]["archived"] is True
    assert body["people"][0]["archived"] is False


def test_roster_invalid_month_returns_400(client, db):
    for bad in ("2026-13", "2026-1", "abc", ""):
        assert client.get("/persons/roster", params={"month": bad}).status_code == 400


def test_roster_empty_month_still_lists_weeks(client, db):
    body = _roster(client, month="2027-02")
    assert body["people"] == []
    assert body["weeks"] == ["2027-02-01", "2027-02-08", "2027-02-15", "2027-02-22"]


def test_archived_person_absent_from_roster_but_detail_ok(client, db):
    dead = _person(db, "张三2")
    dead.archived = True
    proj = _project(db, "贵州矿产预测")
    _alloc(db, dead, proj, "2026-11-02", 10)
    db.commit()

    assert [p["name"] for p in _roster(client)["people"]] == []

    detail = client.get(f"/persons/{dead.id}/month", params={"month": "2026-11"})
    assert detail.status_code == 200
    assert detail.json()["used_days"] == 10


def test_roster_and_detail_agree_on_used_days(client, db):
    p = _person(db, "傅相杰")
    proj = _project(db, "贵州矿产预测")
    _alloc(db, p, proj, "2026-11-02", 10)
    _alloc(db, p, proj, "2026-11-09", 5)
    _alloc(db, p, proj, "2026-11-30", 4.5)

    from_roster = _roster(client)["people"][0]
    from_detail = client.get(f"/persons/{p.id}/month", params={"month": "2026-11"}).json()
    assert from_roster["used_days"] == from_detail["used_days"] == 19.5
    assert from_roster["remaining_days"] == from_detail["remaining_days"]
    assert from_roster["reviewed"] == from_detail["reviewed"]
    assert [x["project_id"] for x in from_roster["projects"]] == [
        x["project_id"] for x in from_detail["projects"]
    ]


def test_roster_projects_merge_allocation_and_assignment_with_roles(client, db):
    p = _person(db, "傅相杰")
    p1 = _project(db, "贵州矿产预测")
    p2 = _project(db, "北京仓储")
    _alloc(db, p, p1, "2026-11-02", 10)
    db.add(Assignment(person_id=p.id, project_id=p2.id, role="项目负责人"))
    db.add(Assignment(person_id=p.id, project_id=p2.id, role="业务对接"))
    db.commit()

    row = _roster(client)["people"][0]
    # projects 按 project_id 升序（见本 Task Step 4 第 7 步），所以 p1 在前、p2 在后；
    # 但仍用 id 索引，别靠位置——位置一旦写反，测试会静默通过错误的排序。
    by_id = {u["project_id"]: u for u in row["projects"]}
    assert by_id[p1.id] == {
        "project_id": p1.id, "project_name": "贵州矿产预测", "roles": [],
        "days": 10.0, "has_allocation": True, "has_assignment": False,
    }
    assert by_id[p2.id] == {
        "project_id": p2.id, "project_name": "北京仓储",
        "roles": ["项目负责人", "业务对接"],
        "days": 0.0, "has_allocation": False, "has_assignment": True,
    }
    # 排序本身另钉一条：project_id 升序
    assert [u["project_id"] for u in row["projects"]] == sorted(u["project_id"] for u in row["projects"])
```

注意 `test_roster_empty_month_still_lists_weeks` 里 2027-02 的期望周列表：2027-02-01 是周一，故为 `02-01 / 02-08 / 02-15 / 02-22`（02-28 是周日，2 月只有 28 天，所以 4 周）。写测试前先用 `python -c` 核一遍该月的周一序列，别照抄。

- [ ] **Step 2: 跑测试确认失败**

Run: `pytest backend/tests/test_monthly.py -v`
Expected: FAIL — `GET /persons/roster` 返回 404。

- [ ] **Step 3: 在 `backend/app/schemas.py` 加 `MonthPersonRow` / `MonthRosterOut`**

按 Interfaces 里的形状加。

- [ ] **Step 4: 在 `backend/app/services/monthly.py` 加 `roster`**

```python
def roster(db: Session, month: str, include_archived: bool) -> MonthRosterOut:
    """某个自然月的人员总表。已禁用的人排在启用的人之后（按 archived 升序）。"""
    stmt = select(Person).order_by(Person.archived, Person.name)
    if not include_archived:
        stmt = stmt.where(Person.archived.is_(False))
    people = db.execute(stmt).scalars().all()
    rows = []
    for person in people:
        detail = person_month(db, person, month)   # 复用同一套汇总原语
        rows.append(
            MonthPersonRow(
                person_id=person.id,
                name=person.name,
                skills=person.skills,
                roles=person.roles,
                note=person.note,
                monthly_capacity=detail.monthly_capacity,
                weekly_capacity=person.weekly_capacity,
                used_days=detail.used_days,
                over_days=detail.over_days,
                remaining_days=detail.remaining_days,
                reviewed=detail.reviewed,
                archived=person.archived,
                projects=detail.projects,
            )
        )
    return MonthRosterOut(month=month, weeks=month_weeks(month), people=rows)
```

**这里逐人调 `person_month` 是有意的 N+1**：本应用的人员量级是「个位数到十几个」，一次 roster 逐人取可接受，换来的是 roster 与详情接口共用同一份汇总逻辑（`Review Focus` 第 5 条就是靠这个结构保证的）。不为此引入批量查询。

**`MonthPersonRow` 比 spec §6.4 多一列 `weekly_capacity: float | None`**（spec 的模型里没有）：roster 行是详情区「资料」标签页的字段来源——它已经带着姓名 / 能力标签 / 角色标签 / 备注 / 核定人天这五个资料字段，周容量是资料页唯一缺的那个（spec §5.2「资料标签页保留『默认周容量（周口径用）』字段」）。把它并进 roster 行，比让「资料」标签页再调一次 `api.listPersons()` 少一次往返，也让「资料页展示的六项」来自同一个对象。取值 `person.weekly_capacity`（周口径、允许未知，spec §9.4 说存量 5.0 不动）。Task 3 的既有断言只钉 `name` / `projects` / 汇总数字，加这一列不破坏任何一条。

- [ ] **Step 5: 在 `backend/app/api.py` 加路由**

```python
@router.get("/persons/roster", response_model=MonthRosterOut)
def get_monthly_roster(
    month: str = Query(...),
    include_archived: bool = False,
    db: Session = Depends(get_db),
):
    """某月的人员总表（只读）。"""
    return monthly_service.roster(db, month, include_archived)
```

把 `/persons/roster` 注册在 `/persons/{person_id}/month` **之前**，`MonthPersonRow` / `MonthRosterOut` 加进 schema import 块。

- [ ] **Step 6: 跑测试确认通过**

Run: `pytest backend/tests/test_monthly.py -v`
Expected: PASS

- [ ] **Step 7: 跑后端全量测试确认没有回归**

Run: `pytest backend/tests/ -q`
Expected: PASS

- [ ] **Step 8: 提交**

```bash
git add backend/app/services/monthly.py backend/app/schemas.py backend/app/api.py backend/tests/test_monthly.py
git commit -m "feat(人员页): 月度人员总表接口 roster"
```

---

### Task 4: 前端月度基建

**Files:**
- Create: `frontend/src/month.ts`
- Create: `frontend/src/month.test.ts`
- Create: `frontend/src/useMonthParam.ts`
- Modify: `frontend/src/types.ts`
- Modify: `frontend/src/api.ts`

**Interfaces:**
- Consumes: `frontend/src/week.ts` 的 `weekKeyOf(date: string) -> string`（取周一）。**`todayInShanghai` 不可用**：它在 `week.ts` 里是模块私有、且返回的是 `en-CA` 格式字符串（`"2026-11-03"`），不是 `Date`，也没有导出。`month.ts` 自己实现 `currentMonth()`（见 Step 3），不要改 `week.ts`。
- Produces:
  - `month.ts`：`currentMonth(now?: Date): string`、`shiftMonth(month: string, delta: number): string`、`monthLabel(month: string): string`、`monthOfWeek(week: string): string`
  - `useMonthParam.ts`：`useMonthParam(): [string, (month: string) => void]`
  - `api.ts`：`listMonthlyRoster(month: string, includeArchived?: boolean): Promise<MonthRoster>`、`getPersonMonth(personId: number, month: string): Promise<MonthPersonDetail>`
  - `types.ts`：`MonthProjectUse`、`MonthPersonRow`、`MonthRoster`、`MonthWeek`、`MonthPersonDetail`

- [ ] **Step 1: 写失败测试 `frontend/src/month.test.ts`**

```ts
import { describe, expect, it } from "vitest";
import { currentMonth, monthLabel, monthOfWeek, shiftMonth } from "./month";

describe("monthOfWeek", () => {
  it("取该周周一所在月", () => {
    expect(monthOfWeek("2026-11-02")).toBe("2026-11");
  });
  it("跨月周整周算进周一所在月", () => {
    expect(monthOfWeek("2026-11-30")).toBe("2026-11");   // week_end 是 12-06
    expect(monthOfWeek("2026-10-26")).toBe("2026-10");   // week_end 是 11-01
  });
});

describe("shiftMonth", () => {
  it("跨年翻月", () => {
    expect(shiftMonth("2026-11", 1)).toBe("2027-01");
    expect(shiftMonth("2026-11", -1)).toBe("2026-10");
    expect(shiftMonth("2026-12", 1)).toBe("2027-01");
    expect(shiftMonth("2026-01", -1)).toBe("2025-12");
  });
});

describe("monthLabel", () => {
  it("输出中文月份", () => {
    expect(monthLabel("2026-11")).toBe("2026年11月");
  });
});

describe("currentMonth", () => {
  it("返回 YYYY-MM", () => {
    expect(currentMonth(new Date("2026-11-15T02:00:00Z"))).toBe("2026-11");
  });
});
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd frontend && npx vitest run src/month.test.ts`
Expected: FAIL — 无法解析 `./month`。

- [ ] **Step 3: 写 `frontend/src/month.ts`**

仿 `frontend/src/week.ts` 的写法与注释风格（时区 Asia/Shanghai、纯函数、无副作用）：

- `todayInShanghai(now?: Date): string` —— **`month.ts` 自己写，别从 `week.ts` 引**。`week.ts` 里的同名函数是模块私有且返回 `"YYYY-MM-DD"` 字符串，没有导出。实现照抄其写法：`new Intl.DateTimeFormat("en-CA", { timeZone: "Asia/Shanghai", year: "numeric", month: "2-digit", day: "2-digit" }).format(now ?? new Date())`，返回 `"YYYY-MM-DD"` 字符串。
- `monthOfWeek(week: string): string` = `weekKeyOf(week).slice(0, 7)`。`weekKeyOf` 返回的已经是周一 `"YYYY-MM-DD"`，取前 7 位就是该周所属月——**不是** `week.slice(0, 7)`，传入的 `week` 未必是周一。
- `currentMonth(now?: Date): string` = `todayInShanghai(now).slice(0, 7)`。
- `shiftMonth(month: string, delta: number): string` —— 解析 `YYYY-MM` 后用 `Date.UTC(y, m - 1 + delta, 1)` 归一化（自动处理跨年），再取 `YYYY-MM`。**不要**用 `new Date(y, m - 1 + delta, 1)`（本地时区，跨夏令时边界会偏一天）——`Date.UTC` 拿到的月首在 UTC 下恒为 00:00。
- `monthLabel(month: string): string` —— 拼 `YYYY年M月`（**月份不补零**，测试钉的是 `"2026年11月"`；`10` 月要输出 `"2026年10月"` 而不是 `"2026年010月"`）。

- [ ] **Step 4: 跑测试确认通过**

Run: `cd frontend && npx vitest run src/month.test.ts`
Expected: PASS

- [ ] **Step 5: 在 `frontend/src/types.ts` 加五个接口**

字段与 Task 2 / Task 3 的 Pydantic 模型**逐字段对齐**（尤其 `roles: string[]`、`over_days: number | null`、`remaining_days: number | null`、`archived: boolean`）。`MonthWeek` 复用已有的 `Allocation` 类型：`{ week: string; week_end: string; total_days: number; reviewed: boolean; allocations: Allocation[] }`。

照抄下面五块（`MonthProjectUse` 写在前面，后面三个接口都引用它；文件末尾已有 `Allocation` / `Assignment`）：

```ts
// Task 2 的 MonthProjectUse，参与项目标签与「本月分配」面板共用
export interface MonthProjectUse {
  project_id: number;
  project_name: string;
  roles: string[];                // 同人同项目可挂多个角色（Assignment 唯一键含 role）
  days: number;                   // 本月在该项目的人天；只有职责、没有分配时为 0
  has_allocation: boolean;
  has_assignment: boolean;
}

// 注意 weekly_capacity 是本 plan 给 spec §6.4 补的列（理由见 Task 3 Step 4 的注释）
export interface MonthPersonRow {
  person_id: number;
  name: string;
  skills: string;
  roles: string;
  note: string;
  monthly_capacity: number;
  weekly_capacity: number | null;   // 周口径，「资料」标签页用
  used_days: number;
  over_days: number | null;
  remaining_days: number | null;
  reviewed: boolean;
  archived: boolean;
  projects: MonthProjectUse[];
}

export interface MonthRoster {
  month: string;                 // "2026-11"
  weeks: string[];               // 该月各周周一，升序
  people: MonthPersonRow[];
}

export interface MonthWeek {
  week: string;
  week_end: string;
  total_days: number;
  reviewed: boolean;
  allocations: Allocation[];
}

export interface MonthPersonDetail {
  person_id: number;
  month: string;
  monthly_capacity: number;
  used_days: number;
  over_days: number | null;
  remaining_days: number | null;
  reviewed: boolean;
  weeks: MonthWeek[];
  assignments: Assignment[];
  projects: MonthProjectUse[];
}
```

**另外改一处既有接口**：`frontend/src/types.ts:15-25` 的 `Person` 加 `monthly_capacity: number;`——Task 2 让 `PersonOut` 带上了这一列，`api.listPersons(): Promise<Person[]>` 拿到的对象里就含它（`frontend/src/api.ts:84`），类型上不声明就是一处说谎。加一行不破坏任何既有用法（工作台的项目 / 人员下拉都不读它）。

- [ ] **Step 6: 在 `frontend/src/api.ts` 加两个方法**

```ts
listMonthlyRoster: (month: string, includeArchived = false) =>
  request<MonthRoster>(`/persons/roster?month=${month}&include_archived=${includeArchived}`),
getPersonMonth: (personId: number, month: string) =>
  request<MonthPersonDetail>(`/persons/${personId}/month?month=${month}`),
```

`MonthRoster` / `MonthPersonRow` / `MonthProjectUse` / `MonthWeek` / `MonthPersonDetail` 加进 `frontend/src/api.ts:1-12` 的 type import。

- [ ] **Step 7: 写 `frontend/src/useMonthParam.ts`**

仿 `frontend/src/useWeekParam.ts` 的结构：读 `?month=`，缺省 `currentMonth()`；**非法值（不匹配 `/^\d{4}-\d{2}$/`）也回退当前月**，不把脏参数透传给后端；写回用 `setSearchParams`（保留 `?person=` 等其它参数）。

- [ ] **Step 8: 跑类型检查与全量前端测试**

Run: `cd frontend && npx tsc --noEmit && npx vitest run`
Expected: PASS

- [ ] **Step 9: 提交**

```bash
git add frontend/src/month.ts frontend/src/month.test.ts frontend/src/useMonthParam.ts frontend/src/types.ts frontend/src/api.ts
git commit -m "feat(人员页): 前端月度基建 month/useMonthParam 与接口封装"
```

---

### Task 5: 人员表 + `PersonFormDialog`

**Files:**
- Create: `frontend/src/components/PersonFormDialog.tsx`
- Modify: `frontend/src/pages/PersonPage.tsx`（重写为表格；本任务**不含**详情区）
- Modify: `frontend/src/styles.css`
- Modify: `frontend/src/pages/PersonPage.test.tsx`（重写）

**Interfaces:**
- Consumes: `api.listMonthlyRoster`、`api.createPerson`、`api.updatePerson`、`api.archivePerson`、`api.restorePerson`、`useMonthParam`、`month.shiftMonth` / `monthLabel`、`parseDays`（`frontend/src/components/WeekPanel.tsx`，**只读复用，不改动该文件**）
- Produces:
  - `PersonFormDialog({ person: MonthPersonRow | null, onClose: () => void, onSaved: () => void })` — `person` 为 `null` 即新增（调 `api.createPerson`）；非 null 时是编辑（调 `api.updatePerson(person.person_id, …)`，初值取 `person` 的 `name` / `skills` / `roles` / `note` / `monthly_capacity`）。标题「新增人员」/「编辑 · {name}」
    - **弹窗的 `person` 类型是 `MonthPersonRow` 而不是既有的 `Person`**：表格里能拿来打开弹窗的只有 roster 行，而 `Person` 要求 `id` / `source_ref` / `edited_in_app` 这些 roster 行没有的字段（`frontend/src/types.ts:15-25`），把 `row` 塞进 `person: Person` 直接是类型错误。弹窗只读上面那六个字段，`MonthPersonRow` 全都有。
  - `PersonPage` 的 DOM 契约（测试用 `getByRole` / `getByLabelText` 定位，所以这几样必须照着来）：
    - **字段标注一律照代码库既有写法**：`<Field label="X" hint="…">` 里放控件，控件上再挂一个 `aria-label="X"`，**`aria-label` 的文案与 `label` 一字不差**。`getByLabelText("X")` 匹配的正是这个 `aria-label`。**原因**：`Field` 是**包裹式** `<label>`（`frontend/src/components/common.tsx`），给了 `hint` 之后 label 的 textContent 变成 `"X hint"`，精确匹配就落空了，只剩 `aria-label` 那条路能命中。**所以测试里用 `getByLabelText` 定位的字段，`aria-label` 必须严格等于测试里那个字符串**（多一个字都不行）。`frontend/src` 里没有任何一处用 `<label htmlFor>`，别自己引入这种风格。
    - `<table>` 六列表头依次为 `姓名` / `核定人天` / `本月占用` / `参与项目` / `状态` / `操作`，**表头文字是纯文本节点**（别把 `姓名` 拆进 `<span>`，否则 `getByRole("columnheader", { name })` 的 accessible name 会带上 span 内容，依然能匹配，但保持纯文本最稳）。
    - 工具行：按钮 `+ 新增人员`；月份翻页是**两个 `<button>`**，accessible name 分别是 `‹` 和 `›`；文字 `本月` 与 `2026年11月`（月份是 `monthLabel(month)`，形如 `2026年11月`）。
    - `显示已禁用` 复选框：`<Field label="显示已禁用">` 里放 `<input type="checkbox" aria-label="显示已禁用">`——按上面那条规则来，不要写 `htmlFor`/`id`。`getByLabelText("显示已禁用")` 匹配 `aria-label`。
    - 状态列：启用的人显示 `启用`，已禁用的人显示 `已禁用`；操作列：启用的人显示 `编辑` + `禁用`，已禁用的人显示 `编辑` + `启用`。
    - 占用单元格：`已填` 人天之和的数字（如 `18.5`），剩余只在 `remaining_days != null` 时显示（`11.5`），否则显示 `待核对`；超额显示 `超 2 人天`。这三个文案各是独立文本节点，别混在一个字符串里。

- [ ] **Step 1: 重写失败测试 `frontend/src/pages/PersonPage.test.tsx`**

沿用该文件既有的 `vi.mock("../api")` 模式（`vi.fn()` 造 `api`，断言入参），重写为月度口径的人员表测试。**三个硬要求，少一个测试就跑不起来：**

1. `vi.mock("../api")` 工厂里**必须保留 `ApiError: class extends Error {}`**（页面 `catch` 里 `instanceof ApiError` 靠它，少了它 import 就失败）；工厂里的方法要用**箭头转发** `listMonthlyRoster: (...args: unknown[]) => listMonthlyRoster(...args)`——`vi.mock` 会被提升到 `const` 声明之上，直接写 `listMonthlyRoster` 会撞 TDZ；`getPersonMonth`（Task 6 用）也要接上 `vi.fn()` 转发。下面「测试台」那段是照抄级的东西。
2. 所有 `render` 走 `renderPage()`，里面是 `<MemoryRouter initialEntries={["/persons?month=2026-11"]}>`。**必须带 `initialEntries` 钉住月份**——不带的话 MemoryRouter 默认进 `/`，`useMonthParam()` 回落成真实当前月，工具行显示的就不是 `2026年11月`，传给 `listMonthlyRoster` 的 `month` 也和 fixture 的 `"2026-11"` 对不上。
3. `PersonFormDialog` 的字段一律是 `<Field label="字段名">` + 控件上的 `aria-label="字段名"`（文案一字不差），弹窗标题用 `<h2>`，保存按钮文案 `保存`——`getByLabelText("姓名")` / `getByLabelText("核定人天")` / `getByRole("heading", { name: "新增人员" })` / `getByRole("button", { name: "保存" })` 靠的就是这四样（Step 3 照此实现）。**不要给 `id`**：代码库里弹窗（`RescheduleDialog.tsx`、`MilestoneForm.tsx`）都走 `Field` + `aria-label`，没有一处 `htmlFor`；一个弹窗里 `aria-label` 各不相同（`姓名` / `核定人天` / `能力标签` / `角色标签` / `备注`），`getByLabelText` 不会因为多个控件同文案而报错。**`hint` 可以给**（例如核定人天写 `hint="默认 30，0.5 粒度"`），不影响——`getByLabelText` 只认 `aria-label`。

文件头还要补 `waitFor`、`within`（新断言用）和 `MemoryRouter` 的 import——既有文件只 import 了 `render` / `screen` / `fireEvent`。测试台代码见下：

```tsx
it("渲染六列表格与工具行", async () => {
  listMonthlyRoster.mockResolvedValue(rosterActive);
  renderPage();
  expect(await screen.findByText("傅相杰")).toBeTruthy();
  // 表头用 columnheader 找：getByText("姓名") 会同时匹配到「参与项目」里
  // 的标签文本、以及详情区可能出现的同名元素，只有 columnheader 唯一。
  for (const head of ["姓名", "核定人天", "本月占用", "参与项目", "状态", "操作"]) {
    expect(screen.getByRole("columnheader", { name: head })).toBeTruthy();
  }
  expect(screen.getByText("2026年11月")).toBeTruthy();
  expect(screen.getByRole("button", { name: "+ 新增人员" })).toBeTruthy();
  expect(screen.getByRole("button", { name: "‹" })).toBeTruthy();
  expect(screen.getByRole("button", { name: "›" })).toBeTruthy();
  expect(screen.getByLabelText("显示已禁用")).toBeTruthy();
});

it("本月占用显示数字、进度条与剩余", async () => {
  listMonthlyRoster.mockResolvedValue(rosterActive);   // 傅相杰 used 18.5 / capacity 30 / 本月已核对
  renderPage();
  expect(await screen.findByText("18.5")).toBeTruthy();
  expect(screen.getByText("11.5")).toBeTruthy();   // 剩余 = 30 - 18.5
  // 只有一个人所以 progressbar 恰好一个；以后加了第二个人，这里要改成
  // getAllByRole("progressbar").length。
  expect(screen.getByRole("progressbar")).toBeTruthy();
});

it("本月有分配的周没核对完时显示「待核对」而不是剩余", async () => {
  listMonthlyRoster.mockResolvedValue({
    ...rosterActive,
    people: [{ ...rosterActive.people[0], reviewed: false, remaining_days: null }],
  });
  renderPage();
  expect(await screen.findByText("待核对")).toBeTruthy();
  expect(screen.queryByText("11.5")).toBeNull();
});

it("超额显示红色「超 N 人天」，且不给剩余", async () => {
  listMonthlyRoster.mockResolvedValue({
    ...rosterActive,
    people: [{
      ...rosterActive.people[0],
      used_days: 32, over_days: 2, reviewed: false, remaining_days: null,
    }],
  });
  renderPage();
  expect(await screen.findByText("超 2 人天")).toBeTruthy();
  expect(screen.queryByText("11.5")).toBeNull();
});

it("新增人员打开弹窗，核定人天默认 30，提交带 monthly_capacity", async () => {
  listMonthlyRoster.mockResolvedValue(rosterActive);
  renderPage();
  fireEvent.click(screen.getByRole("button", { name: "+ 新增人员" }));
  expect(screen.getByRole("heading", { name: "新增人员" })).toBeTruthy();
  fireEvent.change(screen.getByLabelText("姓名"), { target: { value: "李四" } });
  // 默认值：不改就提交，应该带的是 30（表单初值），而不是空。
  fireEvent.click(screen.getByRole("button", { name: "保存" }));
  expect(createPerson).toHaveBeenCalledWith(
    expect.objectContaining({ name: "李四", monthly_capacity: 30 }),
  );
});

it("核定人天填非法值时内联报错、不发请求", async () => {
  listMonthlyRoster.mockResolvedValue(rosterActive);
  renderPage();
  fireEvent.click(screen.getByRole("button", { name: "+ 新增人员" }));
  fireEvent.change(screen.getByLabelText("姓名"), { target: { value: "李四" } });
  fireEvent.change(screen.getByLabelText("核定人天"), { target: { value: "12.3" } });
  fireEvent.click(screen.getByRole("button", { name: "保存" }));
  // 12.3 不是 0.5 的整数倍 → parseDays 拒绝
  expect(createPerson).not.toHaveBeenCalled();
  expect(screen.getByRole("heading", { name: "新增人员" })).toBeTruthy();
});

it("编辑打开弹窗并带出原值，提交调 updatePerson", async () => {
  listMonthlyRoster.mockResolvedValue(rosterActive);
  renderPage();
  fireEvent.click(screen.getByRole("button", { name: "编辑" }));
  expect(screen.getByRole("heading", { name: "编辑 · 傅相杰" })).toBeTruthy();
  // 带出原值：核定人天的输入框里应该是 30，不能是空。
  expect((screen.getByLabelText("核定人天") as HTMLInputElement).value).toBe("30");
  fireEvent.change(screen.getByLabelText("核定人天"), { target: { value: "20" } });
  fireEvent.click(screen.getByRole("button", { name: "保存" }));
  expect(updatePerson).toHaveBeenCalledWith(
    rosterActive.people[0].person_id,
    expect.objectContaining({ monthly_capacity: 20 }),
  );
});

it("禁用 / 启用分别调 archivePerson / restorePerson", async () => {
  // 用含已禁用人的那份 fixture：启用按钮只对 archived 的人出现。
  listMonthlyRoster.mockResolvedValue(rosterWithArchived);
  renderPage();
  const zhang = screen.getByText("张三2").closest("tr")!;
  fireEvent.click(within(zhang).getByRole("button", { name: "启用" }));
  expect(restorePerson).toHaveBeenCalledWith(rosterWithArchived.people[1].person_id);

  const fu = screen.getByText("傅相杰").closest("tr")!;
  fireEvent.click(within(fu).getByRole("button", { name: "禁用" }));
  expect(archivePerson).toHaveBeenCalledWith(rosterActive.people[0].person_id);
});

it("弹窗里没有「默认周容量」字段", async () => {
  listMonthlyRoster.mockResolvedValue(rosterActive);
  renderPage();
  fireEvent.click(screen.getByRole("button", { name: "+ 新增人员" }));
  expect(screen.queryByText(/默认周容量/)).toBeNull();
});

it("接口失败时显示错误信息", async () => {
  listMonthlyRoster.mockRejectedValue(new Error("服务器 500"));
  renderPage();
  expect(await screen.findByText(/服务器 500/)).toBeTruthy();
});

it("已禁用的人默认不显示，勾开关后出现并灰显", async () => {
  // 按 includeArchived 参数分派，不要一律返回同一份 fixture——
  // 那样「默认不显示」这条断言根本没测到开关。
  listMonthlyRoster.mockImplementation((_m: string, includeArchived = false) =>
    Promise.resolve(includeArchived ? rosterWithArchived : rosterActive),
  );
  renderPage();
  expect(screen.queryByText("张三2")).toBeNull();
  expect(listMonthlyRoster).toHaveBeenCalledWith("2026-11", false);

  fireEvent.click(screen.getByLabelText("显示已禁用"));
  // 开关自己触发重新拉表（useEffect 依赖 includeArchived），**不要**用 rerender——
  // rerender 带相同参数不会重跑 effect，`useMonthParam` 也没有变化，列表不会更新。
  await waitFor(() => expect(screen.getByText("张三2")).toBeTruthy());
  expect(listMonthlyRoster).toHaveBeenCalledWith("2026-11", true);
  const archivedRow = screen.getByText("张三2").closest("tr")!;
  expect(within(archivedRow).getByText("已禁用")).toBeTruthy();
});
```

`rosterActive` / `rosterWithArchived` 两份 fixture + 测试台（含文件头 import 补法）见下，**照抄即可**：

```tsx
// @vitest-environment jsdom                       ← 文件第一行，必须有
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter } from "react-router-dom";
import PersonPage from "./PersonPage";

// ---------- 1. 声明 vi.fn()，写在 vi.mock 之前 ----------
// 顺序有意义：vi.mock 的工厂里用箭头包一层转发，而不是直接引用变量。
const listMonthlyRoster = vi.fn();
const getPersonMonth = vi.fn();
const createPerson = vi.fn();
const updatePerson = vi.fn();
const archivePerson = vi.fn();
const restorePerson = vi.fn();
const listProjects = vi.fn();
const listMilestones = vi.fn();
const listAssignments = vi.fn();
const createAssignment = vi.fn();
const createAllocation = vi.fn();
const updateAllocation = vi.fn();
const deleteAllocation = vi.fn();
const setWeekReview = vi.fn();

// ---------- 2. 既有的 vi.mock 工厂，照抄并加两个新方法 ----------
vi.mock("../api", () => ({
  api: {
    listMonthlyRoster: (...args: unknown[]) => listMonthlyRoster(...args),
    getPersonMonth: (...args: unknown[]) => getPersonMonth(...args),
    createPerson: (...args: unknown[]) => createPerson(...args),
    updatePerson: (...args: unknown[]) => updatePerson(...args),
    archivePerson: (...args: unknown[]) => archivePerson(...args),
    restorePerson: (...args: unknown[]) => restorePerson(...args),
    listProjects: (...args: unknown[]) => listProjects(...args),
    listMilestones: (...args: unknown[]) => listMilestones(...args),
    listAssignments: (...args: unknown[]) => listAssignments(...args),
    createAssignment: (...args: unknown[]) => createAssignment(...args),
    createAllocation: (...args: unknown[]) => createAllocation(...args),
    updateAllocation: (...args: unknown[]) => updateAllocation(...args),
    deleteAllocation: (...args: unknown[]) => deleteAllocation(...args),
    setWeekReview: (...args: unknown[]) => setWeekReview(...args),
  },
  // 页面 catch 里 instanceof ApiError 靠它；**不能省**，省了整个文件 import 就炸。
  ApiError: class extends Error {},
}));

// ---------- 3. render 一律走 renderPage() ----------
// initialEntries 钉住月份：不钉的话 MemoryRouter 默认进 `/`，
// useMonthParam() 回落成真实当前月，工具行就不是「2026年11月」，
// 传给 listMonthlyRoster 的 month 也和 fixture 的 "2026-11" 对不上。
const renderPage = () =>
  render(
    <MemoryRouter initialEntries={["/persons?month=2026-11"]}>
      <PersonPage />
    </MemoryRouter>,
  );

// ---------- 4. fixture ----------
// 2026-11 的五个周一：11-02 / 11-09 / 11-16 / 11-23 / 11-30。
const weeks = ["2026-11-02", "2026-11-09", "2026-11-16", "2026-11-23", "2026-11-30"];

const rosterActive = {
  month: "2026-11",
  weeks,
  people: [
    {
      person_id: 1, name: "傅相杰", skills: "", roles: "", note: "",
      monthly_capacity: 30, weekly_capacity: 5, used_days: 18.5, over_days: null,
      remaining_days: 11.5, reviewed: true, archived: false,
      projects: [
        { project_id: 2, project_name: "贵州矿产预测", roles: ["项目负责人"], days: 10, has_allocation: true, has_assignment: true },
      ],
    },
  ],
};

// 张三2 必须**排在末尾**：后端按 archived, name 排序，已禁用的人在表尾，
// 这个顺序就是实现要复刻的顺序，也是下面 closest("tr") 能取到对的那一行的前提。
const rosterWithArchived = {
  ...rosterActive,
  people: [
    rosterActive.people[0],
    {
      person_id: 2, name: "张三2", skills: "", roles: "", note: "",
      monthly_capacity: 30, weekly_capacity: 5, used_days: 4.5, over_days: null,
      remaining_days: 25.5, reviewed: true, archived: true,
      projects: [
        { project_id: 2, project_name: "贵州矿产预测", roles: ["业务对接"], days: 0, has_allocation: false, has_assignment: true },
      ],
    },
  ],
};
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd frontend && npx vitest run src/pages/PersonPage.test.tsx`
Expected: FAIL — 找不到 `姓名` / `核定人天` 等表头，`listMonthlyRoster` 未定义。

- [ ] **Step 3: 写 `frontend/src/components/PersonFormDialog.tsx`**

仿 `frontend/src/components/RescheduleDialog.tsx:62-70` 的 `.modal-backdrop` / `.modal` / `.modal-head` 结构。字段：姓名（必填）、核定人天（`type="number"`，默认 30，`step="0.5"`）、能力标签、角色标签、备注。提交前用 `parseDays` 校验核定人天（非负、0.5 粒度），不合法就显示内联错误、不发请求。**不放**「默认周容量」。保存按钮文案 `保存`，取消按钮文案 `取消`。

**DOM 契约（Task 5 Step 1 的断言靠它，一条都不能改）：**

- 弹窗标题是 `<h2>新增人员</h2>` / `<h2>编辑 · {name}</h2>`——`getByRole("heading", { name: … })` 只认 `h1`–`h6`，写成 `<div className="modal-title">` 找不到。
- 字段写法照代码库既有约定：`<Field label="字段名">` 里放控件，控件上再挂 `aria-label="字段名"`（**文案一字不差**）。五个字段的 `aria-label` 依次是 `姓名` / `核定人天` / `能力标签` / `角色标签` / `备注`，`getByLabelText(...)` 靠它——`Field` 是**包裹式** `<label>`，给了 `hint` 之后 label 的 textContent 变成 `"字段名 hint"`，精确匹配落空，所以**只有 `aria-label` 能命中**；label 文案就写字段名本身，不要加「请输入」之类前缀。**不要写 `htmlFor`/`id`**：`frontend/src` 里没有任何一处 `htmlFor`（`RescheduleDialog.tsx`、`MilestoneForm.tsx` 全是这套写法），别自己引入新风格。
- 核定人天的 `value` 是数字：新增时初值 `30`，编辑时初值是该人的 `monthly_capacity`（`rosterActive.people[0].monthly_capacity === 30`）。测试里有一行 `expect((screen.getByLabelText("核定人天") as HTMLInputElement).value).toBe("30")`——输入框的 `value` 必须是字符串 `"30"`，不要渲染成 `"30.0"` 或 `""`。
- 保存按钮文案精确是 `保存`（`getByRole("button", { name: "保存" })` 精确匹配 accessible name，多写一个字就找不到）。
- 内联错误用 `role="alert"` 或直接 `getByText` 能查到的文本节点；测试只断言「弹窗还在 + `createPerson` 没被调」，所以文案任意，但要和 `核定人天` 的错误区分开。

- [ ] **Step 4: 重写 `frontend/src/pages/PersonPage.tsx`**

结构（本任务到表格为止，详情区留给 Task 7）：

1. `const [month, setMonth] = useMonthParam();` + 顶部 `const [rows, setRows] = useState<MonthRoster | null>(null)` + `error` state；`useEffect` 里调 `api.listMonthlyRoster(month, showArchived)` 拉表，失败时 `setError`。
2. 工具行：`+ 新增人员` 按钮、`显示已禁用` 复选框、右侧 `‹` / `2026年11月` / `›` / `本月`（`‹ ›` 调 `setMonth(shiftMonth(month, ±1))`）。
3. `<table>` 六列：
   - **姓名**：加粗，点击 `setSelectedId(row.person_id)`，选中行加 `.row-selected`。
   - **核定人天**：右对齐数字。
   - **本月占用**：右对齐数字 + `.cell-progress` 进度条（宽度 `used / capacity`，`over_days != null` 时加红色类）；`over_days != null` 时渲染红字 `超 {over_days} 人天`，否则不渲染。
   - **参与项目**：`row.projects` 每个一条 `.tag`，文案 `{project_name} · {roles.join("、")}`，`roles` 为空时只显示 `project_name`。
   - **状态**：`启用` / `已禁用`（后者加 `.tag-warn`）。
   - **操作**：`编辑`（打开 `PersonFormDialog`）、`禁用` / `启用`（调 `archivePerson` / `restorePerson` 后重新拉表）。
4. 已禁用的人整行加 `.row-archived`（灰显），排在表尾（后端已按 `archived, name` 排序，前端不重排）。
5. 弹窗挂载：`dialog` state 为 `{ mode: "create" } | { mode: "edit"; person: MonthPersonRow } | null`（理由见 Interfaces 那条：类型是 roster 行，不是 `Person`）。

- [ ] **Step 5: 在 `frontend/src/styles.css` 加样式**

复用已有的 `.table` / `.tag` / `.tag-warn` / `.row-archived` / `.row-selected` / `.cell-progress` / `.row-actions`。新增：六列表格的列宽（姓名 1.2fr、核定人天与本月占用各 0.8fr 右对齐、参与项目 2fr、状态 0.8fr、操作 1fr）、`.cell-over`（红字）、`.toolbar`（工具行 flex 布局）。

- [ ] **Step 6: 跑测试与类型检查**

Run: `cd frontend && npx vitest run src/pages/PersonPage.test.tsx && npx tsc --noEmit`
Expected: PASS

- [ ] **Step 7: 提交**

```bash
git add frontend/src/components/PersonFormDialog.tsx frontend/src/pages/PersonPage.tsx frontend/src/styles.css frontend/src/pages/PersonPage.test.tsx
git commit -m "feat(人员页): 月度人员表与新增/修改弹窗"
```

---

### Task 6: `PersonMonthPanel`（本月分配面板）

**Files:**
- Create: `frontend/src/components/PersonMonthPanel.tsx`
- Create: `frontend/src/components/PersonMonthPanel.test.tsx`
- Modify: `frontend/src/styles.css`

**Interfaces:**
- Consumes: `MonthPersonDetail`、`api.getPersonMonth`、`api.listProjects`、`api.listMilestones`、`api.createAllocation`、`api.updateAllocation`、`api.deleteAllocation`、`api.setWeekReview`、`weekEnd`（`frontend/src/week.ts`）
- Produces: `PersonMonthPanel({ personId: number, month: string, archived: boolean, onChanged: () => void })` — `archived` 为 `true` 时「+ 新增分配」按钮 `disabled`

- [ ] **Step 1: 写失败测试 `frontend/src/components/PersonMonthPanel.test.tsx`**

**两个 DOM 约定（Step 3 照着实现，否则测试定位不到）：** 每个周块 `<div data-testid={`week-${week}`}>`（`week` 是周一字符串），每行分配 `<tr data-testid={`alloc-${allocation.id}`}>`。整面板里「改」「删」「+ 新增分配」「核对」每个名字都出现多次，不先圈定范围 `getByRole` 会因为多个匹配直接抛错，所以下面一律用 `within(block)` / `within(row)`。

```tsx
// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import PersonMonthPanel from "./PersonMonthPanel";

const getPersonMonth = vi.fn();
const listProjects = vi.fn();
const listMilestones = vi.fn();
const createAllocation = vi.fn();
const updateAllocation = vi.fn();
const deleteAllocation = vi.fn();
const setWeekReview = vi.fn();

vi.mock("../api", () => ({
  api: {
    getPersonMonth: (...args: unknown[]) => getPersonMonth(...args),
    listProjects: (...args: unknown[]) => listProjects(...args),
    listMilestones: (...args: unknown[]) => listMilestones(...args),
    createAllocation: (...args: unknown[]) => createAllocation(...args),
    updateAllocation: (...args: unknown[]) => updateAllocation(...args),
    deleteAllocation: (...args: unknown[]) => deleteAllocation(...args),
    setWeekReview: (...args: unknown[]) => setWeekReview(...args),
  },
  ApiError: class extends Error {},
}));

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
  // 不设默认返回值的话，`api.listProjects()` 解析成 undefined，
  // 实现里一 `.map` 就炸——这里给空数组兜底。
  listProjects.mockResolvedValue([]);
  listMilestones.mockResolvedValue([]);
});

const renderPanel = () =>
  render(<PersonMonthPanel personId={1} month="2026-11" archived={false} onChanged={() => {}} />);

// Allocation 形状照 `frontend/src/types.ts` 的 `Allocation` 接口填。
const allocA = {
  id: 11, person_id: 1, project_id: 1, week: "2026-11-02", week_end: "2026-11-08",
  days: 10, milestone_id: null, kind: "milestone", note: "",
  person_name: "傅相杰", project_name: "贵州矿产预测", milestone_name: null,
};
const allocB = {
  ...allocA, id: 12, week: "2026-11-09", week_end: "2026-11-15", days: 5.5,
  project_id: 2, project_name: "北京仓储",
};

const detailFixture = {
  person_id: 1,
  month: "2026-11",
  monthly_capacity: 30,
  used_days: 15.5,
  over_days: null,
  remaining_days: null,
  reviewed: false,
  weeks: [
    { week: "2026-11-02", week_end: "2026-11-08", total_days: 10, reviewed: true, allocations: [allocA] },
    { week: "2026-11-09", week_end: "2026-11-15", total_days: 5.5, reviewed: false, allocations: [allocB] },
    { week: "2026-11-16", week_end: "2026-11-22", total_days: 0, reviewed: false, allocations: [] },
  ],
  assignments: [],
  projects: [],
};

it("每月一周一块，显示周区间", async () => {
  getPersonMonth.mockResolvedValue(detailFixture);
  renderPanel();
  expect(await screen.findByText("11-02 ~ 11-08")).toBeTruthy();
  expect(screen.getByText("11-09 ~ 11-15")).toBeTruthy();
  expect(screen.getByText("11-16 ~ 11-22")).toBeTruthy();
});

it("空周照常渲染核对开关", async () => {
  getPersonMonth.mockResolvedValue(detailFixture);
  renderPanel();
  // fixture 里 11-09 与 11-16 都没核对（11-16 是空周，也要有开关），
  // 所以「待核对」恰好出现两次；11-02 已核对，渲染的是「已核对」。
  // 用 getAllByText：getByText 遇到两个匹配会直接抛错，而不是返回数组。
  expect(screen.getAllByText("待核对")).toHaveLength(2);
  expect(screen.getByText("已核对")).toBeTruthy();
});

it("点核对调 setWeekReview", async () => {
  getPersonMonth.mockResolvedValue(detailFixture);
  renderPanel();
  // 三块周里各有 1 个 checkbox，取第一块（11-02）的；开关是 toggle，
  // 已核对的点下去要传 false。
  fireEvent.click(within(await screen.findByTestId("week-2026-11-02")).getByRole("checkbox"));
  expect(setWeekReview).toHaveBeenCalledWith(1, "2026-11-02", false);
});

it("改人天调 updateAllocation", async () => {
  getPersonMonth.mockResolvedValue(detailFixture);
  renderPanel();
  // 点「改」之后整行可能整个换成行内编辑态（DOM 节点换了），所以两步分开取。
  fireEvent.click(within(screen.getByTestId("alloc-11")).getByRole("button", { name: /改/ }));
  const editing = screen.getByTestId("alloc-11");
  fireEvent.change(within(editing).getByLabelText("改人天"), { target: { value: "12" } });
  fireEvent.click(within(editing).getByRole("button", { name: "保存" }));
  await waitFor(() => expect(updateAllocation).toHaveBeenCalledWith(allocA.id, { days: 12 }));
});

it("删分配调 deleteAllocation", async () => {
  getPersonMonth.mockResolvedValue(detailFixture);
  renderPanel();
  fireEvent.click(within(screen.getByTestId("alloc-11")).getByRole("button", { name: /删/ }));
  await waitFor(() => expect(deleteAllocation).toHaveBeenCalledWith(allocA.id));
});

it("新增分配落到该周周一", async () => {
  getPersonMonth.mockResolvedValue(detailFixture);
  // `api.listProjects()` 返回值不设的话会是 undefined，实现里 `.map` 就炸。
  // `<option value={String(p.id)}>` 决定了这里要传字符串 "1"（见 Step 3）。
  listProjects.mockResolvedValue([{ id: 1, name: "贵州矿产预测" }]);
  renderPanel();
  const block = await screen.findByTestId("week-2026-11-02");
  fireEvent.click(within(block).getByRole("button", { name: /新增分配/ }));
  fireEvent.change(within(block).getByLabelText("新增分配项目"), { target: { value: "1" } });
  fireEvent.change(within(block).getByLabelText("新增分配人天"), { target: { value: "3" } });
  fireEvent.click(within(block).getByRole("button", { name: "保存" }));
  await waitFor(() =>
    expect(createAllocation).toHaveBeenCalledWith({
      person_id: 1, project_id: 1, week: "2026-11-02", days: 3, milestone_id: null,
    }),
  );
});

it("已禁用的人不给新增分配，但已有分配照改照删", async () => {
  getPersonMonth.mockResolvedValue(detailFixture);
  render(<PersonMonthPanel personId={1} month="2026-11" archived={true} onChanged={() => {}} />);
  const block = await screen.findByTestId("week-2026-11-02");
  // 每块都有「+ 新增分配」，禁用时它们全是 disabled，取第一块的断言即可。
  expect(within(block).getByRole("button", { name: /新增分配/ }).hasAttribute("disabled")).toBe(true);
  fireEvent.click(within(block).getByRole("button", { name: /删/ }));
  await waitFor(() => expect(deleteAllocation).toHaveBeenCalledWith(allocA.id));
});

it("面板里不出现周口径的「容量 / 剩余」", async () => {
  getPersonMonth.mockResolvedValue(detailFixture);
  renderPanel();
  expect(screen.queryByText(/容量/)).toBeNull();
  expect(screen.queryByText(/剩余/)).toBeNull();
});
```

`allocA` / `allocB` 就是块里那两个 `Allocation` 形状的对象（字段照 `frontend/src/types.ts` 的 `Allocation` 接口填）。`detailFixture` 只有三周（11-02 / 11-09 / 11-16），后端的 `MonthWeekOut` 按月返回 4–5 周，少写两周只是为了测试短——Step 3 的实现不要依赖「恰好三周」。

- [ ] **Step 2: 跑测试确认失败**

Run: `cd frontend && npx vitest run src/components/PersonMonthPanel.test.tsx`
Expected: FAIL — 无法解析 `./PersonMonthPanel`。

- [ ] **Step 3: 写 `frontend/src/components/PersonMonthPanel.tsx`**

签名 `PersonMonthPanel({ personId, month, archived, onChanged }: { personId: number; month: string; archived: boolean; onChanged: () => void })`。

1. `useEffect` 调 `api.getPersonMonth(personId, month)`，失败时显示 `ErrorBanner`（`errorMessage`）。
2. 顶部一行周区间：`{week.slice(5)} ~ {weekEnd(week).slice(5)}`（`weekEnd` 从 `../week` 导入，返回周日），即 `11-02 ~ 11-08`。测试按纯文本节点匹配这个字符串，别在里面插 `<span>`。
3. 每行：项目名（+ 节点名，若有）、人天数输入框 + `保存`、`删`、核对开关（`checked={reviewed}`）。
4. 核对开关调 `api.setWeekReview(personId, week, checked)`，成功后调 `onChanged()`。
5. 改人天 / 删分配调 `updateAllocation(id, { days })` / `deleteAllocation(id)`，成功后 `onChanged()`。
6. 每块底部一行 `+ 新增分配`：弹出内联表单（选项目 → 可选节点 → 人天 → 保存），调 `api.createAllocation({ person_id, project_id, week, days, milestone_id })`，`week` 用该块的周周一，`milestone_id` 为 `null` 表示不绑节点。
7. `archived === true` 时「+ 新增分配」按钮 `disabled`，并在旁边显示 `已禁用，不可新增分配`；**已有分配的「改」「删」照常可用**。
8. **整块不出现任何「容量 / 剩余 / 指定周容量」字样与控件**。

**DOM 契约（Step 1 的断言靠它，一条都不能改）：**
- 周块 `<div data-testid={`week-${week}`}>`（`week` 是周一字符串，如 `week-2026-11-02`）；每行分配 `<tr data-testid={`alloc-${allocation.id}`}>`（如 `alloc-11`）。整面板里每个按钮名都重复（每行都有改/删、每块都有新增分配），`getByRole` 遇到多个匹配直接抛错，所以测试一律用 `within(...)` 先圈范围——`data-testid` 就是给这个用的。
- 项目下拉与内联表单的字段照代码库既有写法：`<Field label="字段名">` 里放控件，控件上再挂 `aria-label`，`getByLabelText` 匹配的是 `aria-label`。**`aria-label` 必须严格等于测试里那个字符串**，逐字对照：
  - 新增分配表单的三个控件：`<Field label="项目">` + `<select aria-label="新增分配项目">`；`<Field label="节点" hint="留空表示整体项目管理">` + `<select aria-label="新增分配节点">`；`<Field label="人天" hint="0.5 粒度">` + `<input aria-label="新增分配人天">`。（这套 `aria-label` 与 `WeekPanel.tsx:304-336` 一致，只是 `Field label` 只写短名。）
  - 行内改人天：`<Field label="人天">` + `<input aria-label="改人天">`。
  - `Field` 是**包裹式** `<label>`：给了 `hint` 之后 label 的 textContent 变成 `"字段名 hint"`，精确匹配落空，所以**命中只能靠 `aria-label`**；label 文案写短名（`项目` / `节点` / `人天`）即可。**不要写 `htmlFor`/`id`**——`frontend/src` 里没有任何一处 `htmlFor`。
  - 内联表单**只在被点的那块周里渲染**（`newWeek` 是一个单值 state，点哪块就设成哪块的周一，别给每块都存一个开关）。否则「新增分配项目」「新增分配人天」「保存」会出现 N 份，`within(block)` 里也会撞上多份，测试直接抛「多个元素」。
- 项目 `<option>` 的 `value` **必须是 `String(p.id)`**（测试里 `fireEvent.change(…, { value: "1" })`，断言 `project_id: 1`）。写成项目名或数字裸值都会对不上。
- 「改」按钮点下去之后该行可以整体换成行内编辑态（换掉 DOM 节点是可以的），但**外层的 `<tr>` 要保持同一个 `data-testid`**——测试点完「改」会重新 `getByTestId("alloc-11")` 再取输入框。
- 行内编辑与新增表单的保存按钮文案精确是 `保存`。
- 核对开关的 `<input type="checkbox">` 是这一周里唯一的 checkbox，`getByRole("checkbox")` 在块内取即可。

- [ ] **Step 4: 在 `frontend/src/styles.css` 加样式**

新增 `.month-week-block`（周块：上边框分隔）、`.week-head`（周区间行）、`.inline-form`（内联新增表单）。核对开关复用已有的复选框样式。

- [ ] **Step 5: 跑测试与类型检查**

Run: `cd frontend && npx vitest run src/components/PersonMonthPanel.test.tsx && npx tsc --noEmit`
Expected: PASS

- [ ] **Step 6: 提交**

```bash
git add frontend/src/components/PersonMonthPanel.tsx frontend/src/components/PersonMonthPanel.test.tsx frontend/src/styles.css
git commit -m "feat(人员页): 本月分配面板（按周块、核对、行内改删）"
```

---

### Task 7: 详情区三标签页 + 资料 / 职责面板

**Files:**
- Modify: `frontend/src/pages/PersonPage.tsx`（加详情区）
- Modify: `frontend/src/styles.css`
- Modify: `frontend/src/pages/PersonPage.test.tsx`

**Interfaces:**
- Consumes: `PersonMonthPanel`（它内部自己调 `api.getPersonMonth`，Task 7 的代码不直接调）、`api.updatePerson`、`api.listAssignments`、`api.createAssignment`、`api.deleteAssignment`、`api.listProjects`、`parseDays`、`monthLabel`、以及 roster 行的六个资料字段（`name` / `monthly_capacity` / `weekly_capacity` / `skills` / `roles` / `note`）
- Produces: 详情区 DOM 契约——
  - 汇总条是**一个元素、一个模板字面量文本节点**，文本为 `傅相杰 · 核定 30 人天 · 本月已用 18.5 · 剩余 11.5 · 2026年11月`；`remaining_days === null` 时第 4 段换成 `待核对` 而不是数字。`getByText` 精确匹配整串（不能拆成多个文本节点，否则 exact 匹配失败）。
  - 三个标签页按钮**一律带 `role="tab"` 与 `aria-selected`**（选中 `"true"`，未选中 `"false"`，始终存在该属性，不靠 CSS 类推断）。显式 `role="tab"` 会让 `getByRole("button")` 再也找不到它们，所以测试只能按 `getByRole("tab", { name })` 找，选中态用 `getAttribute("aria-selected")` 断言——**`aria-selected` 不是 `getByRole` 的合法选项键**（在 `role="button"` 上更是直接抛错），写进 options 会被静默忽略，形成假阳性断言。
  - 顺序 `资料` / `项目职责` / `本月分配`，默认选中 `本月分配`。
  - 资料标签页的六项资料（姓名 / 核定人天 / 默认周容量 / 能力标签 / 角色标签 / 备注）取自**上方表格里选中的那一行**（roster 行的 `name` / `monthly_capacity` / `weekly_capacity` / `skills` / `roles` / `note`），不另调 `api.listPersons()`。控件一律 `<Field label="…">` + 控件上显式 `aria-label`（本仓库 `frontend/src` 全篇没有 `htmlFor`/`id` 关联，`Field` 的 wrapping `<label>` 会把 `hint` 也计入标签文本，所以只能走 `aria-label`），钉死的 `aria-label` 是：`姓名`、`核定人天`、`默认周容量`、`能力标签`、`角色标签`、`备注`。
  - 项目职责标签页的控件 `aria-label` 是 `职责项目`、`职责角色`；`添加职责` 按钮**直接发请求**（`api.createAssignment`），标签页里**没有 `保存` 按钮**。
  - 本月分配标签页里，第一周块的标题文本是 `11-02 ~ 11-08`（用来在 5 个周块里唯一定位，避免 `+ 新增分配` 出现 5 次导致 `getByRole` 抛多匹配错）。

- [ ] **Step 1: 追加失败测试到 `frontend/src/pages/PersonPage.test.tsx`**

先在文件里（Task 5 的 harness 之后）加这个 fixture——Task 5 只建了 `rosterActive` / `rosterWithArchived`，没有详情 fixture：

```tsx
// PersonMonthPanel 自己调 api.getPersonMonth 取数（见 Task 6 Step 3），所以这是它的 mock 返回值。
// 注意：汇总条不读它——汇总条的数字全部来自上方选中的 roster 行（Task 3 已把这些字段放进
// MonthPersonRow），这样同一份月度数据不会在同一页被请求两次。
const detailFixture = {
  person_id: 1,
  month: "2026-11",
  monthly_capacity: 30,
  used_days: 18.5,
  over_days: null,
  remaining_days: 11.5,
  reviewed: true,
  weeks: [
    { week: "2026-11-02", week_end: "2026-11-08", total_days: 10, reviewed: true, allocations: [] },
    { week: "2026-11-09", week_end: "2026-11-15", total_days: 8.5, reviewed: true, allocations: [] },
    { week: "2026-11-16", week_end: "2026-11-22", total_days: 0, reviewed: true, allocations: [] },
    { week: "2026-11-23", week_end: "2026-11-29", total_days: 0, reviewed: false, allocations: [] },
    { week: "2026-11-30", week_end: "2026-12-06", total_days: 0, reviewed: false, allocations: [] },
  ],
  assignments: [],
  projects: [],
};
```

```tsx
it("选中某人后默认停在「本月分配」标签页", async () => {
  listMonthlyRoster.mockResolvedValue(rosterActive);
  getPersonMonth.mockResolvedValue(detailFixture);
  renderPage();
  fireEvent.click(await screen.findByText("傅相杰"));

  // 选中态只能直接断言 aria-selected 属性：aria-selected 不是 getByRole 的合法选项键
  // （写进 options 会被静默忽略，形成假阳性断言），而 role="tab" 又让 getByRole("button")
  // 再也找不到这三个按钮。
  expect(screen.getByRole("tab", { name: "本月分配" }).getAttribute("aria-selected")).toBe("true");
  expect(screen.getByRole("tab", { name: "资料" }).getAttribute("aria-selected")).toBe("false");
  expect(screen.getByRole("tab", { name: "项目职责" }).getAttribute("aria-selected")).toBe("false");
  // 默认标签页已经把面板渲染出来了：第一周块的周区间是纯文本节点（别在里面插 <span>）
  expect(screen.getByText("11-02 ~ 11-08")).toBeTruthy();
});

it("三个标签页可切换", async () => {
  listMonthlyRoster.mockResolvedValue(rosterActive);
  getPersonMonth.mockResolvedValue(detailFixture);
  listAssignments.mockResolvedValue([]);
  renderPage();
  fireEvent.click(await screen.findByText("傅相杰"));

  fireEvent.click(screen.getByRole("tab", { name: "资料" }));
  expect(screen.getByLabelText("默认周容量")).toBeTruthy();

  fireEvent.click(screen.getByRole("tab", { name: "项目职责" }));
  expect(screen.getByRole("button", { name: "添加职责" })).toBeTruthy();
});

it("未全部核对时汇总条显示「待核对」", async () => {
  // 汇总条读的是 roster 行，所以「待核对」要打在 roster 上，打在 detailFixture 上没用
  listMonthlyRoster.mockResolvedValue({
    ...rosterActive,
    people: [{ ...rosterActive.people[0], remaining_days: null, reviewed: false }],
  });
  // 默认标签页是「本月分配」，面板一挂载就调 getPersonMonth——不 mock 的话它拿到
  // undefined，渲染时 .weeks 直接抛错，那条「待核对」断言就永远等不到
  getPersonMonth.mockResolvedValue(detailFixture);
  renderPage();
  fireEvent.click(await screen.findByText("傅相杰"));
  expect(await screen.findByText(/待核对/)).toBeTruthy();
});

it("资料标签页保存调 updatePerson 且带 weekly_capacity", async () => {
  listMonthlyRoster.mockResolvedValue(rosterActive);
  getPersonMonth.mockResolvedValue(detailFixture);
  renderPage();
  fireEvent.click(await screen.findByText("傅相杰"));
  fireEvent.click(screen.getByRole("tab", { name: "资料" }));

  // 「默认周容量」允许留空（= 未知），提交时转成数字或 null
  fireEvent.change(screen.getByLabelText("默认周容量"), { target: { value: "6" } });
  fireEvent.click(screen.getByRole("button", { name: "保存资料" }));

  expect(updatePerson).toHaveBeenCalledWith(
    rosterActive.people[0].person_id,
    expect.objectContaining({ weekly_capacity: 6 }),
  );
});

it("项目职责标签页添加职责调 createAssignment", async () => {
  listMonthlyRoster.mockResolvedValue(rosterActive);
  getPersonMonth.mockResolvedValue(detailFixture);
  listProjects.mockResolvedValue([{ id: 7, name: "北京仓储", state: "active" }]);
  listAssignments.mockResolvedValue([]);
  renderPage();
  fireEvent.click(await screen.findByText("傅相杰"));
  fireEvent.click(screen.getByRole("tab", { name: "项目职责" }));

  // <option value={String(p.id)}>：写项目名或数字裸值都对不上
  fireEvent.change(screen.getByLabelText("职责项目"), { target: { value: "7" } });
  // 角色必须显式选：不选时组件会落到 ASSIGNMENT_ROLES[0]（项目负责人），断言就对不上了
  fireEvent.change(screen.getByLabelText("职责角色"), { target: { value: "节点执行" } });
  // 这个面板没有「保存」按钮——点「添加职责」就直接发请求
  fireEvent.click(screen.getByRole("button", { name: "添加职责" }));

  expect(createAssignment).toHaveBeenCalledWith({
    person_id: rosterActive.people[0].person_id,
    project_id: 7,
    role: "节点执行",
  });
});

it("本月分配标签页加载失败时显示错误信息", async () => {
  listMonthlyRoster.mockResolvedValue(rosterActive);
  getPersonMonth.mockRejectedValue(new Error("服务器 500"));
  renderPage();
  fireEvent.click(await screen.findByText("傅相杰"));
  // errorMessage(new Error("服务器 500")) 返回 "Error: 服务器 500"，正则匹配即可
  expect(await screen.findByText(/服务器 500/)).toBeTruthy();
});
```

角色下拉沿用 `PersonPage.tsx` 既有的 `ASSIGNMENT_ROLES = ["项目负责人", "业务对接", "节点执行", "统筹管理"]`。

**每个测试都要先 mock 两件事**：一是 `listMonthlyRoster.mockResolvedValue(rosterActive)`——`PersonPage` 挂载就拉 roster，不 mock 的话 `people` 是 `undefined`，表格直接崩，崩在要断言的东西之前；二是 `getPersonMonth.mockResolvedValue(detailFixture)`——默认标签页是「本月分配」，`PersonMonthPanel` 一挂载就调它，拿不到 mock 就拿到 `undefined`，渲染 `.weeks` 抛 TypeError，同样把测试打掉（只有「加载失败」那条测试是故意让它 reject 的）。切到「项目职责」标签页还会触发 `listAssignments`，不 mock 就是 `undefined.map`。

- [ ] **Step 2: 跑测试确认失败**

Run: `cd frontend && npx vitest run src/pages/PersonPage.test.tsx`
Expected: FAIL — 找不到 `本月分配` 标签页按钮。

- [ ] **Step 3: 在 `PersonPage.tsx` 加详情区**

`selectedId` state（Task 5 已建）非空时，在表格下方渲染：

1. **汇总条**：`{name} · 核定 {capacity} 人天 · 本月已用 {used} · {remaining === null ? "待核对" : `剩余 ${remaining}`} · {monthLabel(month)}`。
   - **数据来源是上方选中的 roster 行**（`row.name` / `row.monthly_capacity` / `row.used_days` / `row.remaining_days`），**不要调 `api.getPersonMonth`**：那份数据 `PersonMonthPanel` 自己会拉（Task 6 Step 3 第 1 条），汇总条再拉一次就是同一页两次请求同一份月度数据。Task 3 之所以把 `monthly_capacity` / `used_days` / `over_days` / `remaining_days` 都放进 `MonthPersonRow`，就是为了这里不必再发一次请求。
   - **必须是「一个元素 + 一个模板字面量文本节点」**：`<div className="detail-summary">{`${row.name} · 核定 ${row.monthly_capacity} 人天 · 本月已用 ${row.used_days} · ${row.remaining_days === null ? "待核对" : `剩余 ${row.remaining_days}`} · ${monthLabel(month)}`}</div>`。别拆成多个 `<span>`——`getByText` 只匹配元素的直接文本子节点，拆开后精确匹配落空。
2. **标签页**：`资料` / `项目职责` / `本月分配` 三个 `<button role="tab" aria-selected={String(active === key)}>`（选中 `"true"`，未选中 `"false"`，**始终渲染该属性**，别只给选中的那个加）。显式 `role="tab"` 会盖掉 `<button>` 的隐式 role，`getByRole("button")` 就再也找不到它们——这是有意的，测试按 `getByRole("tab", { name })` 找。默认 `"本月分配"`。切换只改 `activeTab` state，不重新拉数据。
3. **本月分配**：`<PersonMonthPanel personId={selectedId} month={month} archived={row.archived} onChanged={reload} />`。
4. **资料**：六项资料——姓名、核定人天（`type="number"` `step="0.5"`）、`默认周容量`（`type="number"` `step="0.5"`，允许留空 = 未知，标题旁加小字提示「周口径用，工作台/项目页按周看」）、能力标签、角色标签、备注 + `保存资料` 按钮。
   - **六项全部取自选中的 roster 行**（`row.name` / `row.monthly_capacity` / `row.weekly_capacity` / `row.skills` / `row.roles` / `row.note`），**不要调 `api.listPersons()`**——roster 行本来就带这六个字段，再拉一次是多余的往返。
   - 控件一律 `<Field label="字段名">` 里放控件、控件上再挂 `aria-label`（本仓库 `frontend/src` 全篇没有 `htmlFor`/`id` 关联，`Field` 的包裹式 `<label>` 会把 `hint` 一起计入标签文本，所以命中只能靠 `aria-label`）。钉死的 `aria-label` 逐字是：`姓名`、`核定人天`、`默认周容量`、`能力标签`、`角色标签`、`备注`。
   - 保存调 `api.updatePerson(row.person_id, { …六项 })`，其中 `weekly_capacity` 用 `Number(value)` 转成数字、输入框留空时提交 `null`（= 未知，这是它与必填的核定人天的关键差别）；`monthly_capacity` 同样转数字。成功后调 `reload()`（roster 里那两列要跟着变）。
5. **项目职责**：职责列表（`{project_name} · {role}`）+ `添加职责`（选项目 + 选角色）+ 每条的 `删除`，职责列表用 `api.listAssignments({ person_id: selectedId })`，新增调 `api.createAssignment`、删除调 `api.deleteAssignment`。
   - 项目下拉用 `api.listProjects()`，`<option value={String(p.id)}>`；角色下拉用 `PersonPage.tsx` 既有的 `ASSIGNMENT_ROLES`，`<option value={role}>`。
   - 控件 `aria-label` 逐字是 `职责项目`、`职责角色`。
   - **`添加职责` 按钮点下去直接发请求，这个面板里没有 `保存` 按钮**（与「资料」标签页的 `保存资料` 不同）。
   - 新增 / 删除成功后调 `reload()`——参与项目列要跟着变。

选中的人切换或月份切换时，重新拉 roster（详情区随之重渲染）；`onChanged` 回调里重新拉 roster。

- [ ] **Step 4: 在 `frontend/src/styles.css` 加样式**

新增 `.detail-summary`（汇总条）、`.tabs` / `.tab`（标签页，选中态用下边框强调）、`.tab-panel`。

- [ ] **Step 5: 跑测试与类型检查**

Run: `cd frontend && npx vitest run src/pages/PersonPage.test.tsx && npx tsc --noEmit`
Expected: PASS

- [ ] **Step 6: 提交**

```bash
git add frontend/src/pages/PersonPage.tsx frontend/src/styles.css frontend/src/pages/PersonPage.test.tsx
git commit -m "feat(人员页): 详情区三标签页（资料 / 项目职责 / 本月分配）"
```

---

### Task 8: 工作台链接 + 既有测试修正

**Files:**
- Modify: `frontend/src/pages/WorkbenchPage.tsx:257`（一行）
- Modify: `frontend/src/pages/WeekSharing.test.tsx`
- Modify: `frontend/src/pages/PersonPage.test.tsx`（如有遗留）

**Interfaces:**
- Consumes: `monthOfWeek`（`frontend/src/month.ts`，Task 4 产出）
- Produces: 工作台 → 人员页的链接从 `?week=<周一>&person=<id>` 变成 `?month=<该周周一所在月>&person=<id>`

- [ ] **Step 1: 改 `frontend/src/pages/WorkbenchPage.tsx:257`**

把

```tsx
<a className="link" href={`/persons?week=${week}&person=${person.person_id}`}>
```

改成

```tsx
<a className="link" href={`/persons?month=${monthOfWeek(week)}&person=${person.person_id}`}>
```

并在 `frontend/src/pages/WorkbenchPage.tsx` 顶部加 `import { monthOfWeek } from "../month";`。**工作台自身的周口径、组件、计算一律不动。**

- [ ] **Step 2: 更新 `frontend/src/pages/WeekSharing.test.tsx` 的三处断言**

- 第 213 / 219 行附近：`/persons?week=2026-10-26&person=8` 改成 `/persons?month=2026-10&person=8`；连带 `getPersonWeek` 的调用断言改成 `getPersonMonth` 用 `(8, "2026-10")`。
- 第 221 行附近：点「下一周」后 `getPersonWeek` 的 `(8, "2026-11-02")` 改成 `getPersonMonth` 的 `(8, "2026-11")`。
- 第 255 行附近：`personLink.getAttribute("href")` 期望值从 `/persons?week=2026-11-02&person=7` 改成 `/persons?month=2026-11&person=7`。

改完跑一遍确认：如果该测试文件还断言了人员页内部的周控件（`上一周` / `本周` / `下一周`），那些断言要删掉——人员页已没有周切换控件，保留会失败。

- [ ] **Step 3: 跑后端全量测试**

Run: `pytest backend/tests/ -q`
Expected: PASS

- [ ] **Step 4: 跑前端全量测试与类型检查**

Run: `cd frontend && npx vitest run && npx tsc --noEmit`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add frontend/src/pages/WorkbenchPage.tsx frontend/src/pages/WeekSharing.test.tsx frontend/src/pages/PersonPage.test.tsx
git commit -m "feat(人员页): 工作台跳转改月参数并同步既有测试"
```

---

## 完成后

8 个任务全部完成、全量测试通过后，用 `superpowers:requesting-code-review` 做一次整分支审查，再走 `superpowers:finishing-a-development-branch`。
