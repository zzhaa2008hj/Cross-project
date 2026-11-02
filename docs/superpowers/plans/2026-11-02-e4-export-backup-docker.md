# E4 导出预览、一致性备份恢复与 Docker 收尾 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 交付与当前数据库状态严格一致的导出预览（JSON/Markdown/Obsidian 摘要）、每日一致性备份、离线可回滚恢复，以及固定镜像、可重建、可核验的 Docker 使用路径。

**Architecture:** 用 `sqlite3.Connection.backup()` 在线捕获一致性快照，所有导出物（完整表 JSON、Markdown、Obsidian 摘要）都从同一份快照生成，保证三者互相一致。每日备份复用同一服务，先写 staging 目录再整体 rename 发布，失败不留半份。恢复是离线显式命令：独占应用锁 → 校验候选库（integrity_check + foreign_key_check + 必需表）→ 原子替换 → 保留回滚库；JSON 恢复走同一入口，先在临时库重建再替换。

**Tech Stack:** 既有 FastAPI + SQLAlchemy 2.x + SQLite（WAL）+ React + TypeScript + Vite + Docker Compose。

**Spec:** 首版计划 `/HUI/issues/HUI-203#document-plan`；任务计划文档 `plan`（HUI-211，revision `48da394e-3326-4a2a-917a-4f17a09097df`）。原始方案只读参考：`/home/hui/MyData/AI/my-vault/90_计划/跨项目管理软件/首版开发方案.md`（备份与导出摘要两节）。

## Global Constraints

- 唯一目标仓库 `zzhaa2008hj/Cross-project`，基线 `develop`，PR 合入真实远端 develop 后才可收口。
- 不写 vault、不覆盖现有笔记/脚本、不停 `panel_gen.py`；正式写回属已知限制，本次不实现。
- 数据目录与备份目录都在本项目登记的 Git 外存储（`~/.local/share/paperclip-project-data/52a8eeac-d442-420e-af14-663ffd7af0ee`），备份不得落在 vault 内。
- 容器/网络/卷前缀 `pc-52a8eeac`，标签 `project/issue/owner/lifecycle/version`。
- 预览端口 18330，使用前先查占用。
- 未知容量不得转 0（`weekly_capacity`/`days` 的 NULL 必须原样往返）。
- 本地接入无 CI；零检查即"未配置 CI"，不得声称 CI 通过。
- 证据写在 `evidenceRoot/89f32463-500a-4445-a05a-b7d7d16194c8/`。

## Review Focus

- 并发写入期间取快照，导出的表之间不得出现半笔事务（孤儿外键行）。
- `weekly_capacity = NULL` 与 `0` 必须在 JSON 往返后保持可区分，未知容量不得被写成 0。
- 历史（`history_entries`）与归档标记（`archived`）不得在导出/恢复中丢失。
- 恢复过程中任一步失败，原库必须完好无损，且必须留下可回滚副本。
- 备份中途失败不得留下半份已发布备份。
- 任何来自 HTTP 参数或命令行的路径都不得逃逸出备份/预览根目录。

---

### Task 1: 一致性快照与导出数据层

**Files:**
- Create: `backend/app/services/snapshot.py`
- Test: `backend/tests/test_snapshot.py`

**Interfaces:**
- Produces:
  - `snapshot_db(db_path: Path, dest: Path) -> Path` —— 用 `sqlite3` backup API 把 `db_path` 一致性复制到 `dest`（dest 必须不存在），返回 dest。
  - `read_tables(db_path: Path) -> dict[str, list[dict]]` —— 读出全部表的所有行，按 `PRAGMA table_info` 顺序取列，值做 JSON 安全转换（bytes→base64，其余原样）。
  - `table_columns(db_path: Path) -> dict[str, list[dict]]` —— 表名 → 列信息（含 pk 标记）。

- [ ] **Step 1: 写失败测试**

```python
def test_snapshot_db_copies_all_tables(tmp_path):
    src = make_db(tmp_path, {"projects": [{"id": 1, "name": "A"}]})
    dest = tmp_path / "snap.db"
    assert snapshot_db(src, dest) == dest
    assert read_tables(dest)["projects"][0]["name"] == "A"


def test_snapshot_under_concurrent_write_is_consistent(tmp_path):
    # 写线程持续插入 (project, milestone) 配对；快照里不得出现孤儿 milestone
    ...


def test_read_tables_keeps_null_and_zero_distinct(tmp_path):
    ...
```

- [ ] **Step 2: 运行测试确认失败**

Run: `pytest backend/tests/test_snapshot.py -v`
Expected: FAIL — `ImportError: cannot import name 'snapshot_db' from 'app.services.snapshot'`

- [ ] **Step 3: 实现 `backend/app/services/snapshot.py`**

