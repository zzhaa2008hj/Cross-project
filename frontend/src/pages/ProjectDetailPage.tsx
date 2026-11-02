import { useCallback, useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import type { FormEvent } from "react";
import { api, ApiError } from "../api";
import HistoryPanel from "../components/HistoryPanel";
import MilestoneForm, {
  draftFrom,
  draftToPayload,
  emptyDraft,
  type MilestoneDraft,
} from "../components/MilestoneForm";
import RescheduleDialog from "../components/RescheduleDialog";
import { EmptyState, ErrorBanner, Field, Loading } from "../components/common";
import {
  PROJECT_STATE_LABEL,
  bufferWarnings,
  describeBuffer,
  formatDate,
  milestoneStateLabel,
} from "../labels";
import type { Milestone, Person, Project } from "../types";

export default function ProjectDetailPage() {
  const { projectId } = useParams();
  const pid = Number(projectId);

  const [project, setProject] = useState<Project | null>(null);
  const [persons, setPersons] = useState<Person[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [historyKey, setHistoryKey] = useState(0);

  const [editing, setEditing] = useState<Milestone | null>(null);
  const [creating, setCreating] = useState(false);
  const [draft, setDraft] = useState<MilestoneDraft>(emptyDraft());
  const [rescheduleTarget, setRescheduleTarget] = useState<Milestone | null>(null);

  const [personName, setPersonName] = useState("");
  const [personRoles, setPersonRoles] = useState("");

  const load = useCallback(async () => {
    setError(null);
    try {
      const [p, ps] = await Promise.all([api.getProject(pid), api.listPersons()]);
      setProject(p);
      setPersons(ps);
    } catch (e) {
      setError(e instanceof ApiError ? e.detail : String(e));
      setProject(null);
    }
  }, [pid]);

  useEffect(() => {
    void load();
  }, [load]);

  async function patchProject(payload: Partial<Project>) {
    setError(null);
    setMessage(null);
    setBusy(true);
    try {
      setProject(await api.updateProject(pid, payload));
      setHistoryKey((k) => k + 1);
    } catch (e) {
      setError(e instanceof ApiError ? e.detail : String(e));
    } finally {
      setBusy(false);
    }
  }

  async function toggleArchived() {
    setError(null);
    setMessage(null);
    setBusy(true);
    try {
      // 归档/恢复走专用接口：ProjectUpdate 不接受 archived 字段
      const next = project?.archived ? await api.restoreProject(pid) : await api.archiveProject(pid);
      setProject(next);
      setMessage(next.archived ? "项目已归档" : "项目已恢复");
      setHistoryKey((k) => k + 1);
    } catch (e) {
      setError(e instanceof ApiError ? e.detail : String(e));
    } finally {
      setBusy(false);
    }
  }

  async function saveMilestone() {
    setError(null);
    setMessage(null);
    setBusy(true);
    try {
      const payload = draftToPayload(draft);
      if (editing) {
        await api.updateMilestone(editing.id, payload);
        setMessage(`已更新节点「${payload.name}」`);
      } else {
        await api.createMilestone(pid, payload);
        setMessage(`已创建节点「${payload.name}」`);
      }
      setEditing(null);
      setCreating(false);
      setDraft(emptyDraft());
      await load();
      setHistoryKey((k) => k + 1);
    } catch (e) {
      setError(e instanceof ApiError ? e.detail : String(e));
    } finally {
      setBusy(false);
    }
  }

  async function archiveMilestone(m: Milestone) {
    setError(null);
    setMessage(null);
    try {
      await api.archiveMilestone(m.id);
      setMessage(`已归档节点「${m.name}」（历史保留）`);
      await load();
      setHistoryKey((k) => k + 1);
    } catch (e) {
      setError(e instanceof ApiError ? e.detail : String(e));
    }
  }

  async function deleteMilestone(m: Milestone) {
    setError(null);
    setMessage(null);
    try {
      await api.deleteMilestone(m.id);
      setMessage(`已删除节点「${m.name}」（历史保留）`);
      await load();
      setHistoryKey((k) => k + 1);
    } catch (e) {
      setError(e instanceof ApiError ? e.detail : String(e));
    }
  }

  async function createPerson(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setMessage(null);
    setBusy(true);
    try {
      const p = await api.createPerson({
        name: personName.trim(),
        roles: personRoles.trim(),
      });
      setMessage(`已添加人员「${p.name}」`);
      setPersonName("");
      setPersonRoles("");
      await load();
    } catch (e) {
      setError(e instanceof ApiError ? e.detail : String(e));
    } finally {
      setBusy(false);
    }
  }

  if (project === null && !error) return <Loading />;
  if (!project) {
    return (
      <section>
        <ErrorBanner error={error} />
        <Link to="/">返回项目列表</Link>
      </section>
    );
  }

  const milestones = project.milestones ?? [];
  const siblings = milestones.filter((m) => !m.archived);
  const nameOf = (id: number) => milestones.find((m) => m.id === id)?.name ?? `#${id}`;

  return (
    <section>
      <div className="page-head">
        <h1>
          {project.name}
          {project.archived ? <span className="tag">已归档</span> : null}
        </h1>
        <div className="page-actions">
          <Link to="/" className="link">
            ← 项目列表
          </Link>
          <button
            type="button"
            onClick={() => void toggleArchived()}
            disabled={busy}
          >
            {project.archived ? "恢复项目" : "归档项目"}
          </button>
        </div>
      </div>

      <ErrorBanner error={error} />
      {message ? <p className="banner banner-ok">{message}</p> : null}

      <div className="card">
        <div className="form-grid">
          <Field label="项目状态">
            <select
              value={project.state}
              onChange={(e) => patchProject({ state: e.target.value as Project["state"] })}
              disabled={busy}
            >
              {Object.entries(PROJECT_STATE_LABEL).map(([value, label]) => (
                <option key={value} value={value}>
                  {label}
                </option>
              ))}
            </select>
          </Field>
          <Field label="优先级">
            <input
              defaultValue={project.priority}
              onBlur={(e) => {
                if (e.target.value !== project.priority)
                  patchProject({ priority: e.target.value });
              }}
            />
          </Field>
          <Field label="当前重点节点" hint="手动指定，E1 不自动推导">
            <select
              value={project.current_focus_milestone_id ?? ""}
              onChange={(e) =>
                patchProject({
                  current_focus_milestone_id: e.target.value ? Number(e.target.value) : null,
                })
              }
              disabled={busy}
            >
              <option value="">未设置</option>
              {milestones.map((m) => (
                <option key={m.id} value={m.id}>
                  {m.name}
                </option>
              ))}
            </select>
          </Field>
          <Field label="进展">
            <input
              defaultValue={project.progress}
              onBlur={(e) => {
                if (e.target.value !== project.progress)
                  patchProject({ progress: e.target.value });
              }}
            />
          </Field>
          <Field label="备注">
            <input
              defaultValue={project.note}
              onBlur={(e) => {
                if (e.target.value !== project.note) patchProject({ note: e.target.value });
              }}
            />
          </Field>
        </div>
      </div>

      <div className="page-head">
        <h2>节点（{milestones.length}）</h2>
        <div className="page-actions">
          <button
            type="button"
            onClick={() => {
              setCreating(true);
              setEditing(null);
              setDraft(emptyDraft());
            }}
          >
            新建节点
          </button>
        </div>
      </div>

      {creating || editing ? (
        <MilestoneForm
          draft={draft}
          setDraft={setDraft}
          persons={persons}
          siblings={siblings.filter((m) => m.id !== editing?.id)}
          selfId={editing?.id}
          onSubmit={saveMilestone}
          onCancel={() => {
            setCreating(false);
            setEditing(null);
          }}
          busy={busy}
          submitLabel={editing ? `编辑节点「${editing.name}」` : "新建节点"}
        />
      ) : null}

      {milestones.length === 0 ? (
        <EmptyState text="该项目还没有节点。" />
      ) : (
        <table className="table">
          <thead>
            <tr>
              <th>节点</th>
              <th>状态</th>
              <th>开始</th>
              <th>承诺</th>
              <th>执行人</th>
              <th>前置</th>
              <th>缓冲</th>
              <th>操作</th>
            </tr>
          </thead>
          <tbody>
            {milestones.map((m) => {
              const warnings = bufferWarnings(m.buffer);
              return (
                <tr key={m.id} className={m.archived ? "row-archived" : undefined}>
                  <td>
                    <strong>{m.name}</strong>
                    {m.deliverable ? <div className="muted">{m.deliverable}</div> : null}
                    {m.progress ? <div className="muted">进展：{m.progress}</div> : null}
                    {m.blocker_reason ? (
                      <div className="muted">阻塞：{m.blocker_reason}</div>
                    ) : null}
                    {m.contact_person ? (
                      <div className="muted">对接人：{m.contact_person}</div>
                    ) : null}
                    {m.next_followup_date ? (
                      <div className="muted">下次跟进：{m.next_followup_date}</div>
                    ) : null}
                  </td>
                  <td>{milestoneStateLabel(m.state)}</td>
                  <td>{formatDate(m.start_date)}</td>
                  <td>{formatDate(m.commit_date)}</td>
                  <td>{m.assignee_name || "未分派"}</td>
                  <td className="muted">
                    {m.predecessor_ids.length === 0
                      ? "—"
                      : m.predecessor_ids.map((id) => nameOf(id)).join("、")}
                  </td>
                  <td>
                    <div>{describeBuffer(m.buffer)}</div>
                    {warnings.length > 0 ? (
                      <div className="warn">{warnings.join("；")}</div>
                    ) : null}
                  </td>
                  <td className="row-actions">
                    <button
                      type="button"
                      onClick={() => {
                        setCreating(false);
                        setEditing(m);
                        setDraft(draftFrom(m));
                      }}
                    >
                      编辑
                    </button>
                    <button type="button" onClick={() => setRescheduleTarget(m)}>
                      改期
                    </button>
                    {m.archived ? (
                      <span className="muted">已归档</span>
                    ) : (
                      <>
                        <button type="button" onClick={() => archiveMilestone(m)}>
                          归档
                        </button>
                        <button type="button" className="ghost" onClick={() => deleteMilestone(m)}>
                          删除
                        </button>
                      </>
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      )}

      <div className="card">
        <h3>人员（最小选择）</h3>
        <p className="muted">E1 只做执行人选择，不预建周投入/容量。</p>
        <ul className="list">
          {persons.map((p) => (
            <li key={p.id}>
              {p.name}
              {p.roles ? `（${p.roles}）` : ""}
            </li>
          ))}
        </ul>
        <form className="form-grid inline-form" onSubmit={createPerson}>
          <Field label="姓名">
            <input
              required
              value={personName}
              onChange={(e) => setPersonName(e.target.value)}
            />
          </Field>
          <Field label="角色">
            <input
              value={personRoles}
              onChange={(e) => setPersonRoles(e.target.value)}
              placeholder="例如：执行"
            />
          </Field>
          <div className="form-actions">
            <button type="submit" disabled={busy}>
              添加人员
            </button>
          </div>
        </form>
      </div>

      <HistoryPanel entityType="milestone" refreshKey={historyKey} />

      {rescheduleTarget ? (
        <RescheduleDialog
          milestone={rescheduleTarget}
          onClose={() => setRescheduleTarget(null)}
          onApplied={async () => {
            setRescheduleTarget(null);
            setMessage("改期已提交，历史已记录。");
            await load();
            setHistoryKey((k) => k + 1);
          }}
        />
      ) : null}
    </section>
  );
}
