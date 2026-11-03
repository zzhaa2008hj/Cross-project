# 人员页月度口径改版 · 设计

**日期**：2026-11-03
**状态**：已批准（2026-11-03）
**改动范围**：人员页（`frontend/src/pages/PersonPage.tsx` + 新增组件）+ 支撑月度口径的后端接口与模型列。工作台、项目页的周口径一律不动。

---

## 1. 为什么要改

现在的人员页是四张卡片竖着堆：

1. **人员列表**——不是表格，是一串按钮，每行只有姓名 + 能力标签 +「默认容量 5 人天」；
2. **资料**卡——姓名 / 能力标签 / 默认周容量 + 保存资料；
3. **项目职责**卡——职责列表 + 添加职责；
4. **周投入分配**卡——一次只看一周。

三个具体痛点：

- **看不了横向对比**。想知道「这个月谁快用满了」，得一个人一个人点进去，而且每次只看得到一周。
- **列表列不是管理口径**。「默认容量 5 人天」是周口径；要看的是月口径的**核定人天（默认 30）**、**本月占用**、**参与项目**。
- **管不了人**。列表里只能看，不能新增、修改、启用禁用——这些后端接口（`POST /persons`、`PATCH /persons/{id}`、`/archive`、`/restore`）都现成，UI 根本没露出来。

改成**一张能横向对比的表 + 表格下方的详情区**，并把新增 / 修改 / 启用禁用放到表上。

## 2. 目标、非目标、反目标

### 目标

- 人员表六列：**姓名 / 核定人天 / 本月占用 / 参与项目 / 状态 / 操作**。
- **核定人天**：每人每月的核定值，默认 30，必填数字，不留「未知」。
- **本月占用**：按自然月汇总，只统计 Allocation。
- **参与项目**：本月有分配的项目 ∪ 该人挂职责的项目，去重，带角色。
- **新增 / 修改 / 启用 / 禁用**都在人员页完成。
- 禁用的人**灰显保留**在表里，可开关隐藏；不能再被选为分配对象；历史占用保留。
- 详情区三个标签页：**本月分配（默认）/ 资料 / 项目职责**。

### 非目标

- 不改工作台、项目页的周口径、容量、覆盖、核对逻辑。
- 不改分配的数据模型：仍然按周录（`allocations.week` 不动）。
- 不删 `week_capacities` 表与周容量覆盖接口——项目页还在用。
- 不做导入导出，不动备份/恢复链路。

### 反目标（做到也算失败）

- 人员页不得出现「容量未知」这类状态。
- 不得把月占用和周占用混在一张表里显示。
- 不得因为禁用就把人从列表里抹掉——历史要查得到。
- 不得让「核定人天」与「周容量」共用一个字段（两者量纲不同：30 人天/月 vs 5 人天/周）。

## 3. 约束

- 占用只认 `Allocation`；`Assignment` 只表达角色，永不计入占用。
- 人天粒度 0.5，非负，非法值接口返回 422（沿用 `backend/app/schemas.py:validate_days`）。
- 周键 = 周一（Asia/Shanghai），月 = 自然月。
- 「未知 ≠ 0」的规矩在周口径里继续有效；人员页的核定人天不引入未知。
- 后端 FastAPI + SQLAlchemy 2.x（同步 Session）+ SQLite（WAL）；前端 React + TypeScript + Vite。
- **没有 Alembic**：加列走 `backend/app/db.py` 的 `_ADDED_COLUMNS` 轻量补列机制。
- 本地无 CI；「没跑 CI」≠「CI 通过」。

## 4. 口径（用户拍定的）

| 口径 | 定义 | 谁定的 |
|---|---|---|
| 核定人天 | 每人每月一个数，默认 30，只能填数字（不留未知） | 用户 |
| 分配粒度 | **按周录、按月算**：`allocations` 仍按周存，人员页按月汇总 | 用户 |
| 本月定义 | 自然月 | 用户 |
| 跨月周归属 | 一周的周一落在哪个月，**整周**算进那个月 | 我的调用 |
| 核对粒度 | 仍按周核对，本月视图把每周的核对状态并排显示 | 用户 |
| 月度核对判定 | **本月有分配的周都核对过**才算本月已核对（空周不参与判定） | 用户 |
| 参与项目 | 本月有占用的项目 ∪ 该人挂职责的项目，去重 | 用户 |
| 禁用显示 | 灰显保留 + 「已禁用」标签 + 「显示已禁用」开关 | 用户 |
| 周容量覆盖 | 表、接口、项目页的 WeekPanel 覆盖 UI **全部保留**；**人员页不再出现** | 用户（只从人员页掉） |
| 详情区内容 | 资料 + 项目职责 + 本月分配（按周）三块 | 用户 |
| 页面排法 | **A：表格在上、详情在下**（整页一张表，点某人下方展开详情） | 用户 |
| 详情区排法 | **三个标签页，默认停在「本月分配」** | 用户 |

