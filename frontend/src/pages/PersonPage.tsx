import { useCallback, useEffect, useRef, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { api } from "../api";
import { ErrorBanner, Field, Loading, errorMessage } from "../components/common";
import PersonFormDialog from "../components/PersonFormDialog";
import { currentMonth, monthLabel, shiftMonth } from "../month";
import { useMonthParam } from "../useMonthParam";
import type { MonthPersonRow, MonthRoster } from "../types";

/** 弹窗状态：新增没有具体人，编辑带着那一行 roster 数据。 */
type DialogState = { mode: "create" } | { mode: "edit"; person: MonthPersonRow } | null;

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

  useEffect(() => {
    void load();
  }, [load]);

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
      await load();
    } catch (e) {
      setError(errorMessage(e));
    }
  }

  const rows = roster?.people ?? [];

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

      {dialog ? (
        <PersonFormDialog
          person={dialog.mode === "edit" ? dialog.person : null}
          onClose={() => setDialog(null)}
          onSaved={() => {
            setDialog(null);
            void load();
          }}
        />
      ) : null}
    </div>
  );
}
