import type {
  Allocation,
  Assignment,
  HistoryEntry,
  ImportReport,
  Meta,
  Milestone,
  Person,
  PersonWeek,
  Project,
  ReschedulePreview,
  Workbench,
} from "./types";

const BASE = "/api";

export class ApiError extends Error {
  status: number;
  detail: string;
  constructor(status: number, detail: string) {
    super(detail);
    this.status = status;
    this.detail = detail;
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...init,
  });
  const text = await res.text();
  const body = text ? JSON.parse(text) : null;
  if (!res.ok) {
    let detail = `请求失败（HTTP ${res.status}）`;
    if (body && typeof body === "object" && "detail" in body) {
      const d = (body as { detail: unknown }).detail;
      if (typeof d === "string") {
        detail = d;
      } else if (d && typeof d === "object" && "message" in d) {
        // 改期等接口返回 {message, ...} 结构
        detail = String((d as { message: unknown }).message);
      } else {
        detail = JSON.stringify(d);
      }
    }
    throw new ApiError(res.status, detail);
  }
  return body as T;
}

const body = (payload: unknown) => JSON.stringify(payload);

export const api = {
  meta: () => request<Meta>("/meta"),
  health: () => request<{ status: string }>("/health"),

  listProjects: (includeArchived = false) =>
    request<Project[]>(`/projects?include_archived=${includeArchived}`),
  getProject: (id: number) => request<Project>(`/projects/${id}`),
  createProject: (payload: Partial<Project>) =>
    request<Project>("/projects", { method: "POST", body: body(payload) }),
  updateProject: (id: number, payload: Partial<Project>) =>
    request<Project>(`/projects/${id}`, { method: "PATCH", body: body(payload) }),
  archiveProject: (id: number) =>
    request<Project>(`/projects/${id}/archive`, { method: "POST" }),
  restoreProject: (id: number) =>
    request<Project>(`/projects/${id}/restore`, { method: "POST" }),

  listMilestones: (projectId: number) =>
    request<Milestone[]>(`/projects/${projectId}/milestones`),
  createMilestone: (projectId: number, payload: Partial<Milestone>) =>
    request<Milestone>(`/projects/${projectId}/milestones`, {
      method: "POST",
      body: body(payload),
    }),
  getMilestone: (id: number) => request<Milestone>(`/milestones/${id}`),
  updateMilestone: (id: number, payload: Partial<Milestone>) =>
    request<Milestone>(`/milestones/${id}`, { method: "PATCH", body: body(payload) }),
  archiveMilestone: (id: number) =>
    request<Milestone>(`/milestones/${id}/archive`, { method: "POST" }),
  deleteMilestone: (id: number) =>
    request<{ deleted: boolean }>(`/milestones/${id}`, { method: "DELETE" }),

  listPersons: () => request<Person[]>("/persons"),
  createPerson: (payload: Partial<Person>) =>
    request<Person>("/persons", { method: "POST", body: body(payload) }),
  updatePerson: (id: number, payload: Partial<Person>) =>
    request<Person>(`/persons/${id}`, { method: "PATCH", body: body(payload) }),
  archivePerson: (id: number) =>
    request<Person>(`/persons/${id}/archive`, { method: "POST" }),
  restorePerson: (id: number) =>
    request<Person>(`/persons/${id}/restore`, { method: "POST" }),

  // E2：职责（不计占用）
  listAssignments: (params: { person_id?: number; project_id?: number } = {}) => {
    const q = new URLSearchParams();
    if (params.person_id !== undefined) q.set("person_id", String(params.person_id));
    if (params.project_id !== undefined) q.set("project_id", String(params.project_id));
    const qs = q.toString();
    return request<Assignment[]>(`/assignments${qs ? `?${qs}` : ""}`);
  },
  createAssignment: (payload: {
    person_id: number;
    project_id: number;
    role: string;
    note?: string;
  }) => request<Assignment>("/assignments", { method: "POST", body: body(payload) }),
  updateAssignment: (id: number, payload: { role?: string; note?: string }) =>
    request<Assignment>(`/assignments/${id}`, { method: "PATCH", body: body(payload) }),
  deleteAssignment: (id: number) =>
    request<{ deleted: boolean }>(`/assignments/${id}`, { method: "DELETE" }),

  // E2：周投入分配（唯一占用来源）
  listAllocations: (
    params: { person_id?: number; project_id?: number; week?: string } = {},
  ) => {
    const q = new URLSearchParams();
    if (params.person_id !== undefined) q.set("person_id", String(params.person_id));
    if (params.project_id !== undefined) q.set("project_id", String(params.project_id));
    if (params.week !== undefined) q.set("week", params.week);
    const qs = q.toString();
    return request<Allocation[]>(`/allocations${qs ? `?${qs}` : ""}`);
  },
  createAllocation: (payload: {
    person_id: number;
    project_id: number;
    week: string;
    days: number;
    milestone_id?: number | null;
    kind?: string;
    note?: string;
  }) => request<Allocation>("/allocations", { method: "POST", body: body(payload) }),
  updateAllocation: (
    id: number,
    payload: {
      person_id?: number;
      project_id?: number;
      week?: string;
      days?: number;
      milestone_id?: number | null;
      kind?: string;
      note?: string;
    },
  ) => request<Allocation>(`/allocations/${id}`, { method: "PATCH", body: body(payload) }),
  deleteAllocation: (id: number) =>
    request<{ deleted: boolean }>(`/allocations/${id}`, { method: "DELETE" }),

  // E2：人员周视图、容量覆盖与显式核对
  getPersonWeek: (personId: number, week: string) =>
    request<PersonWeek>(`/persons/${personId}/weeks/${week}`),

  // E3：工作台汇总（只读；过滤只决定项目与人员范围）
  getWorkbench: (params: {
    week?: string;
    project_id?: number;
    owner_person_id?: number;
  } = {}) => {
    const q = new URLSearchParams();
    if (params.week) q.set("week", params.week);
    if (params.project_id !== undefined) q.set("project_id", String(params.project_id));
    if (params.owner_person_id !== undefined) {
      q.set("owner_person_id", String(params.owner_person_id));
    }
    const qs = q.toString();
    return request<Workbench>(`/workbench${qs ? `?${qs}` : ""}`);
  },
  setWeekCapacity: (personId: number, week: string, days: number | null) =>
    request<PersonWeek>(`/persons/${personId}/weeks/${week}/capacity`, {
      method: "PUT",
      body: body({ days }),
    }),
  clearWeekCapacity: (personId: number, week: string) =>
    request<PersonWeek>(`/persons/${personId}/weeks/${week}/capacity`, { method: "DELETE" }),
  setWeekReview: (personId: number, week: string, reviewed: boolean) =>
    request<PersonWeek>(`/persons/${personId}/weeks/${week}/review`, {
      method: "PUT",
      body: body({ reviewed }),
    }),

  history: (params: { entity_type?: string; entity_id?: number } = {}) => {
    const q = new URLSearchParams();
    if (params.entity_type) q.set("entity_type", params.entity_type);
    if (params.entity_id !== undefined) q.set("entity_id", String(params.entity_id));
    const qs = q.toString();
    return request<HistoryEntry[]>(`/history${qs ? `?${qs}` : ""}`);
  },

  previewReschedule: (payload: {
    milestone_id: number;
    new_commit_date?: string | null;
    new_start_date?: string | null;
    mode: "current" | "cascade";
  }) => request<ReschedulePreview>("/reschedule/preview", { method: "POST", body: body(payload) }),
  applyReschedule: (payload: {
    preview_id: number;
    reason: string;
    mode: "current" | "cascade";
  }) =>
    request<{ updated: { name: string }[]; mode: string }>("/reschedule/apply", {
      method: "POST",
      body: body(payload),
    }),

  runImport: (payload: { source_root?: string | null; apply: boolean }) =>
    request<ImportReport>("/imports", { method: "POST", body: body(payload) }),
  listImports: () => request<ImportReport[]>("/imports"),
  getImport: (id: number) => request<ImportReport>(`/imports/${id}`),
  importMarkdown: async (id: number) => {
    const res = await fetch(`${BASE}/imports/${id}/report.md`);
    if (!res.ok) throw new ApiError(res.status, "读取导入报告失败");
    return res.text();
  },

  seedDemo: () => request<Project>("/demo/seed", { method: "POST" }),
};
