// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import ProjectDetailPage from "./ProjectDetailPage";
import { currentWeek } from "../week";

const getProject = vi.fn();
const listPersons = vi.fn();
const listProjects = vi.fn();
const listMilestones = vi.fn();
const listAllocations = vi.fn();
const listAssignments = vi.fn();
const getPersonWeek = vi.fn();
const createAllocation = vi.fn();
const updateAllocation = vi.fn();
const deleteAllocation = vi.fn();

vi.mock("../api", () => ({
  api: {
    getProject: (...args: unknown[]) => getProject(...args),
    listPersons: (...args: unknown[]) => listPersons(...args),
    listProjects: (...args: unknown[]) => listProjects(...args),
    listMilestones: (...args: unknown[]) => listMilestones(...args),
    listAllocations: (...args: unknown[]) => listAllocations(...args),
    listAssignments: (...args: unknown[]) => listAssignments(...args),
    getPersonWeek: (...args: unknown[]) => getPersonWeek(...args),
    updateProject: vi.fn(),
    archiveProject: vi.fn(),
    restoreProject: vi.fn(),
    createAllocation: (...args: unknown[]) => createAllocation(...args),
    updateAllocation: (...args: unknown[]) => updateAllocation(...args),
    deleteAllocation: (...args: unknown[]) => deleteAllocation(...args),
    setWeekCapacity: vi.fn(),
    clearWeekCapacity: vi.fn(),
    setWeekReview: vi.fn(),
    history: () => Promise.resolve([]),
  },
  ApiError: class extends Error {},
}));

const WEEK = currentWeek();

const project = {
  id: 3,
  name: "贵州V1.5",
  state: "active",
  priority: "P1",
  progress: "",
  note: "",
  archived: false,
  current_focus_milestone_id: null,
  milestones: [
    {
      id: 5,
      project_id: 3,
      name: "接口联调",
      deliverable: "",
      start_date: null,
      commit_date: null,
      state: "in_progress",
      assignee_id: 7,
      assignee_name: "傅相杰",
      owner_role: "",
      weekly_investment_pct: null,
      buffer_source: null,
      workday_override: null,
      progress: "",
      blocker_reason: "",
      contact_person: "",
      next_followup_date: null,
      note: "",
      source_ref: null,
      edited_in_app: false,
      archived: false,
      version: 1,
      predecessor_ids: [],
      buffer: {
        status: "ok",
        window_workdays: 5,
        buffer_days: 0,
        internal_target: null,
        consumable: true,
      },
    },
  ],
};

const projectAllocations = [
  {
    id: 20,
    person_id: 7,
    project_id: 3,
    week: WEEK,
    week_end: null,
    days: 3,
    milestone_id: 5,
    kind: "milestone",
    note: "",
    person_name: "傅相杰",
    project_name: "贵州V1.5",
    milestone_name: "接口联调",
  },
];

const personWeek = {
  person_id: 7,
  week: WEEK,
  week_end: null,
  capacity: 5,
  capacity_source: "default",
  total_days: 5.5,
  over_days: 0.5,
  remaining_days: null,
  reviewed: false,
  allocations: [
    projectAllocations[0],
    {
      id: 21,
      person_id: 7,
      project_id: 4,
      week: WEEK,
      week_end: null,
      days: 2.5,
      milestone_id: null,
      kind: "project_management",
      note: "",
      person_name: "傅相杰",
      project_name: "卡鉴",
      milestone_name: null,
    },
  ],
  assignments: [],
  unallocated_milestones: [],
  status_text: "已填投入已超额 0.5 人天",
};

const otherProjectAllocation = {
  id: 21,
  person_id: 7,
  project_id: 4,
  week: WEEK,
  week_end: null,
  days: 2.5,
  milestone_id: null,
  kind: "project_management",
  note: "",
  person_name: "傅相杰",
  project_name: "卡鉴",
  milestone_name: null,
};

/**
 * 模拟后端写入后的读取结果：分配集合可变，人员周合计按全部项目的分配求和
 * （同一个人可能有多个项目来源）。
 */
function mockStore() {
  const state = { allocations: [projectAllocations[0]] as Record<string, unknown>[] };
  listAllocations.mockImplementation(async () => state.allocations);
  getPersonWeek.mockImplementation(async () => {
    const rows = [...state.allocations, otherProjectAllocation];
    const total = rows.reduce((sum, r) => sum + Number(r.days), 0);
    return {
      ...personWeek,
      total_days: total,
      over_days: total > 5 ? total - 5 : null,
      allocations: rows,
    };
  });
  return state;
}

function renderPage() {
  return render(
    <MemoryRouter initialEntries={["/projects/3"]}>
      <Routes>
        <Route path="/projects/:projectId" element={<ProjectDetailPage />} />
      </Routes>
    </MemoryRouter>,
  );
}

