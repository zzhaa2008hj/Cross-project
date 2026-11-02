import { useEffect, useState } from "react";
import { api, ApiError } from "../api";
import { EmptyState, ErrorBanner, Loading } from "./common";
import type { HistoryEntry } from "../types";

export default function HistoryPanel({
  entityType,
  entityId,
  refreshKey,
}: {
  entityType?: string;
  entityId?: number;
  refreshKey: number;
}) {
  const [entries, setEntries] = useState<HistoryEntry[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    setError(null);
    api
      .history({ entity_type: entityType, entity_id: entityId })
      .then((rows) => {
        if (alive) setEntries(rows);
      })
      .catch((e) => {
        if (alive) {
          setError(e instanceof ApiError ? e.detail : String(e));
          setEntries([]);
        }
      });
    return () => {
      alive = false;
    };
  }, [entityType, entityId, refreshKey]);

  return (
    <div className="card">
      <h3>历史记录</h3>
      <ErrorBanner error={error} />
      {entries === null ? (
        <Loading />
      ) : entries.length === 0 ? (
        <EmptyState text="暂无历史记录。" />
      ) : (
        <table className="table">
          <thead>
            <tr>
              <th>对象</th>
              <th>动作</th>
              <th>字段</th>
              <th>原值</th>
              <th>新值</th>
              <th>原因</th>
              <th>时间</th>
            </tr>
          </thead>
          <tbody>
            {entries.map((h) => (
              <tr key={h.id}>
                <td>{h.entity_name}</td>
                <td>{h.action}</td>
                <td>{h.field || "—"}</td>
                <td className="cell-old">{h.old_value || "—"}</td>
                <td className="cell-new">{h.new_value || "—"}</td>
                <td className="muted">{h.reason || "—"}</td>
                <td className="muted">{h.created_at?.slice(0, 19).replace("T", " ")}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
