import { useEffect, useState } from "react";
import { Field } from "./common";
import { MILESTONE_STATE_LABEL } from "../labels";
import type { Milestone, Person } from "../types";

export interface MilestoneDraft {
  name: string;
  deliverable: string;
  state: string;
  start_date: string;
  commit_date: string;
  assignee_id: string;
  owner_role: string;
  buffer_source: string;
  progress: string;
  blocker_reason: string;
  contact_person: string;
  next_followup_date: string;
  note: string;
  predecessor_ids: number[];
}

export function emptyDraft(): MilestoneDraft {
  return {
    name: "",
    deliverable: "",
    state: "未开始",
    start_date: "",
    commit_date: "",
    assignee_id: "",
    owner_role: "",
    buffer_source: "内部",
    progress: "",
    blocker_reason: "",
    contact_person: "",
    next_followup_date: "",
    note: "",
    predecessor_ids: [],
  };
}

export function draftFrom(m: Milestone): MilestoneDraft {
  return {
    name: m.name,
    deliverable: m.deliverable,
    state: m.state,
    start_date: m.start_date ?? "",
    commit_date: m.commit_date ?? "",
    assignee_id: m.assignee_id === null ? "" : String(m.assignee_id),
    owner_role: m.owner_role,
    buffer_source: m.buffer_source ?? "内部",
    progress: m.progress,
    blocker_reason: m.blocker_reason,
    contact_person: m.contact_person,
    next_followup_date: m.next_followup_date ?? "",
    note: m.note,
    predecessor_ids: [...m.predecessor_ids],
  };
}

export function draftToPayload(d: MilestoneDraft) {
  return {
    name: d.name.trim(),
    deliverable: d.deliverable.trim(),
    state: d.state,
    start_date: d.start_date || null,
    commit_date: d.commit_date || null,
    assignee_id: d.assignee_id ? Number(d.assignee_id) : null,
    owner_role: d.owner_role.trim(),
    buffer_source: d.buffer_source || null,
    progress: d.progress.trim(),
    blocker_reason: d.blocker_reason.trim(),
    contact_person: d.contact_person.trim(),
    next_followup_date: d.next_followup_date || null,
    note: d.note.trim(),
    predecessor_ids: d.predecessor_ids,
  };
}

export default function MilestoneForm({
  draft,
  setDraft,
  persons,
  siblings,
  selfId,
  onSubmit,
  onCancel,
  busy,
  submitLabel,
}: {
  draft: MilestoneDraft;
  setDraft: (d: MilestoneDraft) => void;
  persons: Person[];
  siblings: Milestone[];
  selfId?: number;
  onSubmit: () => void;
  onCancel: () => void;
  busy: boolean;
  submitLabel: string;
}) {
  const [showAll, setShowAll] = useState(false);

  useEffect(() => {
    setShowAll(false);
  }, [draft.name]);

  const set = <K extends keyof MilestoneDraft>(key: K, value: MilestoneDraft[K]) =>
    setDraft({ ...draft, [key]: value });

  const visible = showAll ? siblings : siblings.slice(0, 8);

  return (
    <form
      className="card"
      onSubmit={(e) => {
        e.preventDefault();
        onSubmit();
      }}
    >
      <h3>{submitLabel}</h3>
      <div className="form-grid">
        <Field label="节点名称">
          <input
            required
            value={draft.name}
            onChange={(e) => set("name", e.target.value)}
          />
        </Field>
        <Field label="状态">
          <select value={draft.state} onChange={(e) => set("state", e.target.value)}>
            {Object.entries(MILESTONE_STATE_LABEL).map(([value, label]) => (
              <option key={value} value={value}>
                {label}
              </option>
            ))}
          </select>
        </Field>
        <Field label="交付物">
          <input
            value={draft.deliverable}
            onChange={(e) => set("deliverable", e.target.value)}
          />
        </Field>
        <Field label="开始日">
          <input
            type="date"
            value={draft.start_date}
            onChange={(e) => set("start_date", e.target.value)}
          />
        </Field>
        <Field label="承诺日">
          <input
            type="date"
            value={draft.commit_date}
            onChange={(e) => set("commit_date", e.target.value)}
          />
        </Field>
        <Field label="执行人" hint="只选执行人，不预建周投入">
          <select
            value={draft.assignee_id}
            onChange={(e) => set("assignee_id", e.target.value)}
          >
            <option value="">未分派</option>
            {persons.map((p) => (
              <option key={p.id} value={p.id}>
                {p.name}
                {p.roles ? `（${p.roles}）` : ""}
              </option>
            ))}
          </select>
        </Field>
        <Field label="负责人角色">
          <input
            value={draft.owner_role}
            onChange={(e) => set("owner_role", e.target.value)}
            placeholder="例如：产品负责人"
          />
        </Field>
        <Field label="缓冲来源">
          <select
            value={draft.buffer_source}
            onChange={(e) => set("buffer_source", e.target.value)}
          >
            <option value="">未设置</option>
            <option value="内部">内部</option>
            <option value="外部资源">外部资源</option>
            <option value="外部阻塞">外部阻塞</option>
          </select>
        </Field>
        <Field label="进展">
          <input value={draft.progress} onChange={(e) => set("progress", e.target.value)} />
        </Field>
        <Field label="阻塞原因">
          <input
            value={draft.blocker_reason}
            onChange={(e) => set("blocker_reason", e.target.value)}
          />
        </Field>
        <Field label="对接人">
          <input
            value={draft.contact_person}
            onChange={(e) => set("contact_person", e.target.value)}
          />
        </Field>
        <Field label="下次跟进日">
          <input
            type="date"
            value={draft.next_followup_date}
            onChange={(e) => set("next_followup_date", e.target.value)}
          />
        </Field>
        <Field label="备注">
          <input value={draft.note} onChange={(e) => set("note", e.target.value)} />
        </Field>
      </div>

      <fieldset className="fieldset">
        <legend>前置依赖（同项目内）</legend>
        {siblings.length === 0 ? (
          <p className="muted">暂无其它节点。</p>
        ) : (
          <div className="checkbox-list">
            {visible.map((m) => (
              <label key={m.id} className="inline-check">
                <input
                  type="checkbox"
                  disabled={selfId !== undefined && m.id === selfId}
                  checked={draft.predecessor_ids.includes(m.id)}
                  onChange={(e) =>
                    set(
                      "predecessor_ids",
                      e.target.checked
                        ? [...draft.predecessor_ids, m.id]
                        : draft.predecessor_ids.filter((id) => id !== m.id),
                    )
                  }
                />
                {m.name}
              </label>
            ))}
            {siblings.length > 8 ? (
              <button type="button" className="link" onClick={() => setShowAll(!showAll)}>
                {showAll ? "收起" : `展开全部 ${siblings.length} 个节点`}
              </button>
            ) : null}
          </div>
        )}
      </fieldset>

      <div className="form-actions">
        <button type="submit" disabled={busy}>
          {busy ? "保存中…" : "保存"}
        </button>
        <button type="button" className="ghost" onClick={onCancel}>
          取消
        </button>
      </div>
    </form>
  );
}