### 现有数据现状（决定了迁移写法）

`data/sqlite/crossproject.db`：2 个人（傅相杰、张三2），`weekly_capacity` 都是 5.0；3 条分配全在 `2026-11-02` 这一周；该周**未核对**；2 条职责（傅相杰→项目2 项目负责人，张三2→项目2 业务对接）。

按新口径，傅相杰 2026-11 的**本月占用 = 4.5 人天**（3 + 1 + 0.5），核定 30，剩余 25.5。

## 5. 界面

### 5.1 人员表（上半屏）

工具行：`+ 新增人员` 按钮、`显示已禁用` 复选框、右侧 `统计月份：2026年11月 ‹ › 本月`。

| 列 | 内容 | 说明 |
|---|---|---|
| 姓名 | 加粗，点击选中该人，详情区切到 TA | |
| 核定人天 | 数字，右对齐 | 必填，默认 30 |
| 本月占用 | 数字，右对齐 + 进度条 | 超核定则红字「超 N 人天」，进度条转红 |
| 参与项目 | 标签列表，每个标签 `项目名 · 角色` | 本月分配的项目与职责项目合并去重；职责角色为空时只显示项目名 |
| 状态 | `启用` / `已禁用` | 已禁用整行灰显 |
| 操作 | `编辑` · `禁用`（已禁用则 `启用`） | |

- 默认按姓名排序（后端 `list_persons` 已按 name 排，新 roster 接口保持）。
- 默认**不显示**已禁用的人；勾选「显示已禁用」后追加在表尾并灰显。
- 「本月占用」列的数字是**已填**人天之和（不含判断）；「剩余」只在**本月有分配的周都核对过**后才给精确值，否则显示「待核对」——沿用周口径「未核对不给精确剩余」的规矩。空周不参与判定，所以零分配的新人直接显示剩余 30；之后往某个空周加了新分配，该周没核对就自动退回「待核对」。

### 5.2 详情区（下半屏，选中某人时出现）

顶部一行汇总条：`傅相杰 · 核定 30 人天 · 本月已用 18.5 · 剩余 11.5 · 2026年11月`。

三个标签页，**默认停在「本月分配」**：

1. **本月分配（按周）**：本月每一周一行块，块内是这一周的分配明细表（周区间 / 项目 / 人天 / 核对 / 操作），底部一行「+ 新增分配」。
   - 周次顺序：本月各周按时间先后（11-02 → 11-09 → 11-16 → 11-23 → 11-30）。
   - 每行「核对」是一个开关：已核对显示 `已核对`，点一下取消；未核对显示 `待核对`，点一下标记。复用既有 `PUT /persons/{id}/weeks/{week}/review`。
   - 「操作」列：改人天（行内编辑）、删除。
   - 「+ 新增分配」：选项目（+ 可选节点）+ 人天，落到该周。人员页**没有「选人」下拉**——人是从上方表格里选定的，所以这里不存在人员过滤的问题（全应用唯一的「选人」下拉是节点执行人，走 `api.listPersons()`，后端默认已过滤已禁用的人）。
   - **选中的是已禁用的人时**，「+ 新增分配」不给（置灰或隐藏），但**已有的分配仍可改可删**——历史要查得到、也要纠错（我的调用，§9.12）。
   - 这块**不出现**任何「容量 / 剩余 / 指定周容量」——周口径的容量 UI 不再进人员页。
   - 空周上的「核对」开关照常渲染、照常可点（与现有 WeekPanel 行为一致），但**空周不参与**「剩余」的判定。