`snapshot_db` 用 `sqlite3.connect(db_path)` 作源、`sqlite3.connect(dest)` 作目标，调用 `src.backup(dst)`；目标文件必须先删除。`read_tables` 遍历 `sqlite_master` 中 `type='table'` 且非 `sqlite_%` 的表，按 `PRAGMA table_info` 顺序 select，值转换函数把 `bytes` 变 base64 字符串，其余保留。

- [ ] **Step 4: 运行测试确认通过**

Run: `pytest backend/tests/test_snapshot.py -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add backend/app/services/snapshot.py backend/tests/test_snapshot.py
git commit -m "feat(E4): 一致性快照与导出数据读取"
```

---

### Task 2: 导出产物（JSON / Markdown / Obsidian 摘要）与差异

**Files:**
- Create: `backend/app/services/export.py`
- Test: `backend/tests/test_export.py`

**Interfaces:**
- Consumes: `read_tables(db_path) -> dict[str, list[dict]]`（Task 1）
- Produces:
  - `build_export(db_path: Path) -> dict` —— 返回 `{"schema_version", "generated_at", "snapshot_id", "tables": {...}, "counts": {...}}`；`snapshot_id` = `"snap-" + UTC 时间戳 + "-" + 内容 sha256 前 8 位`。
  - `render_markdown(export: dict) -> str` —— 全表可读 Markdown。
  - `render_obsidian_summary(export: dict) -> str` —— 紧凑摘要（项目/节点状态分布/人员容量/最近历史）。
  - `diff_exports(prev: dict | None, cur: dict) -> dict` —— 按主键比较，返回 `{"is_first", "tables": {表名: {"added","removed","changed","ids"}}}`。

- [ ] **Step 1: 写失败测试**

```python
def test_build_export_counts_and_snapshot_id(tmp_path): ...
def test_render_markdown_contains_every_table(tmp_path): ...
def test_render_obsidian_summary_lists_projects(tmp_path): ...
def test_diff_exports_reports_added_changed_removed(tmp_path): ...
def test_null_capacity_stays_null_in_export(tmp_path): ...
```

- [ ] **Step 2: 运行测试确认失败**
Run: `pytest backend/tests/test_export.py -v`
Expected: FAIL — ImportError on `app.services.export`

- [ ] **Step 3: 实现 `backend/app/services/export.py`**

- [ ] **Step 4: 运行测试确认通过**
Run: `pytest backend/tests/test_export.py -v`
Expected: PASS

- [ ] **Step 5: 提交**
```bash
git add backend/app/services/export.py backend/tests/test_export.py
git commit -m "feat(E4): JSON/Markdown/Obsidian 摘要导出与预览差异"
```

---

### Task 3: 备份发布（原子、不留半份、路径穿越拒绝）

**Files:**
- Create: `backend/app/services/backup.py`
- Test: `backend/tests/test_backup.py`

**Interfaces:**
- Consumes: `snapshot_db`, `build_export`, `render_markdown`, `render_obsidian_summary`
- Produces:
  - `backup_root() -> Path` —— 优先 `CP_BACKUP_DIR`，否则 `data_dir()/backups`。
  - `run_backup(db_path: Path, backup_root: Path, stamp: str | None = None) -> dict` —— 返回 `{"stamp","db_path","json_path","markdown_path","obsidian_path","counts"}`；发布目录为 `backup_root/<stamp>/`。
  - `safe_join(base: Path, *parts: str) -> Path` —— 解析后必须仍在 `base` 之内，否则抛 `ValueError`。

- [ ] **Step 1: 写失败测试**

```python
def test_run_backup_publishes_db_json_markdown(tmp_path): ...
def test_run_backup_leaves_no_partial_publish_on_failure(tmp_path, monkeypatch): ...
def test_run_backup_does_not_overwrite_existing_stamp(tmp_path): ...
def test_safe_join_rejects_traversal(tmp_path): ...
def test_backup_root_is_outside_vault(monkeypatch): ...
```

- [ ] **Step 2: 运行测试确认失败**
Run: `pytest backend/tests/test_backup.py -v`
Expected: FAIL — ImportError on `app.services.backup`

- [ ] **Step 3: 实现 `backend/app/services/backup.py`**

流程：建 `backup_root/.staging-<stamp>/` → 写 `export.json`、`export.md`、`obsidian.md` → `snapshot_db` 写 `crossproject.db` → 全部成功后 `os.replace(staging, backup_root/<stamp>)`（同文件系统原子 rename）；任一步异常删除 staging 并抛出。已存在的 stamp 直接报错。

- [ ] **Step 4: 运行测试确认通过**
Run: `pytest backend/tests/test_backup.py -v`
Expected: PASS

