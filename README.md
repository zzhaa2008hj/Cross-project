# Cross-project

跨项目管理软件 · E2（人员资料、周容量与跨项目 Allocation 闭环）

E1 已交付：**项目列表 → 项目详情 → 节点创建/编辑 → 依赖改期预览 → 只读源导入报告**。

E2 目标：在本机浏览器完成 **人员页 → 项目页同一份 Allocation → 显式填周投入 → 定位跨项目冲突**：

- 人员页维护人员资料/能力、默认周容量、指定周容量、项目职责、分配与核对。
- 项目页复用同一份 Allocation（同一分配 ID 只计一次占用），并同时展示该人的完整跨项目冲突集。
- 容量与投入都支持"未知"；职责与执行人不产生占用，不预建 5 天、不按角色折算。

- 后端：FastAPI + SQLAlchemy 2 + SQLite（WAL，FK ON）
- 前端：React 18 + TypeScript + Vite + react-router-dom
- 部署：Docker Compose（backend + nginx 前端），端口仅绑定 `127.0.0.1:18330`

## 目录结构

```
backend/     FastAPI 服务、领域服务（缓冲/改期/导入/历史/周容量与分配）、pytest 用例
frontend/    React 单页应用（项目列表、项目详情、人员页、导入报告）
docker-compose.yml  本机预览编排
```

## Docker 预览（推荐）

自用场景：数据全部落在项目目录 `./data`（SQLite、每日备份、导出预览），删容器不影响数据；端口只绑回环，不对外暴露。

```bash
mkdir -p data            # 首次运行创建数据目录（.gitignore 已忽略）
docker compose up -d --build
curl http://127.0.0.1:18330/api/health
# 浏览器打开 http://127.0.0.1:18330/
```

- 停止：`docker compose down`（**不会**删除 `./data`）。
- **改代码后要带 `--build`**：不带会继续用旧镜像，代码改动不生效。
- 备份与导出产物也在项目目录：`data/backups`、`data/exports`。
- vault 以只读方式挂到容器 `/vault`（导入来源），正式写回不在当前版本范围内。

容器与镜像命名统一使用 `pc-52a8eeac-` 前缀：

| 资源 | 名称 |
| --- | --- |
| compose project | `pc-52a8eeac-develop` |
| backend 容器 | `pc-52a8eeac-develop-backend-1` |
| frontend 容器 | `pc-52a8eeac-develop-frontend-1` |
| 镜像 | `pc-52a8eeac-backend:local`、`pc-52a8eeac-frontend:local` |

无 named volume：SQLite 落在项目目录 `data/`，容器删除不会带走数据。

## 本地开发（不用 Docker）

```bash
# 后端
python3 -m venv .venv && . .venv/bin/activate
pip install -r backend/requirements.txt -r backend/requirements-dev.txt
cd backend && CP_DATA_DIR=/tmp/cp-data uvicorn app.main:app --reload --port 8000
pytest -q                      # 63 passed

# 前端
cd frontend && npm ci
npm run typecheck              # tsc --noEmit
npm test                       # vitest
npm run build                  # 产物在 frontend/dist
npm run dev                    # 开发服务器，/api 代理到 8000
```

环境变量：`CP_DATA_DIR`（SQLite 目录，默认 `./data`）、`CP_VAULT_DIR`（只读源目录，默认仓库同级 `vault`）。

## 功能与接口

