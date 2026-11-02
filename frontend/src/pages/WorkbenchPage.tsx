import { useCallback, useEffect, useMemo, useState } from "react";
import { api } from "../api";
import { EmptyState, ErrorBanner, Field, Loading, errorMessage } from "../components/common";
import { projectStateLabel } from "../labels";
import { currentWeek, shiftWeek } from "../week";
import type { Person, Project, Workbench, WorkbenchProject } from "../types";

/** 待处理事项的类别标签。顺序与后端一致：异常在前，待补数据在后。 */
export const TODO_KIND_LABEL: Record<string, string> = {
  overdue: "逾期",
  blocked: "阻塞",
  due_soon: "临近交付",
  unassigned: "待分派",
  missing_allocation: "待填投入",
  capacity: "容量待确认",
  review: "待核对",
};

function ProjectCard({
  project,
  week,
  expanded,
  onToggle,
}: {
  project: WorkbenchProject;
  week: string;
  expanded: boolean;
  onToggle: () => void;
}) {
  return (
    <article className="card" data-testid={`project-${project.id}`}>
      <header className="card-head">
        <h3>{project.name}</h3>
        {project.priority ? <span className="tag">{project.priority}</span> : null}
        <span className="tag">{projectStateLabel(project.state)}</span>
        {project.on_hold ? <span className="tag tag-warn">已暂停</span> : null}
        <a className="link" href={`/projects/${project.id}?week=${week}`}>
          查看项目
        </a>
      </header>
      <p className="muted">
        当前重点：{project.current_focus_name ?? "未设置"}；本周投入 {project.allocation_days} 人天
      </p>
      <p className="muted">
        逾期 {project.overdue_count}；阻塞 {project.blocked_count}；本周临近交付 {project.due_soon_count}
      </p>
      <button type="button" onClick={onToggle} aria-expanded={expanded}>
        {expanded ? "收起节点" : "展开节点"}
      </button>
      {expanded ? (
        <ul className="list">
          {project.milestones.map((m) => (
            <li key={m.id}>
              <span>{m.name}</span>
              <span className="muted">（{m.state}）</span>
              {m.overdue ? <span className="tag tag-warn">逾期</span> : null}
              {m.due_this_week ? <span className="tag tag-info">临近交付</span> : null}
              {m.blocked ? <span className="tag tag-warn">阻塞</span> : null}
              {m.assignee_name ? <span className="muted">负责：{m.assignee_name}</span> : null}
            </li>
          ))}
        </ul>
      ) : null}
    </article>
  );
}

/**
 * 工作台：跨项目汇总入口。
 * 只读；过滤只决定项目与人员范围，人员占用与合计始终保持完整。
 */
