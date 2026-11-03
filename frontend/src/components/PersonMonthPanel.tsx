import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "../api";
import { ErrorBanner, Field, Loading, errorMessage } from "./common";
import { parseDays } from "./WeekPanel";
import { weekEnd } from "../week";
import type { Allocation, Milestone, MonthPersonDetail, MonthWeek, Project } from "../types";

interface PersonMonthPanelProps {
  personId: number;
  /** 月份："YYYY-MM"。 */
  month: string;
  /** 已禁用的人不能新增分配，但已有分配照改照删。 */
  archived: boolean;
  /** 写操作成功后通知宿主刷新自己的数据。 */
  onChanged: () => void;
}

/**
 * 人员某个月按周看分配：每周一块，块内列出该周的分配明细。
 * 面板只回答「这周派到哪些项目、各多少人天、核对没有」，
 * 容量与剩余是周口径的概念，不在这里出现。
 */
export default function PersonMonthPanel({
  personId,
  month,
  archived,
  onChanged,
}: PersonMonthPanelProps) {
  const [detail, setDetail] = useState<MonthPersonDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const [projects, setProjects] = useState<Project[]>([]);
  // 内联新增表单只在被点的那块周里渲染，所以全局只记一个打开的周。
  const [newWeek, setNewWeek] = useState<string | null>(null);
  const [newProjectId, setNewProjectId] = useState("");
  const [newMilestoneId, setNewMilestoneId] = useState("");
  const [newDays, setNewDays] = useState("");
  // 节点按周存：换周重开表单时不会串上另一周选中的节点。
  const [milestonesByWeek, setMilestonesByWeek] = useState<Record<string, Milestone[]>>({});

  const [editingId, setEditingId] = useState<number | null>(null);
  const [editDays, setEditDays] = useState("");

  // 请求序号：只有最后一次请求的结果才允许渲染，避免旧响应覆盖新月份的数据。
  const requestSeq = useRef(0);

  // 节点列表的请求序号：按周各记各的（不与上面的 requestSeq 混用）。
  const milestoneSeq = useRef<Record<string, number>>({});

  const load = useCallback(async () => {
    const seq = ++requestSeq.current;
    setError(null);
    try {
      const next = await api.getPersonMonth(personId, month);
      if (seq !== requestSeq.current) return; // 过期响应，丢弃
      setDetail(next);
    } catch (e) {
      if (seq !== requestSeq.current) return; // 过期响应，丢弃
      setError(errorMessage(e));
      setDetail(null);
    } finally {
      if (seq === requestSeq.current) setLoading(false);
    }
  }, [personId, month]);

  // 始终指向最新的 load：load 依赖 [personId, month]，换月/换人会重建。
  // 写操作完成后重拉必须用最新的一份，否则会拉回点击那一刻的旧月份数据。
  const loadRef = useRef(load);
  loadRef.current = load;

  useEffect(() => {
    setLoading(true);
    void load();
  }, [load]);

  // 项目下拉只在新表单里用；拿不到项目列表不影响面板主体。
  useEffect(() => {
    let cancelled = false;
    void (async () => {
      try {
        const rows = (await api.listProjects()) ?? [];
        if (!cancelled) setProjects(rows);
      } catch {
        // 忽略：项目列表为空时新增表单里选不了项目。
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  /** 写操作：成功后刷新本面板并通知宿主刷新自己的数据。 */
  async function run(action: () => Promise<unknown>): Promise<boolean> {
    setError(null);
    setBusy(true);
    try {
      await action();
      await loadRef.current();
      onChanged();
      return true;
    } catch (e) {
      setError(errorMessage(e));
      return false;
    } finally {
      setBusy(false);
    }
  }

  async function toggleReview(week: MonthWeek, reviewed: boolean) {
    await run(() => api.setWeekReview(personId, week.week, reviewed));
  }

  function startEdit(row: Allocation) {
    setEditingId(row.id);
    setEditDays(String(row.days));
  }

  async function saveEdit(row: Allocation) {
    const value = parseDays(editDays);
    if (value === null) {
      setError("人天必须是非负的 0.5 粒度数字");
      return;
    }
    const ok = await run(() => api.updateAllocation(row.id, { days: value }));
    if (!ok) return;
    setEditingId(null);
    setEditDays("");
  }

  async function removeAllocation(row: Allocation) {
    await run(() => api.deleteAllocation(row.id));
  }

  /** 打开/收起某一周的新增分配表单。 */
  function toggleNewForm(week: string) {
    if (newWeek === week) {
      setNewWeek(null);
      return;
    }
    setNewWeek(week);
    setNewProjectId("");
    setNewMilestoneId("");
    setNewDays("");
    // 重新打开时节点要跟着项目重新选：清掉上一轮残留的节点，
    // 否则「A 项目的节点 + B 项目」会被后端判成跨项目而 422。
    setMilestonesByWeek((prev) => ({ ...prev, [week]: [] }));
  }

  /** 选项目后拉该项目的节点；保存不依赖节点是否加载完，不选节点就是整体项目管理。 */
  async function onProjectChange(week: string, value: string) {
    // 序号在函数开头自增：清空项目的早退分支也要自增，
    // 否则在飞的旧请求会把上一个项目的节点写回来。
    const seq = (milestoneSeq.current[week] ?? 0) + 1;
    milestoneSeq.current[week] = seq;
    setNewProjectId(value);
    setNewMilestoneId("");
    if (!value) {
      setMilestonesByWeek((prev) => ({ ...prev, [week]: [] }));
      return;
    }
    try {
      const rows = (await api.listMilestones(Number(value))) ?? [];
      // 不是最后一次选择就丢弃（?? [] 的兜底保留）
      if (milestoneSeq.current[week] !== seq) return;
      setMilestonesByWeek((prev) => ({ ...prev, [week]: rows }));
    } catch {
      // 旧请求失败也不许清掉新项目的节点
      if (milestoneSeq.current[week] !== seq) return;
      setMilestonesByWeek((prev) => ({ ...prev, [week]: [] }));
    }
  }

  async function submitNew(week: string) {
    if (!newProjectId) {
      setError("请选择项目");
      return;
    }
    const value = parseDays(newDays);
    if (value === null) {
      setError("人天必须是非负的 0.5 粒度数字");
      return;
    }
    const ok = await run(() =>
      api.createAllocation({
        person_id: personId,
        project_id: Number(newProjectId),
        week,
        days: value,
        milestone_id: newMilestoneId ? Number(newMilestoneId) : null,
      }),
    );
    if (!ok) return;
    setNewWeek(null);
    setNewProjectId("");
    setNewMilestoneId("");
    setNewDays("");
  }

  if (loading) return <Loading />;
  if (!detail) {
    return (
      <div>
        <ErrorBanner error={error} />
      </div>
    );
  }

  const weeks = detail.weeks ?? [];

  return (
    <div>
      <ErrorBanner error={error} />

      {weeks.map((week) => (
        <div className="month-week-block" data-testid={`week-${week.week}`} key={week.week}>
          <div className="week-head">{week.week.slice(5)} ~ {weekEnd(week.week).slice(5)}</div>

          <div className="row">
            <span className="muted">{week.reviewed ? "已核对" : "待核对"}</span>
            <label className="inline-check">
              <input
                type="checkbox"
                checked={week.reviewed}
                disabled={busy}
                onChange={(e) => void toggleReview(week, e.target.checked)}
              />
              核对
            </label>
          </div>

          {week.allocations.length === 0 ? (
            <p className="muted empty">本周还没有分配</p>
          ) : (
            <table className="table">
              <thead>
                <tr>
                  <th>项目</th>
                  <th>人天</th>
                  <th>操作</th>
                </tr>
              </thead>
              <tbody>
                {week.allocations.map((row) => (
                  <tr data-testid={`alloc-${row.id}`} key={row.id}>
                    <td>
                      {row.project_name ?? `#${row.project_id}`}
                      {row.milestone_name ? ` · ${row.milestone_name}` : null}
                    </td>
                    <td>
                      {editingId === row.id ? (
                        <Field label="人天">
                          <input
                            aria-label="改人天"
                            value={editDays}
                            disabled={busy}
                            onChange={(e) => setEditDays(e.target.value)}
                          />
                        </Field>
                      ) : (
                        `${row.days} 人天`
                      )}
                    </td>
                    <td>
                      <div className="row-actions">
                        {editingId === row.id ? (
                          <>
                            <button type="button" disabled={busy} onClick={() => void saveEdit(row)}>
                              保存
                            </button>
                            <button type="button" onClick={() => setEditingId(null)}>
                              取消
                            </button>
                          </>
                        ) : (
                          <>
                            <button type="button" disabled={busy} onClick={() => startEdit(row)}>
                              修改
                            </button>
                            <button type="button" disabled={busy} onClick={() => void removeAllocation(row)}>
                              删除
                            </button>
                          </>
                        )}
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}

          {newWeek === week.week ? (
            <div className="inline-form">
              <div className="form-grid">
                <Field label="项目">
                  <select
                    aria-label="新增分配项目"
                    value={newProjectId}
                    disabled={busy}
                    onChange={(e) => void onProjectChange(week.week, e.target.value)}
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
                    value={newMilestoneId}
                    disabled={busy}
                    onChange={(e) => setNewMilestoneId(e.target.value)}
                  >
                    <option value="">整体项目管理</option>
                    {(milestonesByWeek[week.week] ?? []).map((m) => (
                      <option key={m.id} value={String(m.id)}>
                        {m.name}
                      </option>
                    ))}
                  </select>
                </Field>
                <Field label="人天" hint="0.5 粒度">
                  <input
                    aria-label="新增分配人天"
                    value={newDays}
                    disabled={busy}
                    onChange={(e) => setNewDays(e.target.value)}
                  />
                </Field>
              </div>
              <div className="form-actions">
                <button type="button" disabled={busy} onClick={() => void submitNew(week.week)}>
                  保存
                </button>
              </div>
            </div>
          ) : null}

          <div className="row-actions">
            <button
              type="button"
              disabled={archived || busy}
              aria-expanded={newWeek === week.week}
              onClick={() => toggleNewForm(week.week)}
            >
              + 新增分配
            </button>
            {archived ? <span className="muted">已禁用，不可新增分配</span> : null}
          </div>
        </div>
      ))}
    </div>
  );
}