前端页面：`/`（项目列表）、`/projects/:id`（项目详情 + 节点 + 改期 + 本项目周投入分配）、`/persons`（人员资料/能力/容量/职责/周视图）、`/imports`（导入报告）。

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/api/health` | 健康检查（含项目数） |
| GET | `/api/meta` | 状态/枚举/标签元数据 |
| GET/POST/PATCH | `/api/persons`、`/api/persons/{id}` | 人员资料：姓名、角色标签、能力 `skills`、默认周容量 `weekly_capacity` |
| GET/POST | `/api/projects`、`/api/projects/{id}` | 项目 CRUD、四态（active/on-hold/done/maintenance） |
| POST | `/api/projects/{id}/archive`、`/restore`、DELETE | 归档不丢历史；有引用不可删 |
| GET/POST/PATCH/DELETE | `/api/projects/{id}/milestones`、`/api/milestones/{id}` | 节点（中文六态）、依赖 |
| GET | `/api/history` | 历史记录（改期原因等） |
| POST | `/api/reschedule/preview` | 改期预览：固定记录版本、changes、affected_not_modified、buffer |
| POST | `/api/reschedule/apply` | 原子提交：原因必填、版本冲突 409、循环/非法日期 400 |
| POST/GET | `/api/imports`、`/api/imports/{id}`、`/api/imports/{id}/report.md` | 只读源导入与报告 |
| POST | `/api/demo/seed` | 写入验收样例（菱形依赖） |
| GET | `/api/persons/{id}/weeks/{week}` | **人员某周全量视图**：容量、占用、超额、剩余、核对状态、分配列表（人员页与项目页共用同一份数据） |
| PUT/DELETE | `/api/persons/{id}/weeks/{week}/capacity` | 指定周容量覆盖 / 删除覆盖（删除才回退默认） |
| PUT | `/api/persons/{id}/weeks/{week}/review` | 显式标记"本周投入已核对" |
| GET/POST/PATCH/DELETE | `/api/assignments` | 项目职责：项目负责人 / 业务对接 / 节点执行 / 统筹管理（不计占用） |
| GET/POST/PATCH/DELETE | `/api/allocations` | 周投入分配：人员 + 项目 + 周 + 人天，可关联节点或整体项目管理 |

### 关键行为约定

- **节点状态**（中文枚举）：外部阻塞 / 内部资源阻塞 / 进行中 / 未开始 / 已完成 / 已取消；`buffer_source` 取 `内部` / `外部阻塞`。
- **缓冲派生**：`W` = 开始日到承诺日的工作日数；`B = max(floor(W*0.2+0.5), 1)`；内部目标 = 承诺日 − B 个工作日（示例 2026-11-02→13：W=10、B=2、目标 11-11）。外部缓冲不可消费。
- **改期**：先预览再提交；按新旧承诺日的**日历日差**平移传递后继，每个节点只平移一次（菱形不叠加）；已完成/已取消只列不改；空日期保留；**跨项目依赖首版不支持**；预览模式必须与提交模式一致（仅当前预览不能联动提交，整笔 400）。
- **失败语义**：循环依赖、非法日期、记录版本变化一律**整笔拒绝**，不写半份历史。
- **导入**：dry-run 在同一事务内应用后整体回滚，不写库；每条记录带 `source_record_hash` 与 `edited_in_app` 保护；相同快照幂等；源变化时先给差异，不覆盖软件内已编辑内容；报告含源定位、哈希、映射、互斥计数（read = imported + skipped + failed）与待确认清单。
- **人员**：E1 不预建周投入/容量，分配执行人不产生 Allocation。

### E2 周容量与分配约定

- **周键**：Asia/Shanghai，周键为该周**周一**日期，覆盖周一至周日；周一由后端 `services/weekly.current_week()` 统一计算，前端 `week.ts` 镜像同一规则。
- **容量**：默认周容量来自人员资料；指定周可覆盖。覆盖值可以是**未知**（`days` 为 null）——指定周的显式未知**不回退**默认，只有**删除该周覆盖**才回退默认。未知 ≠ 0。
- **人天粒度**：非负，步长 0.5 人天；`-0.5`、`1.2` 一律拒绝并保留原值。
- **占用来源**：只有 Allocation 计入占用。职责（Assignment）与节点执行人**不计占用**，不自动填 5 天、不按角色折算。
- **分配类型**：`milestone`（关联具体节点）或 `project_management`（整体项目管理）；有节点时自动派生为 `milestone`，与显式声明矛盾时返回 422。
- **剩余与超额**：容量已知且本周投入已核对 → 剩余精确；容量未知 → 不给精确剩余；占用合计超过容量时，即使未核对也报"已超额"。
- **待补充**：仅被分派、尚无 Allocation 时状态为"投入待补充"，不虚构分配；显式核对后给出剩余；任何分配改动后回到"待补充"。
- **一致性与不重复计入**：人员页与项目页读同一份 Allocation（同一分配 ID 只计一次占用）。项目页按项目筛选时，仍完整列出该人在其他项目的冲突分配，不掩盖冲突集。maintenance 项目的分配同样计入占用。

### 导入用法

容器内 vault 挂载点为 `/vault`（只读）：

```bash
curl -s -X POST http://127.0.0.1:18330/api/imports \
  -H 'content-type: application/json' \
  -d '{"source_root": "/vault", "apply": false}'
