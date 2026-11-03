import { useState } from "react";
import { api } from "../api";
import { ErrorBanner, Field, errorMessage } from "./common";
import { parseDays } from "./WeekPanel";
import type { MonthPersonRow } from "../types";

interface PersonFormDialogProps {
  /** null 表示新增；有值表示编辑（只有 roster 行能拿到人，不带 id/source_ref 等字段）。 */
  person: MonthPersonRow | null;
  onClose: () => void;
  onSaved: () => void;
}

interface FormState {
  name: string;
  capacity: string;
  skills: string;
  roles: string;
  note: string;
}

/** 核定人天的表单初值：新增默认 30，编辑带出该人的核定人天。 */
const DEFAULT_CAPACITY = "30";

function initialForm(person: MonthPersonRow | null): FormState {
  return {
    name: person?.name ?? "",
    capacity: person ? String(person.monthly_capacity) : DEFAULT_CAPACITY,
    skills: person?.skills ?? "",
    roles: person?.roles ?? "",
    note: person?.note ?? "",
  };
}

/**
 * 新增 / 修改人员弹窗：姓名、核定人天、能力标签、角色标签、备注。
 * 「默认周容量」是周口径字段，只在详情区的「资料」标签页编辑，这里不放。
 */
export default function PersonFormDialog({ person, onClose, onSaved }: PersonFormDialogProps) {
  const [form, setForm] = useState<FormState>(() => initialForm(person));
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const title = person ? `编辑 · ${person.name}` : "新增人员";

  async function save() {
    const name = form.name.trim();
    if (!name) {
      setError("请填写姓名");
      return;
    }
    // 核定人天：非负、0.5 粒度，非法值就地拦下，不发请求。
    const capacity = parseDays(form.capacity);
    if (capacity === null) {
      setError("核定人天必须是非负的 0.5 粒度数字");
      return;
    }
    setError(null);
    setBusy(true);
    try {
      const payload = {
        name,
        monthly_capacity: capacity,
        skills: form.skills.trim(),
        roles: form.roles.trim(),
        note: form.note.trim(),
      };
      if (person) {
        await api.updatePerson(person.person_id, payload);
      } else {
        await api.createPerson(payload);
      }
      onSaved();
    } catch (e) {
      // 失败时保留已填内容，方便用户改完重试。
      setError(errorMessage(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="modal-backdrop" role="dialog" aria-modal="true" aria-label={title}>
      <div className="modal">
        <div className="modal-head">
          <h2>{title}</h2>
          <button type="button" className="ghost" onClick={onClose}>
            关闭
          </button>
        </div>

        <ErrorBanner error={error} />

        <div className="form-grid">
          <Field label="姓名">
            <input
              aria-label="姓名"
              value={form.name}
              onChange={(e) => setForm({ ...form, name: e.target.value })}
            />
          </Field>
          <Field label="核定人天" hint="默认 30，0.5 粒度">
            <input
              type="number"
              step="0.5"
              aria-label="核定人天"
              value={form.capacity}
              onChange={(e) => setForm({ ...form, capacity: e.target.value })}
            />
          </Field>
          <Field label="能力标签">
            <input
              aria-label="能力标签"
              value={form.skills}
              onChange={(e) => setForm({ ...form, skills: e.target.value })}
            />
          </Field>
          <Field label="角色标签">
            <input
              aria-label="角色标签"
              value={form.roles}
              onChange={(e) => setForm({ ...form, roles: e.target.value })}
            />
          </Field>
          <Field label="备注">
            <textarea
              aria-label="备注"
              rows={3}
              value={form.note}
              onChange={(e) => setForm({ ...form, note: e.target.value })}
            />
          </Field>
        </div>

        <div className="form-actions">
          <button type="button" disabled={busy} onClick={() => void save()}>
            保存
          </button>
          <button type="button" className="ghost" onClick={onClose}>
            取消
          </button>
        </div>
      </div>
    </div>
  );
}
