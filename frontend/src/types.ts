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
  skills: string;
  weekly_capacity: number | null;
  monthly_capacity: number;
  note: string;
  archived: boolean;
  source_ref: string | null;
  edited_in_app: boolean;
}

// E2：项目职责。只表达职责，不计入占用。
export interface Assignment {
  id: number;
  person_id: number;
  project_id: number;
  role: string;
  note: string;
  person_name: string | null;
  project_name: string | null;
}

// E2：周投入分配。唯一占用来源，跨页共用同一个稳定 ID。
export interface Allocation {
  id: number;
  person_id: number;
  project_id: number;
  week: string;
  week_end: string | null;
  days: number;
  milestone_id: number | null;
  kind: "milestone" | "project_management";
  note: string;
  person_name: string | null;
  project_name: string | null;
  milestone_name: string | null;
}

export interface MilestoneBrief {
  id: number;
  name: string;
  state: string;
  commit_date: string | null;
  start_date: string | null;
  assignee_id: number | null;
}

// E2：人员某一周的全量视图，人员页与项目页共用。
export interface PersonWeek {
  person_id: number;
  week: string;
  week_end: string;
  capacity: number | null;
  capacity_source: "default" | "override";
  total_days: number;
  over_days: number | null;
  remaining_days: number | null;
  reviewed: boolean;
  allocations: Allocation[];
  assignments: Assignment[];
  unallocated_milestones: MilestoneBrief[];
  status_text: string;
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

// E3：工作台汇总。只读，与人员页共用同一份 Allocation ID。
export interface WorkbenchTodoItem {
  kind: string;
  project_id: number | null;
  project_name: string | null;
  project_state: string | null;
  milestone_id: number | null;
  milestone_name: string | null;
  person_id: number | null;
  person_name: string | null;
  due_date: string | null;
  week_label: string;
  detail: string;
}

export interface WorkbenchMilestone {
  id: number;
  name: string;
  state: string;
  commit_date: string | null;
  start_date: string | null;
  assignee_id: number | null;
  assignee_name: string | null;
  overdue: boolean;
  due_this_week: boolean;
  blocked: boolean;
}

export interface WorkbenchProject {
  id: number;
  name: string;
  state: ProjectState;
  on_hold: boolean;
  priority: string;
  priority_rank: number;
  current_focus_milestone_id: number | null;
  current_focus_name: string | null;
  allocation_days: number;
  overdue_count: number;
  blocked_count: number;
  due_soon_count: number;
  milestones: WorkbenchMilestone[];
}

export interface WorkbenchConflict {
  project_id: number;
  project_name: string | null;
  project_state: string | null;
  days: number;
  allocations: Allocation[];
}

export interface WorkbenchPerson {
  person_id: number;
  name: string;
  capacity: number | null;
  capacity_source: "default" | "override";
  total_days: number;
  over_days: number | null;
  remaining_days: number | null;
  reviewed: boolean;
  status_text: string;
  assignments: Assignment[];
  allocations: Allocation[];
  unallocated_milestones: MilestoneBrief[];
  conflicts: WorkbenchConflict[];
}

export interface Workbench {
  week: string;
  week_end: string;
  today: string;
  projects: WorkbenchProject[];
  maintenance_projects: WorkbenchProject[];
  people: WorkbenchPerson[];
  todos: WorkbenchTodoItem[];
  has_pending: boolean;
}

export interface Meta {
  project_states: ProjectState[];
  milestone_states: string[];
  buffer_sources: string[];
  allocation_supported: boolean;
}

// ---------- 月度口径（人员页） ----------

// Task 2 的 MonthProjectUse，参与项目标签与「本月分配」面板共用
export interface MonthProjectUse {
  project_id: number;
  project_name: string;
  roles: string[];                // 同人同项目可挂多个角色（Assignment 唯一键含 role）
  days: number;                   // 本月在该项目的人天；只有职责、没有分配时为 0
  has_allocation: boolean;
  has_assignment: boolean;
}

// 注意 weekly_capacity 是本 plan 给 spec §6.4 补的列（理由见 Task 3 Step 4 的注释）
export interface MonthPersonRow {
  person_id: number;
  name: string;
  skills: string;
  roles: string;
  note: string;
  monthly_capacity: number;
  weekly_capacity: number | null;   // 周口径，「资料」标签页用
  used_days: number;
  over_days: number | null;
  remaining_days: number | null;
  reviewed: boolean;
  archived: boolean;
  projects: MonthProjectUse[];
}

export interface MonthRoster {
  month: string;                 // "2026-11"
  weeks: string[];               // 该月各周周一，升序
  people: MonthPersonRow[];
}

export interface MonthWeek {
  week: string;
  week_end: string;
  total_days: number;
  reviewed: boolean;
  allocations: Allocation[];
}

export interface MonthPersonDetail {
  person_id: number;
  month: string;
  monthly_capacity: number;
  used_days: number;
  over_days: number | null;
  remaining_days: number | null;
  reviewed: boolean;
  weeks: MonthWeek[];
  assignments: Assignment[];
  projects: MonthProjectUse[];
}