function setup() {
  getProject.mockResolvedValue(project);
  listPersons.mockResolvedValue([
    {
      id: 7,
      name: "傅相杰",
      roles: "项目负责人",
      skills: "地质AI",
      weekly_capacity: 5,
      note: "",
      archived: false,
      source_ref: null,
      edited_in_app: true,
    },
  ]);
  listProjects.mockResolvedValue([
    { id: 3, name: "贵州V1.5" },
    { id: 4, name: "卡鉴" },
  ]);
  listMilestones.mockResolvedValue([]);
  listAllocations.mockResolvedValue(projectAllocations);
  listAssignments.mockResolvedValue([]);
  getPersonWeek.mockResolvedValue(personWeek);
}

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("项目页的周投入分配", () => {
  it("显示本项目的分配，并复用人员页同一份 Allocation ID", async () => {
    setup();
    renderPage();
    await waitFor(() => expect(screen.getByText("周投入分配")).toBeTruthy());
    const list = screen.getByLabelText("项目分配列表");
    expect(within(list).getByText(/傅相杰/)).toBeTruthy();
    expect(within(list).getByText(/接口联调/)).toBeTruthy();
    expect(within(list).getByText(/分配#20/)).toBeTruthy();
  });

  it("项目页仍展示该人的全部跨项目冲突，不因项目筛选被隐藏", async () => {
    setup();
    renderPage();
    await waitFor(() => expect(screen.getByText(/本周占用 5.5 人天/)).toBeTruthy());
    const list = screen.getByLabelText("分配列表");
    expect(within(list).getByText(/贵州V1.5/)).toBeTruthy();
    expect(within(list).getByText(/卡鉴/)).toBeTruthy();
    expect(within(list).getByText("分配#21")).toBeTruthy();
  });

  it("新增分配后同页项目分配列表与人员周合计立即同步，不靠刷新页面", async () => {
    setup();
    const state = mockStore();
    createAllocation.mockImplementation(async (payload: Record<string, unknown>) => {
      const created = {
        ...payload,
        id: 77,
        week_end: null,
        kind: "project_management",
        note: "",
        person_name: "傅相杰",
        project_name: "贵州V1.5",
        milestone_name: null,
      };
      state.allocations = [...state.allocations, created];
      return created;
    });
    renderPage();
    // 人员卡在父页分配到达后才挂载，先等人员卡渲染完成再操作。
    await waitFor(() => expect(screen.getByLabelText("新增分配项目")).toBeTruthy());
    await waitFor(() => expect(screen.getByLabelText("项目分配列表")).toBeTruthy());

    fireEvent.change(screen.getByLabelText("新增分配项目"), { target: { value: "3" } });
    fireEvent.change(screen.getByLabelText("新增分配人天"), { target: { value: "2" } });
    fireEvent.click(screen.getByRole("button", { name: "新增分配" }));

    await waitFor(() => {
      const list = screen.getByLabelText("项目分配列表");
      expect(within(list).getByText(/分配#77/)).toBeTruthy();
    });
    // 人员周合计同步：3（本项目）+ 2（新增）+ 2.5（其他项目）
    expect(await screen.findByText(/本周占用 7.5 人天/)).toBeTruthy();
  });

  it("修改分配人天后同页项目分配列表与人员周合计立即同步", async () => {
    setup();
    const state = mockStore();
    updateAllocation.mockImplementation(async (id: number, payload: Record<string, unknown>) => {
      state.allocations = state.allocations.map((a) => (a.id === id ? { ...a, ...payload } : a));
      return { ...state.allocations[0] };
    });
    renderPage();
    await waitFor(() => expect(screen.getByLabelText("分配人天#20")).toBeTruthy());
    await waitFor(() => expect(screen.getByLabelText("项目分配列表")).toBeTruthy());

    fireEvent.change(screen.getByLabelText("分配人天#20"), { target: { value: "4" } });
    fireEvent.click(screen.getByRole("button", { name: "保存分配#20" }));

    await waitFor(() => {
      const list = screen.getByLabelText("项目分配列表");
      expect(within(list).getByText("4 人天")).toBeTruthy();
    });
    expect(await screen.findByText(/本周占用 6.5 人天/)).toBeTruthy();
  });

  it("删除分配后同页项目分配列表与人员周合计立即同步", async () => {
    setup();
    const state = mockStore();
    deleteAllocation.mockImplementation(async (id: number) => {
      state.allocations = state.allocations.filter((a) => a.id !== id);
      return { ok: true };
    });
    renderPage();
    await waitFor(() => expect(screen.getByRole("button", { name: "删除分配#20" })).toBeTruthy());
    await waitFor(() => expect(screen.getByLabelText("项目分配列表")).toBeTruthy());

    fireEvent.click(screen.getByRole("button", { name: "删除分配#20" }));

    await waitFor(() => expect(screen.getByText("本项目还没有周投入分配")).toBeTruthy());
    expect(screen.queryByLabelText("项目分配列表")).toBeNull();
    expect(await screen.findByText(/本周占用 2.5 人天/)).toBeTruthy();
  });
});