```

`apply: false` 为 dry-run（默认，推荐）；`apply: true` 才会写入。导入只读源目录，不修改 vault。

### E2 用法

1. 打开 `/persons`：左侧选人，右侧维护姓名、角色标签、能力、默认周容量；"项目职责"里给某人挂职责（不产生占用）。
2. 在该人的周视图里新增分配：选项目（有节点则选节点）、填人天；或选"整体项目管理"表示该项目的统筹投入。
3. 容量行可临时覆盖本周容量（填数字=覆盖，空/未知=显式未知）；删除覆盖回到默认容量。
4. 本周投入填完后点"本周投入已核对"，才给出精确剩余；之后任何分配改动都会回到"待补充"。
5. 打开 `/projects/:id`：卡片"周投入分配"列出本项目全部分配（带稳定 `分配#ID`）；下方每个相关人的周视图同时显示其**其他项目**的冲突分配，便于定位跨项目冲突。

## E4：导出预览、一致性备份与恢复

E4 交付三件事：**软件状态一致的导出预览**、**每日一致性备份与离线恢复**、**可复现的 Docker 使用路径**。

### 导出预览（只读，不写回 vault）

打开 `/export`：

1. 点「生成导出预览」——后端对 SQLite 做在线一致性快照（`sqlite3.Connection.backup()`），JSON / Markdown / Obsidian 摘要三份产物同源于该快照。
2. 页面展示快照版本、生成时间、各表行数，以及与上一次预览的差异（新增 / 修改 / 删除）。
3. 三个下载入口：JSON、Markdown、Obsidian 摘要。
4. 页面顶部固定提示：**本预览只读取软件数据库，不会写回 vault 笔记或脚本。**

预览产物落在数据目录的 `exports/`（容器内 `/data/exports`），可用 `CP_EXPORT_DIR` 覆盖。

### 每日一致性备份

- 服务启动后起一个后台线程，按固定间隔做一次一致性备份（默认 24 小时，可用 `CP_BACKUP_INTERVAL_HOURS` 调整；`CP_BACKUP_ENABLED=0` 整体关闭）。
- 备份目录：容器内 `/data/backups`，即项目目录 `data/backups`（不在 vault 内）。
- 每次备份是一个版本目录，含 `crossproject.db`（SQLite 一致性副本）、`export.json` 与 `export.md`。
- 备份失败只记录日志，不影响服务运行。

手动触发一次备份：

```bash
curl -s -X POST http://127.0.0.1:18330/api/backup/run
```

### 恢复演练（离线操作）

恢复是离线操作：会先确认应用已停（数据库文件锁），应用仍在运行时会被拒绝。

```bash
# 1) 做一次一致性备份（应用运行中也能备份）
docker compose run --rm --no-deps backend python -m app.backup_cli backup \
  --db /data/sqlite/crossproject.db \
  --backup-dir /data/backups

# 2) 恢复前先停应用（否则会被库锁拒绝），恢复完再起
docker compose stop backend

# 3) 从 JSON 恢复（按当前模型重建库结构并写入数据）
docker compose run --rm --no-deps backend python -m app.backup_cli restore --type json \
  --source /data/backups/<版本>/export.json \
  --db /data/sqlite/crossproject.db

# 4) 从 SQLite 副本恢复（原子替换）
docker compose run --rm --no-deps backend python -m app.backup_cli restore --type sqlite \
  --source /data/backups/<版本>/crossproject.db \
  --db /data/sqlite/crossproject.db

docker compose start backend
```

