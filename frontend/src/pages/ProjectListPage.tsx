import { useCallback, useEffect, useState } from "react";
import type { FormEvent } from "react";
import { Link } from "react-router-dom";
import { api, ApiError } from "../api";
import { EmptyState, ErrorBanner, Field, Loading } from "../components/common";
import { PROJECT_STATE_LABEL, projectStateLabel } from "../labels";
import type { Project, ProjectState } from "../types";

interface ProjectForm {
  name: string;
  state: ProjectState;
  priority: string;
  progress: string;
  note: string;
}

const EMPTY_FORM: ProjectForm = {
  name: "",
  state: "active",
  priority: "",
  progress: "",
  note: "",
};

export default function ProjectListPage() {
  const [projects, setProjects] = useState<Project[] | null>(null);
  const [includeArchived, setIncludeArchived] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [form, setForm] = useState(EMPTY_FORM);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    setError(null);
    try {
      setProjects(await api.listProjects(includeArchived));
    } catch (e) {
      setError(e instanceof ApiError ? e.detail : String(e));
      setProjects([]);
    }
  }, [includeArchived]);

  useEffect(() => {
    void load();
  }, [load]);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setMessage(null);
    setBusy(true);
    try {
      const created = await api.createProject({
        name: form.name.trim(),
        state: form.state,
        priority: form.priority.trim(),
        progress: form.progress.trim(),
        note: form.note.trim(),
      });
      setMessage(`已创建项目「${created.name}」`);
      setForm(EMPTY_FORM);
      await load();
    } catch (e) {
      setError(e instanceof ApiError ? e.detail : String(e));
    } finally {
      setBusy(false);
    }
  }

  async function toggleArchive(project: Project) {
    setError(null);
    setMessage(null);
    try {
      if (project.archived) {
        await api.restoreProject(project.id);
        setMessage(`已恢复项目「${project.name}」`);
      } else {
        await api.archiveProject(project.id);
        setMessage(`已归档项目「${project.name}」（历史保留）`);
      }
      await load();
    } catch (e) {
      setError(e instanceof ApiError ? e.detail : String(e));
    }
  }

  async function seedDemo() {
    setError(null);
    setMessage(null);
    try {
      const project = await api.seedDemo();
      setMessage(`验收样例已就绪：${project.name}`);
      await load();
    } catch (e) {
      setError(e instanceof ApiError ? e.detail : String(e));
    }
  }

  return (
    <section>
      <div className="page-head">
        <h1>项目</h1>
        <div className="page-actions">
          <label className="inline-check">
            <input
              type="checkbox"
              checked={includeArchived}
              onChange={(e) => setIncludeArchived(e.target.checked)}
            />
            显示已归档
          </label>
          <button type="button" onClick={seedDemo}>
            建立验收样例
          </button>
        </div>
      </div>

      <ErrorBanner error={error} />
      {message ? <p className="banner banner-ok">{message}</p> : null}

      <form className="card form-grid" onSubmit={submit}>
        <Field label="项目名称">
          <input
            required
            value={form.name}
            onChange={(e) => setForm({ ...form, name: e.target.value })}
            placeholder="例如：北京仓储项目"
          />
        </Field>
        <Field label="状态">
          <select
            value={form.state}
            onChange={(e) => setForm({ ...form, state: e.target.value as ProjectState })}
          >
            {Object.entries(PROJECT_STATE_LABEL).map(([value, label]) => (
              <option key={value} value={value}>
                {label}
              </option>
            ))}
          </select>
        </Field>
        <Field label="优先级" hint="例如 P0 / P1">
          <input
            value={form.priority}
            onChange={(e) => setForm({ ...form, priority: e.target.value })}
          />
        </Field>
        <Field label="进展">
          <input
            value={form.progress}
            onChange={(e) => setForm({ ...form, progress: e.target.value })}
          />
        </Field>
        <Field label="备注">
          <input
            value={form.note}
            onChange={(e) => setForm({ ...form, note: e.target.value })}
          />
        </Field>
        <div className="form-actions">
          <button type="submit" disabled={busy}>
            新建项目
          </button>
        </div>
      </form>

      {projects === null ? (
        <Loading />
      ) : projects.length === 0 ? (
        <EmptyState text="暂无项目，请先新建或建立验收样例。" />
      ) : (
        <table className="table">
          <thead>
            <tr>
              <th>项目</th>
              <th>状态</th>
              <th>优先级</th>
              <th>当前重点</th>
              <th>进展</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {projects.map((p) => (
              <tr key={p.id} className={p.archived ? "row-archived" : undefined}>
                <td>
                  <Link to={`/projects/${p.id}`}>{p.name}</Link>
                  {p.archived ? <span className="tag">已归档</span> : null}
                </td>
                <td>{projectStateLabel(p.state)}</td>
                <td>{p.priority || "—"}</td>
                <td>{p.current_focus_name || "—"}</td>
                <td className="cell-progress">{p.progress || "—"}</td>
                <td>
                  <button type="button" onClick={() => toggleArchive(p)}>
                    {p.archived ? "恢复" : "归档"}
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </section>
  );
}