2. **资料**：姓名、核定人天（默认 30）、**默认周容量（周口径用）**、能力标签、角色标签、备注 + 保存。保存走 `PATCH /persons/{id}`。
   - 「默认周容量」是**人员页唯一保留的周口径字段**，标题旁注明「周口径用，工作台/项目页按周看」，避免与月度的核定人天混淆；它允许留空（= 未知），这是它与核定人天的关键差别。
3. **项目职责**：职责列表（项目 · 角色）+ 添加职责（选项目 + 选角色）+ 删除。职责不计入占用。

### 5.3 新增 / 修改人员（弹窗）

弹窗字段：**姓名（必填）**、**核定人天（默认 30，必填数字）**、能力标签、角色标签、备注。

- 新增与修改共用一个表单；修改时标题为「编辑 · 傅相杰」。
- 弹窗里**不放**「默认周容量」——它是周口径字段，只在「资料」标签页编辑（见 §5.2）。
- 禁用 / 启用**不进弹窗**，放表的操作列，一步到位（我的调用）。
- 前端提交前校验人天：非负、0.5 粒度（复用 `frontend/src/components/WeekPanel.tsx` 的 `parseDays`）。

## 6. 数据与接口

### 6.1 模型

`backend/app/models.py` 的 `Person` 加一列：

```python
monthly_capacity: Mapped[float] = mapped_column(
    Float, nullable=False, default=30.0, server_default=text("30")
)
```

`weekly_capacity` **保持原样**（`float | None`，周口径，工作台/项目页继续用）。

### 6.2 迁移

`backend/app/db.py` 的 `_ADDED_COLUMNS` 加：

```python
"persons": [("skills", "TEXT DEFAULT ''"), ("monthly_capacity", "REAL NOT NULL DEFAULT 30")],
```

SQLite 的 `ALTER TABLE ... ADD COLUMN ... NOT NULL DEFAULT 30` 会把存量行直接补成 30，无需单独回填脚本。老库首次启动即完成升级。

### 6.3 Schema 变更（`backend/app/schemas.py`）

- `PersonCreate.monthly_capacity: float = 30.0`，走 `validate_days` 校验（非负、0.5 粒度）。
- `PersonUpdate.monthly_capacity: float | None = None`，**显式传 null 报 422**（字段缺失则不改动）。实现上用 `mode="before"` 的校验器：`None` 直接抛错——Pydantic v2 默认不对缺失字段跑校验器，字段缺失与显式 null 因此可区分。
- `PersonOut.monthly_capacity: float`。

### 6.4 新接口（新增，服务层 `backend/app/services/monthly.py`）

```
GET /persons/roster?month=2026-11&include_archived=false
GET /persons/{person_id}/month?month=2026-11
```

**`GET /persons/roster`** → `MonthRosterOut`

```python
class MonthProjectUse(BaseModel):
    project_id: int
    project_name: str
    roles: list[str] = []     # 该人在这项目上的职责角色（可能有多个）
    days: float = 0.0         # 本月在该项目的人天（只有职责则为 0）
    has_allocation: bool = False
    has_assignment: bool = False

class MonthPersonRow(BaseModel):
    person_id: int
    name: str
    skills: str = ""
    roles: str = ""
    note: str = ""
    monthly_capacity: float
    used_days: float          # 本月已填人天
    over_days: float | None   # used > capacity 时为超出量，否则 None
    remaining_days: float | None  # 本月有分配的周都核对过时为 capacity - used，否则 None
    reviewed: bool            # 本月有分配的周是否都核对过（空周不参与）
    archived: bool
    projects: list[MonthProjectUse] = []

class MonthRosterOut(BaseModel):
    month: str                # "2026-11"
    weeks: list[str]          # 该月各周周一，升序，如 ["2026-11-02", ..., "2026-11-30"]
    people: list[MonthPersonRow] = []
```

**`MonthProjectUse.roles` 为什么是列表**：`Assignment` 的唯一键是 `(person_id, project_id, role)`（`backend/app/models.py:152`），同一人在同一项目上可以挂多个不同角色，所以角色用列表而不是单个字符串。前端把同一个项目的角色并成一个标签：`项目名 · 角色1、角色2`；只有分配、没有职责的项目只显示项目名。

**`GET /persons/{person_id}/month`** → `MonthPersonDetail`

