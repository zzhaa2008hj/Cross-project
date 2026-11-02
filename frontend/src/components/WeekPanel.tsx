import { useCallback, useEffect, useState } from "react";
import { api } from "../api";
import { EmptyState, ErrorBanner, Field, Loading, errorMessage } from "./common";
import type { Allocation, Milestone, PersonWeek, Project } from "../types";

/** 人天：非负、0.5 粒度。非法输入在提交前拦下，保留用户已填内容。 */
export function parseDays(value: string): number | null {
  const text = value.trim();
  if (text === "") return null;
  const days = Number(text);
  if (!Number.isFinite(days) || days < 0) return null;
  if (Math.abs(days * 2 - Math.round(days * 2)) > 1e-9) return null;
  return days;
}

interface WeekPanelProps {
  personId: number;
  /** 周键：周一日期，覆盖周一至周日。 */
  week: string;
  /** 项目页传入：只高亮该项目，不隐藏该人的其他项目冲突。 */
  focusProjectId?: number | null;
  personName?: string | null;
}

/**
 * 人员某一周的完整视图：容量、占用合计、分配明细与核对状态。
 * 人员页与项目页共用本组件与同一个后端汇总接口，因此同一份 Allocation
 * 在两页展示同一个稳定 ID，占用不会被重复计入。
 */