- [ ] **Step 5: 提交**
```bash
git add backend/app/services/backup.py backend/tests/test_backup.py
git commit -m "feat(E4): 每日一致性备份与原子发布"
```

---

### Task 4: 离线恢复（校验、原子替换、回滚保留）与 CLI

**Files:**
- Create: `backend/app/services/restore.py`
- Create: `backend/app/backup_cli.py`
- Test: `backend/tests/test_restore.py`

**Interfaces:**
- Produces:
  - `validate_sqlite_candidate(path: Path) -> list[str]` —— 返回问题列表；空列表表示通过（`PRAGMA integrity_check`、`PRAGMA foreign_key_check`、必需表齐全）。
  - `restore_sqlite(candidate: Path, db_path: Path, stamp: str) -> dict` —— 返回 `{"restored_from","rollback_path"}`；先复制原库到 `<db>.rollback-<stamp>`，再把候选复制到 `<db>.new` 并 `os.replace`。
  - `restore_json(json_path: Path, db_path: Path, stamp: str) -> dict` —— 从 JSON 导出重建数据库：按外键安全顺序插入到临时库，校验通过后原子替换。
  - `acquire_app_lock(db_path: Path)` / `assert_app_stopped(db_path: Path)` —— flock 独占锁文件 `<db>.lock`；应用运行期持锁，恢复时拿不到锁即报错。

- [ ] **Step 1: 写失败测试**

```python
def test_restore_sqlite_replaces_db_and_keeps_rollback(tmp_path): ...
def test_restore_sqlite_with_invalid_candidate_leaves_original(tmp_path): ...
def test_restore_json_rebuilds_equivalent_db(tmp_path): ...
def test_restore_json_with_bad_payload_leaves_original(tmp_path): ...
def test_assert_app_stopped_fails_while_lock_held(tmp_path): ...
```

- [ ] **Step 2: 运行测试确认失败**
Run: `pytest backend/tests/test_restore.py -v`
Expected: FAIL — ImportError on `app.services.restore`

- [ ] **Step 3: 实现 `backend/app/services/restore.py` 与 `backend/app/backup_cli.py`**

CLI：`python -m app.backup_cli backup [--db PATH] [--backup-dir PATH] [--stamp S]`；`python -m app.backup_cli restore --source PATH [--db PATH] [--type sqlite|json] [--stamp S]`；恢复前必须确认应用已停（锁检查），失败退出码非 0 并打印原因。

- [ ] **Step 4: 运行测试确认通过**
Run: `pytest backend/tests/test_restore.py -v`
Expected: PASS

- [ ] **Step 5: 提交**
```bash
git add backend/app/services/restore.py backend/app/backup_cli.py backend/tests/test_restore.py
git commit -m "feat(E4): 离线恢复（校验/原子替换/回滚）与备份 CLI"
```

---

### Task 5: 导出预览 API 与每日备份调度

**Files:**
- Create: `backend/app/api_export.py`
- Modify: `backend/app/main.py`
- Test: `backend/tests/test_api_export.py`

**Interfaces:**
- Consumes: `build_export`, `render_markdown`, `render_obsidian_summary`, `diff_exports`, `run_backup`, `backup_root`
- Produces（HTTP）：
  - `POST /api/export/preview` → `{"preview_id","generated_at","snapshot_id","counts","diff","markdown","obsidian"}`
  - `GET /api/export/previews/{preview_id}/json` → `export.json` 下载
  - `GET /api/export/previews/{preview_id}/markdown` → `export.md` 下载
  - `GET /api/export/previews/{preview_id}/obsidian` → `obsidian.md` 下载
  - `GET /api/export/previews` → 预览列表（最近 20 条）
  - `POST /api/backup/run` → 手动触发一次备份，返回备份摘要

  预览存 `data_dir()/exports/<preview_id>/`，索引 `data_dir()/exports/index.json`。

- [ ] **Step 1: 写失败测试**

```python
def test_preview_returns_snapshot_and_diff(client): ...
def test_preview_diff_reflects_change_between_previews(client): ...
def test_preview_download_json_markdown_obsidian(client): ...
def test_unknown_preview_id_returns_404(client): ...
def test_preview_id_with_traversal_returns_404(client): ...
def test_backup_run_endpoint_publishes_backup(client, tmp_path): ...
```

- [ ] **Step 2: 运行测试确认失败**
Run: `pytest backend/tests/test_api_export.py -v`
Expected: FAIL — 404/ImportError

- [ ] **Step 3: 实现 `backend/app/api_export.py`，在 `backend/app/main.py` 注册 router**

`main.py` 同时启动每日备份调度：启动线程，每 24 小时调用一次 `run_backup`（失败只记录日志，不影响服务），并暴露 `CP_BACKUP_ENABLED` 开关。

