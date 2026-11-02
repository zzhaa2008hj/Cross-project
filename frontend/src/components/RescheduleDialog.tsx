import { useState } from "react";
import { api, ApiError } from "../api";
import { ErrorBanner, Field } from "./common";
import { describeBuffer, formatDate, isTerminal, milestoneStateLabel } from "../labels";
import type { Milestone, ReschedulePreview } from "../types";

export default function RescheduleDialog({
  milestone,
  onClose,
  onApplied,
}: {
  milestone: Milestone;
  onClose: () => void;
  onApplied: () => void;
}) {
  const [newCommit, setNewCommit] = useState("");
  const [newStart, setNewStart] = useState("");
  const [mode, setMode] = useState<"current" | "cascade">("current");
  const [reason, setReason] = useState("");
  const [preview, setPreview] = useState<ReschedulePreview | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function doPreview() {
    setError(null);
    setBusy(true);
    try {
      const p = await api.previewReschedule({
        milestone_id: milestone.id,
        new_commit_date: newCommit || null,
        new_start_date: newStart || null,
        mode,
      });
      setPreview(p);
    } catch (e) {
      setPreview(null);
      setError(e instanceof ApiError ? e.detail : String(e));
    } finally {
      setBusy(false);
    }
  }

  async function doApply() {
    setError(null);
    if (!preview) return;
    setBusy(true);
    try {
      // 用预览时的模式提交，避免用户在预览后切换联动范围造成模式不一致
      await api.applyReschedule({
        preview_id: preview.preview_id,
        reason: reason.trim(),
        mode: preview.mode as "current" | "cascade",
      });
      onApplied();
    } catch (e) {
      setError(e instanceof ApiError ? e.detail : String(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="modal-backdrop" role="dialog" aria-modal="true" aria-label="改期预览">
      <div className="modal">
        <div className="modal-head">
          <h2>改期预览 · {milestone.name}</h2>
          <button type="button" className="ghost" onClick={onClose}>
            关闭
          </button>
        </div>

        <ErrorBanner error={error} />

        <div className="form-grid">
          <Field label="新承诺日" hint="留空表示只改开始日">
            <input
              type="date"
              value={newCommit}
              onChange={(e) => {
                setNewCommit(e.target.value);
                setPreview(null); // 日期变化后旧预览失效，需重新生成
              }}
            />
          </Field>
          <Field label="新开始日" hint="留空则按日历日差同步平移">
            <input
              type="date"
              value={newStart}
              onChange={(e) => {
                setNewStart(e.target.value);
                setPreview(null); // 日期变化后旧预览失效，需重新生成
              }}
            />
          </Field>
          <Field label="联动范围">
            <select
              value={mode}
              onChange={(e) => {
                setMode(e.target.value as "current" | "cascade");
                setPreview(null); // 联动范围变化后旧预览失效，需重新生成
              }}
            >
              <option value="current">仅当前节点</option>
              <option value="cascade">联动传递后继</option>
            </select>
          </Field>
        </div>

        <div className="form-actions">
          <button type="button" onClick={doPreview} disabled={busy}>
            {busy && !preview ? "预览中…" : "生成预览"}
          </button>
        </div>

        {preview ? (
          <div className="preview">
            <p className="muted">
              预览记录版本：{" "}
              {Object.entries(preview.versions ?? {})
                .map(([id, v]) => `#${id} v${v}`)
                .join("、")}{" "}
              · 缓冲：{describeBuffer(preview.buffer)}
            </p>
            <table className="table">
              <thead>
                <tr>
                  <th>节点</th>
                  <th>状态</th>
                  <th>原开始</th>
                  <th>新开始</th>
                  <th>原承诺</th>
                  <th>新承诺</th>
                  <th>说明</th>
                </tr>
              </thead>
              <tbody>
                {preview.changes.map((c) => (
                  <tr key={c.milestone_id}>
                    <td>{c.name}</td>
                    <td>{milestoneStateLabel(c.state)}</td>
                    <td>{formatDate(c.old_start_date)}</td>
                    <td>{formatDate(c.new_start_date)}</td>
                    <td>{formatDate(c.old_commit_date)}</td>
                    <td>{formatDate(c.new_commit_date)}</td>
                    <td className="muted">{c.note || "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>

            {preview.affected_not_modified.length > 0 ? (
              <>
                <h4>受影响但不改动的记录</h4>
                <ul className="list">
                  {preview.affected_not_modified.map((a) => (
                    <li key={a.milestone_id}>
                      {a.name}（{milestoneStateLabel(a.state)}）：{a.reason}
                      {isTerminal(a.state) ? "" : ""}
                    </li>
                  ))}
                </ul>
              </>
            ) : null}

            <Field label="改期原因" hint="必填，会写入历史记录">
              <textarea
                rows={2}
                value={reason}
                onChange={(e) => setReason(e.target.value)}
                placeholder="例如：上游资料延迟，承诺日顺延 3 天"
              />
            </Field>
            <div className="form-actions">
              <button type="button" onClick={doApply} disabled={busy}>
                {busy ? "提交中…" : "确认改期"}
              </button>
              <span className="muted">提交前会校验记录版本，版本已变则整笔拒绝。</span>
            </div>
          </div>
        ) : null}
      </div>
    </div>
  );
}