export default function WeekPanel({ personId, week, focusProjectId, personName }: WeekPanelProps) {
  const [view, setView] = useState<PersonWeek | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const [projects, setProjects] = useState<Project[]>([]);
  const [milestones, setMilestones] = useState<Milestone[]>([]);
  const [projectId, setProjectId] = useState<string>("");
  const [milestoneId, setMilestoneId] = useState<string>("");
  const [days, setDays] = useState<string>("");
  const [editDays, setEditDays] = useState<Record<number, string>>({});
  const [capacityInput, setCapacityInput] = useState<string>("");

  const load = useCallback(async () => {
    setError(null);
    try {
      setView(await api.getPersonWeek(personId, week));
    } catch (e) {
      setError(errorMessage(e));
      setView(null);
    } finally {
      setLoading(false);
    }
  }, [personId, week]);

  useEffect(() => {
    setLoading(true);
    void load();
  }, [load]);

  useEffect(() => {
    let cancelled = false;
    api
      .listProjects()
      .then((rows) => {
        if (!cancelled) setProjects(rows);
      })
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, []);

  // 节点只在所选项目内可选；跨项目节点整笔拒绝（后端同样把关）。
  useEffect(() => {
    if (!projectId) {
      setMilestones([]);
      setMilestoneId("");
      return;
    }
    let cancelled = false;
    api
      .listMilestones(Number(projectId))
      .then((rows) => {
        if (!cancelled) {
          setMilestones(rows);
          setMilestoneId("");
        }
      })
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, [projectId]);

  /** 执行一次写操作；失败时保留用户已填内容并展示错误，返回是否成功。 */
  async function run(action: () => Promise<unknown>): Promise<boolean> {
    setError(null);
    setBusy(true);
    try {
      await action();
      await load();
      return true;
    } catch (e) {
      setError(errorMessage(e));
      return false;
    } finally {
      setBusy(false);
    }
  }

  async function submitAllocation() {
    const value = parseDays(days);
    if (value === null) {
      setError("人天必须是非负的 0.5 粒度数字");
      return;
    }
    if (!projectId) {
      setError("请选择项目");
      return;
    }
    const ok = await run(() =>
      api.createAllocation({
        person_id: personId,
        project_id: Number(projectId),
        week,
        days: value,
        milestone_id: milestoneId ? Number(milestoneId) : null,
      }),
    );
    if (!ok) return;
    setDays("");
    setMilestoneId("");
  }

  async function saveRow(row: Allocation) {
    const value = parseDays(editDays[row.id] ?? String(row.days));
    if (value === null) {
      setError("人天必须是非负的 0.5 粒度数字");
      return;
    }
    await run(() => api.updateAllocation(row.id, { days: value }));
  }

  if (loading) return <Loading />;
  if (!view) {
    return (
      <div>
        <ErrorBanner error={error} />
      </div>
    );
  }

  const allocations = view.allocations ?? [];
  const capacityText =
    view.capacity === null ? "容量未知" : `容量 ${view.capacity} 人天`;
  const capacityHint =
    view.capacity_source === "override" ? "指定周覆盖" : "默认周容量";

  return (
    <div className="card">
      <h3>
        {personName ? `${personName} · ` : ""}
        {view.week} ~ {view.week_end}
      </h3>

      <ErrorBanner error={error} />

      <p className="muted">
        {capacityText}（{capacityHint}）
      </p>
      <p className="muted">本周占用 {view.total_days} 人天</p>
      <p className="muted">{view.status_text}</p>

      <div className="form-grid">
        <Field label="指定周容量" hint="留空表示显式未知，不会回退默认容量">
          <input
            aria-label="指定周容量"
            value={capacityInput}
            onChange={(e) => setCapacityInput(e.target.value)}
            placeholder={view.capacity === null ? "未知" : String(view.capacity)}
          />
        </Field>
        <div className="form-actions">
          <button
            type="button"
            disabled={busy}
            onClick={() =>
              void run(() =>
                api.setWeekCapacity(personId, week, parseDays(capacityInput)),
              )
            }
          >
            保存指定周容量
          </button>
          <button
            type="button"
            disabled={busy}
            onClick={() => void run(() => api.clearWeekCapacity(personId, week))}
          >
            删除指定周覆盖
          </button>
          <button
            type="button"
            disabled={busy}
            onClick={() => void run(() => api.setWeekReview(personId, week, !view.reviewed))}
          >
            {view.reviewed ? "取消核对" : "标记本周投入已核对"}
          </button>
        </div>
      </div>

      <h4>本周分配明细</h4>
      {allocations.length === 0 ? (
        <EmptyState text="本周还没有分配" />
      ) : (
        <ul aria-label="分配列表">
          {allocations.map((row) => (
            <li key={row.id}>
              <span>{row.project_name ?? `#${row.project_id}`}</span>
              {" · "}
              <span>{row.milestone_name ?? "整体项目管理"}</span>
              {" · "}
              <span>{row.days} 人天</span>
              {" · "}
              <span className="muted">分配#{row.id}</span>
              {focusProjectId !== undefined && focusProjectId !== null && row.project_id === focusProjectId ? (
                <span className="tag">本项目</span>
              ) : null}
              <input
                aria-label={`分配人天#${row.id}`}
                value={editDays[row.id] ?? String(row.days)}
                onChange={(e) =>
                  setEditDays((prev) => ({ ...prev, [row.id]: e.target.value }))
                }
              />
              <button
                type="button"
                disabled={busy}
                onClick={() => void saveRow(row)}
              >
                {`保存分配#${row.id}`}
              </button>
              <button
                type="button"
                disabled={busy}
                onClick={() => void run(() => api.deleteAllocation(row.id))}
              >
                {`删除分配#${row.id}`}
              </button>
            </li>
          ))}
        </ul>
      )}

      <h4>新增周投入分配</h4>
      <div className="form-grid">
        <Field label="项目">
          <select
            aria-label="新增分配项目"
            value={projectId}
            onChange={(e) => setProjectId(e.target.value)}
            disabled={busy}
          >
            <option value="">请选择</option>
            {projects.map((p) => (
              <option key={p.id} value={String(p.id)}>
                {p.name}
              </option>
            ))}
          </select>
        </Field>
        <Field label="节点" hint="留空表示整体项目管理">
          <select
            aria-label="新增分配节点"
            value={milestoneId}
            onChange={(e) => setMilestoneId(e.target.value)}
            disabled={busy}
          >
            <option value="">整体项目管理</option>
            {milestones.map((m) => (
              <option key={m.id} value={String(m.id)}>
                {m.name}
              </option>
            ))}
          </select>
        </Field>
        <Field label="人天" hint="0.5 粒度">
          <input
            aria-label="新增分配人天"
            value={days}
            onChange={(e) => setDays(e.target.value)}
          />
        </Field>
      </div>
      <div className="form-actions">
        <button type="button" disabled={busy} onClick={() => void submitAllocation()}>
          新增分配
        </button>
      </div>
    </div>
  );
}