export default function WorkbenchPage() {
  const [week, setWeek] = useState<string>(() => currentWeek());
  const [projectFilter, setProjectFilter] = useState("");
  const [ownerFilter, setOwnerFilter] = useState("");
  const [data, setData] = useState<Workbench | null>(null);
  const [projects, setProjects] = useState<Project[]>([]);
  const [persons, setPersons] = useState<Person[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [expanded, setExpanded] = useState<number[]>([]);

  useEffect(() => {
    api.listProjects().then(setProjects).catch(() => undefined);
    api.listPersons().then(setPersons).catch(() => undefined);
  }, []);

  const load = useCallback(async () => {
    setError(null);
    try {
      const params: {
        week: string;
        project_id?: number;
        owner_person_id?: number;
      } = { week };
      if (projectFilter) params.project_id = Number(projectFilter);
      if (ownerFilter) params.owner_person_id = Number(ownerFilter);
      setData(await api.getWorkbench(params));
    } catch (e) {
      setError(errorMessage(e));
      setData(null);
    } finally {
      setLoading(false);
    }
  }, [week, projectFilter, ownerFilter]);

  useEffect(() => {
    void load();
  }, [load]);

  const toggle = (id: number) =>
    setExpanded((prev) =>
      prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id],
    );

  const weekLabel = useMemo(() => {
    if (!data) return `${week} ~ ${shiftWeek(week, 6)}`;
    return `${data.week} ~ ${data.week_end}`;
  }, [data, week]);

  if (loading) return <Loading text="加载工作台…" />;

  return (
    <section className="page">
      <h1>工作台</h1>
      <ErrorBanner error={error} />

      <div className="filters">
        <Field label="周">
          <div className="row">
            <button type="button" onClick={() => setWeek(shiftWeek(week, -1))}>
              上一周
            </button>
            <button type="button" onClick={() => setWeek(currentWeek())}>
              本周
            </button>
            <button type="button" onClick={() => setWeek(shiftWeek(week, 1))}>
              下一周
            </button>
            <span className="muted">周区间 {weekLabel}</span>
          </div>
        </Field>
        <Field label="项目">
          <select
            aria-label="项目筛选"
            value={projectFilter}
            onChange={(e) => setProjectFilter(e.target.value)}
          >
            <option value="">全部项目</option>
            {projects.map((p) => (
              <option key={p.id} value={p.id}>
                {p.name}
              </option>
            ))}
          </select>
        </Field>
        <Field label="项目负责人">
          <select
            aria-label="项目负责人筛选"
            value={ownerFilter}
            onChange={(e) => setOwnerFilter(e.target.value)}
          >
            <option value="">全部负责人</option>
            {persons.map((p) => (
              <option key={p.id} value={p.id}>
                {p.name}
              </option>
            ))}
          </select>
        </Field>
      </div>

      <section aria-label="待处理事项">
        <h2>待处理事项</h2>
        {data && data.has_pending ? (
          <ul className="list">
            {data.todos.map((todo, i) => (
              <li key={`${todo.kind}-${todo.milestone_id ?? "x"}-${todo.person_id ?? "x"}-${i}`}>
                <span className="tag">{TODO_KIND_LABEL[todo.kind] ?? todo.kind}</span>
                <span>{todo.detail}</span>
                {todo.kind === "due_soon" ? (
                  <span className="muted">（{todo.week_label}）</span>
                ) : null}
              </li>
            ))}
          </ul>
        ) : (
          <EmptyState text="当前没有待处理事项" />
        )}
      </section>

      <section aria-label="项目">
        <h2>项目</h2>
        {data && data.projects.length > 0 ? (
          data.projects.map((p) => (
            <ProjectCard
              key={p.id}
              project={p}
              week={week}
              expanded={expanded.includes(p.id)}
              onToggle={() => toggle(p.id)}
            />
          ))
        ) : (
          <EmptyState text="当前范围内没有项目" />
        )}
      </section>

      <section aria-label="维护项目">
        <h2>维护项目</h2>
        {data && data.maintenance_projects.length > 0 ? (
          data.maintenance_projects.map((p) => (
            <ProjectCard
              key={p.id}
              project={p}
              week={week}
              expanded={expanded.includes(p.id)}
              onToggle={() => toggle(p.id)}
            />
          ))
        ) : (
          <EmptyState text="当前没有维护期项目" />
        )}
      </section>

      <section aria-label="人员安排">
        <h2>人员安排</h2>
        {data && data.people.length > 0 ? (
          data.people.map((person) => (
            <article className="card" key={person.person_id}>
              <header className="card-head">
                <h3>{person.name}</h3>
                <span className="muted">{person.status_text}</span>
                <a className="link" href={`/persons?week=${week}&person=${person.person_id}`}>
                  查看人员
                </a>
              </header>
              <p className="muted">
                本周投入 {person.total_days} 人天
                {person.over_days ? `，超出 ${person.over_days} 人天` : ""}
                {person.remaining_days !== null ? `，剩余 ${person.remaining_days} 人天` : ""}
              </p>
              <ul className="list">
                {person.conflicts.map((c) => (
                  <li key={c.project_id}>
                    <span>{c.project_name ?? `项目 #${c.project_id}`}</span>
                    {c.project_state ? (
                      <span className="muted">（{projectStateLabel(c.project_state)}）</span>
                    ) : null}
                    <span className="muted">{c.days} 人天</span>
                    {c.allocations.map((a) => (
                      <span key={a.id} className="muted">
                        {" "}
                        分配#{a.id}
                      </span>
                    ))}
                  </li>
                ))}
              </ul>
            </article>
          ))
        ) : (
          <EmptyState text="当前范围内没有人员" />
        )}
      </section>
    </section>
  );
}