```python
class MonthWeekOut(BaseModel):
    week: str
    week_end: str
    total_days: float
    reviewed: bool
    allocations: list[AllocationOut] = []

class MonthPersonDetail(BaseModel):
    person_id: int
    month: str
    monthly_capacity: float
    used_days: float
    over_days: float | None
    remaining_days: float | None
    reviewed: bool
    weeks: list[MonthWeekOut] = []
    assignments: list[AssignmentOut] = []
    projects: list[MonthProjectUse] = []
```

**月份参数**：`month` 形如 `YYYY-MM`，非法格式返回 400。

**月 → 周的算法**：某月的周 = 该自然月内所有「周一落在该月」的日期（每月 4 或 5 个）。2026-11 → `["2026-11-02", "2026-11-09", "2026-11-16", "2026-11-23", "2026-11-30"]`；`2026-10-26` 那一周（10/26–11/01）整周算 10 月。

### 6.5 复用的既有接口（不改动）

| 用途 | 接口 |
|---|---|
| 新增 / 修改人员 | `POST /persons`、`PATCH /persons/{id}` |
| 启用 / 禁用 | `POST /persons/{id}/archive`、`POST /persons/{id}/restore` |
| 增删改分配 | `POST /allocations`、`PATCH /allocations/{id}`、`DELETE /allocations/{id}` |
| 按周核对 | `PUT /persons/{id}/weeks/{week}/review` |
| 职责 | `GET/POST /assignments`、`PATCH/DELETE /assignments/{id}` |
| 项目 / 节点 | `GET /projects`、`GET /milestones?project_id=` |

## 7. 前端改动

| 文件 | 动作 |
|---|---|
| `frontend/src/pages/PersonPage.tsx` | 重写：人员表 + 详情区（标签页） |
| `frontend/src/components/PersonFormDialog.tsx` | 新增：新增/修改人员弹窗 |
| `frontend/src/components/PersonMonthPanel.tsx` | 新增：本月分配（按周）面板 |
| `frontend/src/month.ts` | 新增：`currentMonth()`（Asia/Shanghai）、`shiftMonth(month, delta)`、`monthLabel(month)` |
| `frontend/src/useMonthParam.ts` | 新增：仿照 `useWeekParam.ts` 的 `?month=` 参数读写 |
| `frontend/src/api.ts` | 加 `listMonthlyRoster(month, includeArchived)`、`getPersonMonth(personId, month)` |
| `frontend/src/types.ts` | 加 `MonthRoster` / `MonthPersonRow` / `MonthPersonDetail` / `MonthWeek` |
| `frontend/src/pages/PersonPage.test.tsx` | 重写（见 §8） |
| `frontend/src/pages/WorkbenchPage.tsx` | **只改跳转链接一行**：`/persons?week=…&person=…` → `/persons?month=<该周周一所在月>&person=…`（见 §9.11） |
| `frontend/src/pages/WeekSharing.test.tsx` | 跟着改：断言里的 `/persons?week=…` 与 `getPersonWeek` 调用要改成月参数 |
| `frontend/src/styles.css` | 加进度条、六列表格、标签页、「超 N 人天」红字样式；弹窗复用 `RescheduleDialog.tsx` 已有的 `.modal-backdrop` / `.modal` / `.modal-head` |
| `frontend/src/components/WeekPanel.tsx` | **不动**（项目页继续用） |

**月份参数**：人员页用 `?month=2026-11`（替代现在的 `?week=`），仿照 `frontend/src/useWeekParam.ts` 写 `useMonthParam`。工作台跳人员页时带的 `?person=<id>`（预选人员）**保留**。

## 8. 测试

### 后端 `backend/tests/test_monthly.py`（新增）

- 新建人员 `monthly_capacity` 默认为 30。
- 老库补列后存量人员为 30（`_add_missing_columns` 路径）。
- 本月占用只算本月的周；相邻月的分配不计入。
- 跨月周（周一 11-30）整周算进 11 月；`2026-10-26` 那周算 10 月。
- 超额：`used > capacity` → `over_days` 为超出量。
- 剩余：本月**有分配的周**都核对过 → `capacity - used`；否则 `None`。
- 空周不参与核对判定：零分配的人 `reviewed=True`、`remaining_days == capacity`。
- 往一个已核对的空周加了新分配 → 该周未核对 → `reviewed=False`、`remaining_days=None`。
- 参与项目 = 本月分配项目 ∪ 职责项目，去重，带角色。
- 已禁用的人：默认不出现在 roster；`include_archived=true` 时出现且 `archived=True`。
- `month` 参数非法 → 400。
- `PATCH /persons/{id}` 显式传 `monthly_capacity: null` → 422；传 0.3 → 422；不传该字段 → 不改动。

