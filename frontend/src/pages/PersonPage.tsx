import { useCallback, useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { api } from "../api";
import { EmptyState, ErrorBanner, Field, Loading, errorMessage } from "../components/common";
import WeekPanel from "../components/WeekPanel";
import { currentWeek, shiftWeek } from "../week";
import { useWeekParam } from "../useWeekParam";
import type { Assignment, Person, Project } from "../types";

/** 项目职责的标准角色。职责只表达角色，不计入任何占用。 */
export const ASSIGNMENT_ROLES = ["项目负责人", "业务对接", "节点执行", "统筹管理"];

interface PersonForm {
  name: string;
  skills: string;
  weekly_capacity: string;
  roles: string;
  note: string;
}

function toForm(person: Person): PersonForm {
  return {
    name: person.name,
    skills: person.skills ?? "",
    weekly_capacity:
      person.weekly_capacity === null ? "" : String(person.weekly_capacity),
    roles: person.roles ?? "",
    note: person.note ?? "",
  };
}

/**
 * 人员页：资料与能力、默认周容量、项目职责，以及本周投入分配视图。
 * 与项目页共用 WeekPanel 与同一个后端汇总接口，占用不会被重复计入。
 */
export default function PersonPage() {
  const [persons, setPersons] = useState<Person[]>([]);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  const [form, setForm] = useState<PersonForm | null>(null);
  const [projects, setProjects] = useState<Project[]>([]);
  const [assignments, setAssignments] = useState<Assignment[]>([]);
  const [assignmentProject, setAssignmentProject] = useState("");
  const [assignmentRole, setAssignmentRole] = useState(ASSIGNMENT_ROLES[0]);

  const [week, setWeek] = useWeekParam();
  const [searchParams] = useSearchParams();
  const preselected = searchParams.get("person");

  const loadPersons = useCallback(async () => {
    setError(null);
    try {
      const rows = await api.listPersons();
      setPersons(rows);
      setSelectedId((prev) => {
        // 从工作台跳转过来时按 URL 指定的人员打开。
        if (preselected) {
          const target = rows.find((r) => String(r.id) === preselected);
          if (target) return target.id;
        }
        return prev ?? (rows[0]?.id ?? null);
      });
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setLoading(false);
    }
  }, [preselected]);

  useEffect(() => {
    void loadPersons();
  }, [loadPersons]);

  useEffect(() => {
    api
      .listProjects()
      .then(setProjects)
      .catch(() => undefined);
  }, []);

  const selected = persons.find((p) => p.id === selectedId) ?? null;

  useEffect(() => {
    if (selected) setForm(toForm(selected));
  }, [selected]);

  const loadAssignments = useCallback(async (personId: number) => {
    try {
      setAssignments(await api.listAssignments({ person_id: personId }));
    } catch (e) {
      setError(errorMessage(e));
    }
  }, []);

  useEffect(() => {
    if (selectedId !== null) void loadAssignments(selectedId);
  }, [selectedId, loadAssignments]);

  async function saveProfile() {
    if (!selected || !form) return;
    setError(null);
    setSaving(true);
    try {
      const capacity = form.weekly_capacity.trim();
      await api.updatePerson(selected.id, {
        name: form.name.trim(),
        skills: form.skills.trim(),
        roles: form.roles.trim(),
        note: form.note.trim(),
        weekly_capacity: capacity === "" ? null : Number(capacity),
      });
      await loadPersons();
    } catch (e) {
      // 失败时保留已填内容，方便用户修改后重试。
      setError(errorMessage(e));
    } finally {
      setSaving(false);
    }
  }

  async function addAssignment() {
    if (!selected || !assignmentProject) {
      setError("请选择项目");
      return;
    }
    setError(null);
    try {
      await api.createAssignment({
        person_id: selected.id,
        project_id: Number(assignmentProject),
        role: assignmentRole,
      });
      await loadAssignments(selected.id);
    } catch (e) {
      setError(errorMessage(e));
    }
  }

  if (loading) return <Loading />;

  return (
    <div className="page">
      <div className="page-head">
        <h2>人员</h2>
        <p className="muted">能力资料、周容量与项目职责；周投入分配在下方按周查看。</p>
      </div>

      <ErrorBanner error={error} />

      <div className="card">
        <h3>人员列表</h3>
        {persons.length === 0 ? (
          <EmptyState text="还没有人员" />
        ) : (
          <ul aria-label="人员列表">
            {persons.map((p) => (
              <li key={p.id}>
                <button type="button" onClick={() => setSelectedId(p.id)}>
                  {p.name}
                </button>
                <span className="muted"> {p.skills || "能力待补充"}</span>
                <span className="muted">
                  {" "}
                  默认容量{" "}
                  {p.weekly_capacity === null ? "未知" : `${p.weekly_capacity} 人天`}
                </span>
              </li>
            ))}
          </ul>
        )}
      </div>

      {selected && form ? (
        <>
          <div className="card">
            <h3>资料：{selected.name}</h3>
            <div className="form-grid">
              <Field label="姓名">
                <input
                  aria-label="姓名"
                  value={form.name}
                  onChange={(e) => setForm({ ...form, name: e.target.value })}
                />
              </Field>
              <Field label="能力标签" hint="如：地质AI、遥感">
                <input
                  aria-label="能力标签"
                  value={form.skills}
                  onChange={(e) => setForm({ ...form, skills: e.target.value })}
                />
              </Field>
              <Field label="默认周容量" hint="留空表示未知；指定周可单独覆盖">
                <input
                  aria-label="默认周容量"
                  value={form.weekly_capacity}
                  onChange={(e) => setForm({ ...form, weekly_capacity: e.target.value })}
                />
              </Field>
            </div>
            <div className="form-actions">
              <button type="button" disabled={saving} onClick={() => void saveProfile()}>
                保存资料
              </button>
            </div>
          </div>

          <div className="card">
            <h3>项目职责</h3>
            <p className="muted">职责不计入占用，只说明角色；实际投入请在周投入分配中填写。</p>
            {assignments.length === 0 ? (
              <EmptyState text="还没有项目职责" />
            ) : (
              <ul aria-label="职责列表">
                {assignments.map((a) => (
                  <li key={a.id}>
                    {a.project_name ?? `#${a.project_id}`} · {a.role}
                  </li>
                ))}
              </ul>
            )}
            <div className="form-grid">
              <Field label="职责项目">
                <select
                  aria-label="职责项目"
                  value={assignmentProject}
                  onChange={(e) => setAssignmentProject(e.target.value)}
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
                <select
                  aria-label="职责角色"
                  value={assignmentRole}
                  onChange={(e) => setAssignmentRole(e.target.value)}
                >
                  {ASSIGNMENT_ROLES.map((r) => (
                    <option key={r} value={r}>
                      {r}
                    </option>
                  ))}
                </select>
              </Field>
            </div>
            <div className="form-actions">
              <button type="button" onClick={() => void addAssignment()}>
                添加职责
              </button>
            </div>
          </div>

          <div className="card">
            <h3>周投入分配</h3>
            <div className="row" role="group" aria-label="周选择">
              <button type="button" onClick={() => setWeek(shiftWeek(week, -1))}>
                上一周
              </button>
              <button type="button" onClick={() => setWeek(currentWeek())}>
                本周
              </button>
              <button type="button" onClick={() => setWeek(shiftWeek(week, 1))}>
                下一周
              </button>
              <span className="muted">
                周区间 {week} ~ {shiftWeek(week, 6)}
              </span>
            </div>
            <WeekPanel personId={selected.id} week={week} />
          </div>
        </>
      ) : null}
    </div>
  );
}
