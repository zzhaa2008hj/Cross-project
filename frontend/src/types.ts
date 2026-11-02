export type ProjectState = "active" | "on-hold" | "done" | "maintenance";

export interface BufferInfo {
  status: string;
  window_workdays: number | null;
  buffer_days: number | null;
  internal_target: string | null;
  consumable: boolean;
  reason?: string;
  warnings?: string[];
  start_after_commit?: boolean;
  commit_on_weekend?: boolean;
}

export interface Person {
  id: number;
  name: string;
  roles: string;
  weekly_capacity: number | null;
  note: string;
  archived: boolean;
  source_ref: string | null;
  edited_in_app: boolean;
}

export interface Milestone {
  id: number;
  project_id: number;
  name: string;
  deliverable: string;
  start_date: string | null;
  commit_date: string | null;
  state: string;
  assignee_id: number | null;
  assignee_name: string | null;
  owner_role: string;
  weekly_investment_pct: number | null;
  buffer_source: string | null;
  workday_override: number | null;
  progress: string;
  blocker_reason: string;
  contact_person: string;
  next_followup_date: string | null;
  note: string;
  source_ref: string | null;
  edited_in_app: boolean;
  archived: boolean;
  version: number;
  predecessor_ids: number[];
  buffer: BufferInfo;
}

export interface Project {
  id: number;
  name: string;
  state: ProjectState;
  priority: string;
  current_focus_milestone_id: number | null;
  current_focus_name?: string | null;
  progress: string;
  note: string;
  archived: boolean;
  source_ref: string | null;
  edited_in_app: boolean;
  milestone_count?: number;
  milestones?: Milestone[];
}

export interface HistoryEntry {
  id: number;
  entity_type: string;
  entity_id: number;
  entity_name: string;
  action: string;
  field: string;
  old_value: string;
  new_value: string;
  reason: string;
  actor: string;
  created_at: string;
}

export interface RescheduleChange {
  milestone_id: number;
  name: string;
  state: string;
  old_start_date: string | null;
  old_commit_date: string | null;
  new_start_date: string | null;
  new_commit_date: string | null;
  note: string;
}

export interface ReschedulePreview {
  preview_id: number;
  milestone_id: number;
  milestone_name: string;
  project_id: number;
  mode: string;
  delta_days: number;
  old_start_date: string | null;
  old_commit_date: string | null;
  new_start_date: string | null;
  new_commit_date: string | null;
  changes: RescheduleChange[];
  affected_not_modified: {
    milestone_id: number;
    name: string;
    state: string;
    reason: string;
    commit_date: string | null;
  }[];
  buffer: BufferInfo;
  versions: Record<string, number>;
}

export interface ImportRecord {
  kind: string;
  source_ref: string;
  source_hash: string;
  status: "import" | "skip" | "fail";
  reason: string;
  mapping: Record<string, string>;
  diff: { field: string; old_value: string | null; new_value: string | null }[];
}

export interface ImportReport {
  id: number;
  snapshot_hash: string;
  mode: string;
  read_count: number;
  imported_count: number;
  skipped_count: number;
  failed_count: number;
  applied: boolean;
  sources: { rel: string; sha256: string; bytes: number; lines: number; exists?: boolean }[];
  records: ImportRecord[];
  pending: { ref: string; field: string; raw: string; reason: string }[];
  diffs: { kind?: string; key?: string; field: string; old_value: string | null; new_value: string | null }[];
  reconciliation: Record<string, number | string>;
  report_markdown: string;
  created_at: string;
}

export interface Meta {
  project_states: ProjectState[];
  milestone_states: string[];
  buffer_sources: string[];
  allocation_supported: boolean;
}