### 前端 `frontend/src/pages/PersonPage.test.tsx`（重写）

- 表格渲染六列与数据；本月占用显示数字与进度条；超额显示红色「超 N 人天」。
- 已禁用的人灰显显示，「显示已禁用」开关能切换。
- 「+ 新增人员」打开弹窗 → 填姓名与核定人天 → 提交调用 `createPerson`（含 `monthly_capacity`）。
- 操作列「编辑」打开弹窗且带出原值；提交调用 `updatePerson`。
- 「禁用」调用 `archivePerson`，「启用」调用 `restorePerson`。
- 详情区三个标签页可切换；默认停在「本月分配」。
- 「资料」标签页里有「默认周容量」字段；新增/修改弹窗里没有这个字段。
- 本月分配里改人天 / 删分配 / 切换核对分别调用对应接口。
- 接口失败时显示错误信息。

## 9. 我的调用（builder 直接照做，除非用户改口）

1. 跨月周按「周一所在月」整周归属；月末那周整周算进当月。
2. 「剩余」只有本月**有分配的周**都核对过才给精确值，否则显示「待核对」；「超额」始终按已填人天判断。详情区顶部的汇总条与表格口径一致，未满足条件时同样显示「待核对」。
3. 核定人天是**每人一个数，对所有月份生效**，不做逐月覆盖表。
4. 迁移把存量人员的核定人天补成 30；**不改动存量的 `weekly_capacity`（仍是 5.0）**——改存量会动到工作台/项目页的既有显示，超出「只改人员页」。
5. 人员表默认按姓名排序，已禁用的人排在启用的人之后。
6. 超额用红色「超 N 人天」标注，进度条同步转红。
7. 新增/修改走弹窗，字段为姓名 / 核定人天 / 能力标签 / 角色标签 / 备注；禁用启用放操作列。
8. 详情区默认标签页是「本月分配」。
9. 参与项目的角色用列表 `roles`（`Assignment` 唯一键含 role，同一人同项目可挂多个角色）；前端把同一项目的角色并成一个标签 `项目名 · 角色1、角色2`，只有分配没有职责的只显示项目名。
10. **不给已禁用的人加后端拦截**（`POST /allocations` 不动）：那会连带改项目页行为，超出「只改人员页」。人员页本来也没有「选人」下拉；节点执行人下拉早就走 `api.listPersons()`，默认不含已禁用的人。
11. 工作台跳人员页的链接从 `?week=` 改成 `?month=<该周周一所在月>&person=<id>`（`WorkbenchPage.tsx:257` 一行）：人员页已只留月度口径，周参数在那边没有意义。**工作台自身的周口径不动。**
12. 选中的人已禁用时，详情区**不给「+ 新增分配」**（置灰或隐藏）——禁用的语义就是不再派活；但**已有分配照改照删**，历史要查得到也要能纠错。前端一个 `disabled` 就行，不新增后端拦截（见第 10 条）。

## 10. 已拍板（2026-11-03）

审查代理提的 5 题全部落定：2 题由你拍板，3 题由「改动范围 = 只改人员页」和既有代码事实直接定下。

| 问题 | 结论 | 谁定的 |
|---|---|---|
| 周容量的编辑入口归谁 | **资料标签页保留「默认周容量（周口径用）」字段**；弹窗里不放；存量 5.0 不动 | 你 |
| 月度核对判定含不含空周 | **只含有分配的周**；零分配的人直接显示剩余 30 | 你 |
| 禁用的人要不要后端拦截新增分配 | 不拦，`POST /allocations` 不动（项目页行为不变）；人员页本来没有「选人」下拉，节点执行人下拉早已默认过滤 | 范围推出（§9.10） |
| 工作台 → 人员页的 `?week=` 参数 | 人员页只留月度口径 ⇒ 链接改成 `?month=<该周周一所在月>`，工作台口径不动 | 范围推出（§9.11） |
| 参与项目的多角色 | `roles: list[str]`，前端并成一个标签 | 我的调用（§9.9） |