`docker compose run --no-deps` 起的是一次性容器，不带 `depends_on`，不会顺手把 backend 拉起来和恢复抢库锁。

恢复流程固定为：**校验 → 生成回滚副本 → 原子替换**。校验不通过则不动原库。

回滚副本按版本号命名；同一版本号已存在时自动追加 `-2`、`-3` 序号（最多 50 份，超出报 `FileExistsError`），绝不覆盖上一次的回滚副本——每一份都是「恢复到这一点」的依据，且不会被自动清理。

发布前先用备份 API 把候选库折成一份自洽快照再原子替换，因此候选库 `-wal` 中已提交但尚未 checkpoint 的数据也会并入发布库。

### 环境变量（E4）

| 变量 | 默认 | 说明 |
| --- | --- | --- |
| `CP_BACKUP_DIR` | `data/backups`（项目目录） | 备份根目录 |
| `CP_EXPORT_DIR` | `<数据目录>/exports` | 导出预览产物目录 |
| `CP_BACKUP_ENABLED` | `1` | `0` 关闭每日备份调度 |
| `CP_BACKUP_INTERVAL_HOURS` | `24` | 备份间隔（小时） |

## 已知限制（E2 范围外）

- 工作台 / 跨项目人力视图 → E3
- 跨项目依赖、正式写回 vault 需产品单次切换决定（E4 只准备精确文件范围/托管区块/备份回滚方案，未切换）
- E2 只做当前周视图；历史周可查（按周键请求）但无趋势图与批量编辑

### E4 已知限制

- 正式写回 vault（覆盖笔记/脚本）**未启用**：本版只提供导出预览与精确文件范围/托管区块/备份回滚方案，是否切换由产品单次决定。
- 预览差异只统计新增/修改/删除的行数，不做字段级 diff 展示。
- 每日备份调度在应用进程内运行；进程不运行时不会有备份，需要靠外部定时任务补位。
- 备份保留策略未实现：历史备份目录不会自动清理，需人工清理。
- 本机单用户场景，未做并发写入下的冲突消解（写库仍以单实例运行为前提）。
- 离线恢复不直接复制候选 `.db` 主文件：发布前先用备份 API 折一份自洽快照（`sqlite3.Connection.backup()`），候选库 `-wal` 中已提交但尚未 checkpoint 的数据会一并并入发布库，事务边界完整，不会丢已提交数据。
- 备份版本号精确到秒，同一秒内重复触发会自动追加 `-2`、`-3` 序号；并发触发时各自抢不同版本号，发布冲突会自动重试；显式指定版本号的 CLI 仍然拒绝覆盖既有备份。
- 恢复校验要求候选 `.db` 含当前模型的**全部列**：早于当前版本的备份请走 JSON 恢复路径（按当前模型重建结构）。JSON 恢复还要求导出文件包含当前模型的**全部表**，缺表一律拒绝（避免用不完整的导出清空现库）；**完整但没有任何数据行的导出是合法恢复源**——全新库备份后立即恢复就是这种情形，行数不构成合法性判据。
- 恢复过程独占库锁：应用仍在运行时恢复会被拒绝，替换期间应用也无法启动。
- 现库本身已损坏时，回滚副本保存的是原始字节（不是有效 SQLite 快照），恢复仍会继续。
- 预览环境用 compose 默认网络（`pc-52a8eeac-develop_default`），与正式 QA 容器互不相通；nginx 反代指向服务名 `backend`，该网络内唯一。改服务名时记得同步改 `frontend/nginx.conf`。