- [ ] **Step 4: 运行测试确认通过**
Run: `pytest backend/tests/test_api_export.py -v`
Expected: PASS

- [ ] **Step 5: 提交**
```bash
git add backend/app/api_export.py backend/app/main.py backend/tests/test_api_export.py
git commit -m "feat(E4): 导出预览 API 与每日备份调度"
```

---

### Task 6: 前端导出预览页

**Files:**
- Create: `frontend/src/pages/ExportPage.tsx`
- Create: `frontend/src/pages/ExportPage.test.tsx`
- Modify: `frontend/src/App.tsx`

**Interfaces:**
- Consumes: Task 5 的 HTTP 接口
- Produces: 路由 `/export`，导航项「导出预览」

- [ ] **Step 1: 写失败测试**

```tsx
it("点击生成后展示快照版本与行数", ...)
it("展示与上次预览的差异", ...)
it("提供 JSON/Markdown/Obsidian 摘要三个下载入口", ...)
it("提示预览不写回 vault", ...)
it("接口失败时显示错误", ...)
```

- [ ] **Step 2: 运行测试确认失败**
Run: `cd frontend && npx vitest run src/pages/ExportPage.test.tsx`
Expected: FAIL — 无法解析 `./pages/ExportPage`

- [ ] **Step 3: 实现 `frontend/src/pages/ExportPage.tsx` 并在 `frontend/src/App.tsx` 注册路由与导航**

页面含：「生成导出预览」按钮、快照版本/生成时间/各表行数、与上次预览差异（新增/修改/删除）、三个下载链接、显著提示「本预览只读取软件数据库，不会写回 vault 笔记或脚本」。

- [ ] **Step 4: 运行测试确认通过**
Run: `cd frontend && npx vitest run && npx tsc --noEmit`
Expected: PASS

- [ ] **Step 5: 提交**
```bash
git add frontend/src/pages/ExportPage.tsx frontend/src/pages/ExportPage.test.tsx frontend/src/App.tsx
git commit -m "feat(E4): 导出预览页面"
```

---

### Task 7: Docker 固定镜像、备份挂载与使用说明

**Files:**
- Modify: `docker-compose.yml`
- Modify: `backend/Dockerfile`
- Modify: `README.md`

**Interfaces:**
- Produces: 固定版本镜像标签 `pc-52a8eeac-backend:hui211-e4` / `pc-52a8eeac-frontend:hui211-e4`；备份卷 `/backups` 挂到本项目数据目录下的 `backups/`；README 含使用说明、备份与恢复演练步骤、已知限制。

- [ ] **Step 1: 写失败测试**

用 `backend/tests/test_ops_config.py` 断言 `docker-compose.yml` 含 `CP_BACKUP_DIR`、备份 bind mount、`pc-52a8eeac` 前缀，且备份挂载源路径不在 vault 内。

- [ ] **Step 2: 运行测试确认失败**
Run: `pytest backend/tests/test_ops_config.py -v`
Expected: FAIL — compose 缺少备份挂载

- [ ] **Step 3: 改 `docker-compose.yml` / `backend/Dockerfile` / `README.md`**

- [ ] **Step 4: 运行测试确认通过**
Run: `pytest backend/tests/test_ops_config.py -v`
Expected: PASS

- [ ] **Step 5: 提交**
```bash
git add docker-compose.yml backend/Dockerfile README.md backend/tests/test_ops_config.py
git commit -m "chore(E4): 固定镜像、备份挂载与使用说明"
```

---

### Task 8: 端到端验证与交付

**Files:**
- Create: `evidence/89f32463-500a-4445-a05a-b7d7d16194c8/` 下的验证记录（项目 evidenceRoot 内）

- [ ] **Step 1: 全量后端测试**
Run: `pytest -q`（backend 目录）
Expected: 全部 PASS

- [ ] **Step 2: 前端全量测试 + 类型 + 构建**
Run: `cd frontend && npx vitest run && npx tsc --noEmit && npm run build`
Expected: 全部 PASS

- [ ] **Step 3: 干净环境启动 + 备份 + 恢复演练**
用独立数据目录启动后端，`backup_cli backup` → `backup_cli restore --type json` → `backup_cli restore --type sqlite`，记录命令与输出。

- [ ] **Step 4: 容器重建持久化实测**
用固定标签构建镜像，重建容器后确认数据库文件仍在 `/data` 且备份目录仍在 `/backups`，记录镜像 ID。

- [ ] **Step 5: PR + 交接**
推送分支并开 PR（base `develop`，保留 head 的 merge commit），记录 PR/head/merge 与 exact-head checks；在 HUI-211 保存 `qa-handoff`（version=2），跑 `qa_handoff_check.py --scope source --mode prepared`；建 work products；跑 `project_closeout.py`。
