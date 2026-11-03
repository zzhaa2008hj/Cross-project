import { useCallback, useEffect, useRef, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { api } from "../api";
import { ErrorBanner, Field, Loading, errorMessage } from "../components/common";
import PersonFormDialog from "../components/PersonFormDialog";
import PersonMonthPanel from "../components/PersonMonthPanel";
import { parseCapacityDays, parseDays } from "../components/WeekPanel";
import { currentMonth, monthLabel, shiftMonth } from "../month";
import { useMonthParam } from "../useMonthParam";
import type { Assignment, MonthPersonRow, MonthRoster, Project } from "../types";

/** 弹窗状态：新增没有具体人，编辑带着那一行 roster 数据。 */
type DialogState = { mode: "create" } | { mode: "edit"; person: MonthPersonRow } | null;

/** 详情区的三个标签页。默认停在「本月分配」。 */
type DetailTab = "profile" | "roles" | "month";

/**
 * 职责角色：必须与 backend/app/config.py 的 ASSIGNMENT_ROLES 逐字一致，
 * 后端按它校验，不在名单里直接 422。
 */
const ASSIGNMENT_ROLES = ["项目负责人", "业务对接", "节点执行", "统筹管理"];

/**
 * 汇总条文案：一个模板字面量文本节点，getByText 才能精确匹配整串。
 * 数字全部来自上方选中的 roster 行（不调 getPersonMonth，避免同一页请求两次同一份月度数据）。
 */
function summaryText(row: MonthPersonRow, month: string): string {
  const remaining = row.remaining_days == null ? "待核对" : `剩余 ${row.remaining_days}`;
  return `${row.name} · 核定 ${row.monthly_capacity} 人天 · 本月已用 ${row.used_days} · ${remaining} · ${monthLabel(month)}`;
}

interface ProfilePanelProps {
  row: MonthPersonRow;
  onSaved: () => void;
}

/**
 * 「资料」标签页：六项资料全部取自选中的 roster 行，不另调 listPersons。
 * 核定人天必填，走 parseDays（Number("") 会把空值静默变成 0）；
 * 默认周容量可留空 = 未知，用 parseCapacityDays 区分「空」与「非法」。
 */
function ProfilePanel({ row, onSaved }: ProfilePanelProps) {
  const [name, setName] = useState(row.name);
  const [capacity, setCapacity] = useState(String(row.monthly_capacity));
  const [weekly, setWeekly] = useState(row.weekly_capacity == null ? "" : String(row.weekly_capacity));
  const [skills, setSkills] = useState(row.skills);
  const [roles, setRoles] = useState(row.roles);
  const [note, setNote] = useState(row.note);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function save() {
    const trimmedName = name.trim();
    if (!trimmedName) {
      setError("请填写姓名");
      return;
    }
    // 核定人天：非负、0.5 粒度，非法值就地拦下，不发请求。
    const days = parseDays(capacity);
    if (days === null) {
      setError("核定人天必须是非负的 0.5 粒度数字");
      return;
    }
    // 默认周容量：留空 = 未知（提交 null），非法值单独拦下。
    const weeklyDays = parseCapacityDays(weekly);
    if (!weeklyDays.ok) {
      setError("默认周容量必须是非负的 0.5 粒度数字");
      return;
    }
    setError(null);
    setBusy(true);
    try {
      await api.updatePerson(row.person_id, {
        name: trimmedName,
        monthly_capacity: days,
        weekly_capacity: weeklyDays.days,
        skills: skills.trim(),
        roles: roles.trim(),
        note: note.trim(),
      });
      onSaved();
    } catch (e) {
      // 失败时保留已填内容，方便改完重试。
      setError(errorMessage(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div>
      <ErrorBanner error={error} />
      <div className="form-grid">
        <Field label="姓名">
          <input
            aria-label="姓名"
            value={name}
            disabled={busy}
            onChange={(e) => setName(e.target.value)}
          />
        </Field>
        <Field label="核定人天">
          <input
            aria-label="核定人天"
            type="number"
            step="0.5"
            value={capacity}
            disabled={busy}
            onChange={(e) => setCapacity(e.target.value)}
          />
        </Field>
        <Field label="默认周容量" hint="周口径用，工作台/项目页按周看">
          <input
            aria-label="默认周容量"
            type="number"
            step="0.5"
            value={weekly}
            disabled={busy}
            onChange={(e) => setWeekly(e.target.value)}
          />
        </Field>
        <Field label="能力标签">
          <input
            aria-label="能力标签"
            value={skills}
            disabled={busy}
            onChange={(e) => setSkills(e.target.value)}
          />
        </Field>
        <Field label="角色标签">
          <input
            aria-label="角色标签"
            value={roles}
            disabled={busy}
            onChange={(e) => setRoles(e.target.value)}
          />
        </Field>
        <Field label="备注">
          <textarea
            aria-label="备注"
            rows={3}
            value={note}
            disabled={busy}
            onChange={(e) => setNote(e.target.value)}
          />
        </Field>
      </div>
      <div className="form-actions">
        <button type="button" disabled={busy} onClick={() => void save()}>
          保存资料
        </button>
      </div>
    </div>
  );
}

interface RolesPanelProps {
  projects: Project[];
  assignments: Assignment[];
  error: string | null;
  onCreate: (projectId: number, role: string) => void;
  onDelete: (assignmentId: number) => void;
}

/**
 * 「项目职责」标签页：只管职责，不计占用。
 * 「添加职责」直接发请求，面板里没有「保存」按钮。
 */
function RolesPanel({ projects, assignments, error, onCreate, onDelete }: RolesPanelProps) {
  const [projectId, setProjectId] = useState("");
  const [role, setRole] = useState("");
  const [formError, setFormError] = useState<string | null>(null);

  function submit() {
    if (!projectId) {
      setFormError("请选择项目");
      return;
    }
    if (!role) {
      setFormError("请选择职责角色");
      return;
    }
    setFormError(null);
    onCreate(Number(projectId), role);
  }

  return (
    <div>
      <ErrorBanner error={error} />
      <ErrorBanner error={formError} />

      {assignments.length === 0 ? (
        <p className="muted empty">还没有项目职责</p>
      ) : (
        <ul className="assignment-list">
          {assignments.map((a) => (
            <li key={a.id}>
              <span>{`${a.project_name ?? `#${a.project_id}`} · ${a.role}`}</span>
              <button type="button" className="ghost" onClick={() => onDelete(a.id)}>
                删除
              </button>
            </li>
          ))}
        </ul>
      )}

      <div className="form-grid">
        <Field label="职责项目">
          <select
            aria-label="职责项目"
            value={projectId}
            onChange={(e) => setProjectId(e.target.value)}
          >
            <option value="">请选择</option>
            {projects.map((p) => (
              <option key={p.id} value={String(p.id)}>
                {p.name}
              </option>
            ))}
          </select>
        </Field>
        <Field label="职责角色">
          <select aria-label="职责角色" value={role} onChange={(e) => setRole(e.target.value)}>
            <option value="">请选择</option>
            {ASSIGNMENT_ROLES.map((r) => (
              <option key={r} value={r}>
                {r}
              </option>
            ))}
          </select>
        </Field>
      </div>
      <div className="form-actions">
        <button type="button" onClick={submit}>
          添加职责
        </button>
      </div>
    </div>
  );
}

/**
 * 人员页上半屏：月度人员表。
 * 月份来自 ?month=（useMonthParam），已禁用的人默认不显示（后端按参数过滤），
 * 勾上「显示已禁用」后按后端的 archived, name 顺序追加在表尾并整行灰显。
 */
export default function PersonPage() {
  const [month, setMonth] = useMonthParam();
  const [showArchived, setShowArchived] = useState(false);
  const [roster, setRoster] = useState<MonthRoster | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [dialog, setDialog] = useState<DialogState>(null);

  // 详情区：汇总条 + 三个标签页，默认停在「本月分配」。
  const [tab, setTab] = useState<DetailTab>("month");
  const [projects, setProjects] = useState<Project[]>([]);
  const [assignments, setAssignments] = useState<Assignment[]>([]);
  // 已加载过职责的人员 id：切标签页不重复拉，换人才重拉。
  const [assignmentsFor, setAssignmentsFor] = useState<number | null>(null);
  const [rolesError, setRolesError] = useState<string | null>(null);

  const [searchParams] = useSearchParams();
  const preselected = searchParams.get("person");

  // 请求序号：只有最后一次请求的结果才允许渲染，避免旧响应覆盖新数据。
  const requestSeq = useRef(0);

  const load = useCallback(async () => {
    const seq = ++requestSeq.current;
    setError(null);
    try {
      const next = await api.listMonthlyRoster(month, showArchived);
      if (seq !== requestSeq.current) return; // 过期响应，丢弃
      setRoster(next);
    } catch (e) {
      if (seq !== requestSeq.current) return; // 过期响应，丢弃
      setError(errorMessage(e));
    }
  }, [month, showArchived]);

  // 始终指向最新的 load：load 依赖 [month, showArchived]，换月/换开关会重建。
  // 写操作完成后重拉必须用最新的一份，否则会拉回点击那一刻的旧数据。
  const loadRef = useRef(load);
  loadRef.current = load;

  useEffect(() => {
    void load();
  }, [load]);

  // 项目下拉给「项目职责」标签页用：进页面就拉一次，切标签页不再重拉。
  useEffect(() => {
    let cancelled = false;
    void (async () => {
      try {
        const rows = (await api.listProjects()) ?? [];
        if (!cancelled) setProjects(rows);
      } catch {
        // 忽略：项目列表为空时职责下拉选不了项目，不影响其他标签页。
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  // 从工作台跳转过来时按 URL 指定的人员选中。
  useEffect(() => {
    if (!roster || !preselected) return;
    const target = roster.people.find((p) => String(p.person_id) === preselected);
    if (target) setSelectedId(target.person_id);
  }, [roster, preselected]);

  async function toggleArchived(row: MonthPersonRow) {
    setError(null);
    try {
      if (row.archived) {
        await api.restorePerson(row.person_id);
      } else {
        await api.archivePerson(row.person_id);
      }
      // 重拉用最新的一份 load：写请求飞行途中换月/换开关也不会拉回旧数据。
      await loadRef.current();
    } catch (e) {
      setError(errorMessage(e));
    }
  }

  /** 写操作成功后刷新自己的数据：roster 换最新，职责列表也重拉。 */
  const reload = useCallback(() => {
    void loadRef.current();
  }, []);

  const loadAssignments = useCallback(async (personId: number) => {
    const rows = (await api.listAssignments({ person_id: personId })) ?? [];
    setAssignments(rows);
    setAssignmentsFor(personId);
  }, []);

  // 职责列表只在「项目职责」标签页首次打开时拉一次；换人再重拉。
  useEffect(() => {
    if (tab !== "roles" || selectedId === null) return;
    if (assignmentsFor === selectedId) return;
    let cancelled = false;
    void (async () => {
      try {
        const rows = (await api.listAssignments({ person_id: selectedId })) ?? [];
        if (cancelled) return;
        setAssignments(rows);
        setAssignmentsFor(selectedId);
      } catch (e) {
        if (!cancelled) setRolesError(errorMessage(e));
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [tab, selectedId, assignmentsFor]);

  async function addAssignment(projectId: number, role: string) {
    if (selectedId === null) return;
    setRolesError(null);
    try {
      await api.createAssignment({ person_id: selectedId, project_id: projectId, role });
      reload();
      await loadAssignments(selectedId);
    } catch (e) {
      setRolesError(errorMessage(e));
    }
  }

  async function removeAssignment(assignmentId: number) {
    if (selectedId === null) return;
    setRolesError(null);
    try {
      await api.deleteAssignment(assignmentId);
      reload();
      await loadAssignments(selectedId);
    } catch (e) {
      setRolesError(errorMessage(e));
    }
  }

  const rows = roster?.people ?? [];
  const selectedRow = rows.find((r) => r.person_id === selectedId) ?? null;
  // 职责列表只认当前这个人的：换人后旧数据不闪一下。
  const visibleAssignments = assignmentsFor === selectedId ? assignments : [];

  // aria-selected 的类型是 Booleanish：写 String(...) 会推成 string 编译不过，
  // 这里显式返回 "true" | "false" 两个字面量，且三个按钮始终带该属性。
  const tabSelected = (key: DetailTab): "true" | "false" => (tab === key ? "true" : "false");

  return (
    <div className="page">
      <div className="page-head">
        <h2>人员</h2>
        <p className="muted">按月看核定人天与本月占用；已禁用的人默认不显示。</p>
      </div>

      <ErrorBanner error={error} />

      <div className="toolbar">
        <button type="button" onClick={() => setDialog({ mode: "create" })}>
          + 新增人员
        </button>
        <Field label="显示已禁用">
          <input
            type="checkbox"
            aria-label="显示已禁用"
            checked={showArchived}
            onChange={(e) => setShowArchived(e.target.checked)}
          />
        </Field>

        <div className="toolbar-right">
          <button type="button" onClick={() => setMonth(shiftMonth(month, -1))}>
            ‹
          </button>
          <span className="muted">统计月份：</span>
          <span className="month-label">{monthLabel(month)}</span>
          <button type="button" onClick={() => setMonth(shiftMonth(month, 1))}>
            ›
          </button>
          <button type="button" className="ghost" onClick={() => setMonth(currentMonth())}>
            本月
          </button>
        </div>
      </div>

      {roster ? (
        <table className="table table-persons" aria-label="人员列表">
          <colgroup>
            <col className="col-name" />
            <col className="col-num" />
            <col className="col-num" />
            <col className="col-projects" />
            <col className="col-status" />
            <col className="col-actions" />
          </colgroup>
          <thead>
            <tr>
              <th>姓名</th>
              <th className="cell-num">核定人天</th>
              <th className="cell-num">本月占用</th>
              <th>参与项目</th>
              <th>状态</th>
              <th>操作</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => {
              const over = row.over_days != null;
              return (
                <tr
                  key={row.person_id}
                  className={
                    [row.archived ? "row-archived" : "", selectedId === row.person_id ? "row-selected" : ""]
                      .filter(Boolean)
                      .join(" ") || undefined
                  }
                >
                  <td>
                    <button
                      type="button"
                      className="cell-name"
                      onClick={() => setSelectedId(row.person_id)}
                    >
                      {row.name}
                    </button>
                  </td>
                  <td className="cell-num">{row.monthly_capacity}</td>
                  <td className="cell-num">
                    <div>{row.used_days}</div>
                    <progress
                      className={over ? "cell-progress cell-progress-over" : "cell-progress"}
                      value={row.used_days}
                      max={Math.max(row.monthly_capacity, 0.0001)}
                    />
                    {over ? (
                      <div className="cell-over">超 {row.over_days} 人天</div>
                    ) : row.remaining_days != null ? (
                      <div>{row.remaining_days}</div>
                    ) : (
                      <div className="muted">待核对</div>
                    )}
                  </td>
                  <td>
                    {row.projects.map((p) => (
                      <span key={p.project_id} className="tag">
                        {p.project_name}
                        {p.roles.length ? ` · ${p.roles.join("、")}` : ""}
                      </span>
                    ))}
                  </td>
                  <td>
                    {row.archived ? <span className="tag tag-warn">已禁用</span> : <span>启用</span>}
                  </td>
                  <td>
                    <div className="row-actions">
                      <button
                        type="button"
                        onClick={() => setDialog({ mode: "edit", person: row })}
                      >
                        编辑
                      </button>
                      <button type="button" onClick={() => void toggleArchived(row)}>
                        {row.archived ? "启用" : "禁用"}
                      </button>
                    </div>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      ) : error ? null : (
        <Loading />
      )}

      {selectedRow ? (
        <section className="detail" aria-label="人员详情">
          <div className="detail-summary">{summaryText(selectedRow, month)}</div>

          <div className="tabs" role="tablist" aria-label="详情标签页">
            <button
              type="button"
              role="tab"
              className="tab"
              aria-selected={tabSelected("profile")}
              onClick={() => setTab("profile")}
            >
              资料
            </button>
            <button
              type="button"
              role="tab"
              className="tab"
              aria-selected={tabSelected("roles")}
              onClick={() => setTab("roles")}
            >
              项目职责
            </button>
            <button
              type="button"
              role="tab"
              className="tab"
              aria-selected={tabSelected("month")}
              onClick={() => setTab("month")}
            >
              本月分配
            </button>
          </div>

          {/* 三个面板都常驻：切标签页只改 state，不重新拉数据，也不丢面板内部状态。 */}
          <div className="tab-panel" role="tabpanel" hidden={tab !== "profile"}>
            <ProfilePanel key={selectedRow.person_id} row={selectedRow} onSaved={reload} />
          </div>
          <div className="tab-panel" role="tabpanel" hidden={tab !== "roles"}>
            <RolesPanel
              projects={projects}
              assignments={visibleAssignments}
              error={rolesError}
              onCreate={(projectId, role) => void addAssignment(projectId, role)}
              onDelete={(assignmentId) => void removeAssignment(assignmentId)}
            />
          </div>
          <div className="tab-panel" role="tabpanel" hidden={tab !== "month"}>
            <PersonMonthPanel
              personId={selectedRow.person_id}
              month={month}
              archived={selectedRow.archived}
              onChanged={reload}
            />
          </div>
        </section>
      ) : null}

      {dialog ? (
        <PersonFormDialog
          person={dialog.mode === "edit" ? dialog.person : null}
          onClose={() => setDialog(null)}
          onSaved={() => {
            setDialog(null);
            reload();
          }}
        />
      ) : null}
    </div>
  );
}
