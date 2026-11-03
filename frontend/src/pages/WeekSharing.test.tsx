// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import PersonPage from "./PersonPage";
import ProjectDetailPage from "./ProjectDetailPage";
import WorkbenchPage from "./WorkbenchPage";

const listPersons = vi.fn();
const listProjects = vi.fn();
const listMilestones = vi.fn();
const listAssignments = vi.fn();
const listAllocations = vi.fn();
const getPersonWeek = vi.fn();
const getPersonMonth = vi.fn();
const listMonthlyRoster = vi.fn();
const deleteAssignment = vi.fn();
const getProject = vi.fn();
const getWorkbench = vi.fn();

vi.mock("../api", () => ({
  api: {
    listPersons: (...args: unknown[]) => listPersons(...args),
    listProjects: (...args: unknown[]) => listProjects(...args),
    listMilestones: (...args: unknown[]) => listMilestones(...args),
    listAssignments: (...args: unknown[]) => listAssignments(...args),
    listAllocations: (...args: unknown[]) => listAllocations(...args),
    getPersonWeek: (...args: unknown[]) => getPersonWeek(...args),
    getPersonMonth: (...args: unknown[]) => getPersonMonth(...args),
    getProject: (...args: unknown[]) => getProject(...args),
    getWorkbench: (...args: unknown[]) => getWorkbench(...args),
    listMonthlyRoster: (...args: unknown[]) => listMonthlyRoster(...args),
    createPerson: vi.fn(),
    updatePerson: vi.fn(),
    createAssignment: vi.fn(),
    createAllocation: vi.fn(),
    updateAllocation: vi.fn(),
    deleteAllocation: vi.fn(),
    deleteAssignment: (...args: unknown[]) => deleteAssignment(...args),
    setWeekCapacity: vi.fn(),
    clearWeekCapacity: vi.fn(),
    setWeekReview: vi.fn(),
    updateProject: vi.fn(),
    archiveProject: vi.fn(),
    restoreProject: vi.fn(),
    history: () => Promise.resolve([]),
  },
  ApiError: class extends Error {},
}));

const persons = [
  { id: 7, name: "傅相杰", roles: "项目负责人", skills: "地质AI", weekly_capacity: 5, note: "", archived: false, source_ref: null, edited_in_app: true },
  { id: 8, name: "文磊", roles: "业务对接", skills: "", weekly_capacity: null, note: "", archived: false, source_ref: null, edited_in_app: false },
];

const project = {
  id: 3,
  name: "贵州V1.5",
  state: "active",
  priority: "P1",
  progress: "",
  note: "",
  archived: false,
  current_focus_milestone_id: null,
  milestones: [],
  assignments: [],
};

const roster = {
  month: "2026-11",
  people: [
    { person_id: 7, name: "傅相杰", skills: "地质AI", roles: "项目负责人", note: "",
      monthly_capacity: 30, weekly_capacity: 5, used_days: 18.5, over_days: null,
      remaining_days: 11.5, reviewed: true, archived: false, projects: [] },
    { person_id: 8, name: "文磊", skills: "", roles: "业务对接", note: "",
      monthly_capacity: 30, weekly_capacity: null, used_days: 0, over_days: null,
      remaining_days: null, reviewed: false, archived: false, projects: [] },
  ],
};

function personWeek(week: string) {
  return {
    person_id: 7,
    week,
    week_end: "2026-11-08",
    capacity: 5,
    capacity_source: "default",
    total_days: 5.5,
    over_days: 0.5,
    remaining_days: null,
    reviewed: false,
    allocations: [
      {
        id: 21,
        person_id: 7,
        project_id: 4,
        week,
        milestone_id: null,
        kind: "project_management",
        days: 2.5,
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
}

beforeEach(() => {
  listPersons.mockResolvedValue(persons);
  listProjects.mockResolvedValue([
    { id: 3, name: "贵州V1.5" },
    { id: 4, name: "卡鉴" },
  ]);
  listMilestones.mockResolvedValue([]);
  listAssignments.mockResolvedValue([]);
  listAllocations.mockResolvedValue([
    {
      id: 21,
      person_id: 7,
      project_id: 3,
      week: "2026-11-02",
      milestone_id: null,
      kind: "project_management",
      days: 2.5,
      note: "",
      person_name: "傅相杰",
      project_name: "贵州V1.5",
      milestone_name: null,
    },
  ]);
  getPersonWeek.mockImplementation((_id: number, week: string) => Promise.resolve(personWeek(week)));
  getProject.mockResolvedValue(project);
  listMonthlyRoster.mockResolvedValue(roster);
  getPersonMonth.mockResolvedValue({
    person_id: 8, month: "2026-11", monthly_capacity: 30, used_days: 0, over_days: null,
    remaining_days: null, reviewed: false, weeks: [], assignments: [], projects: [],
  });
  getWorkbench.mockResolvedValue({
    week: "2026-11-02",
    week_end: "2026-11-08",
    today: "2026-11-02",
    projects: [
      {
        id: 3,
        name: "贵州V1.5",
        state: "active",
        on_hold: false,
        priority: "P1",
        priority_rank: 1,
        current_focus_milestone_id: null,
        current_focus_name: null,
        allocation_days: 3,
        overdue_count: 0,
        blocked_count: 0,
        due_soon_count: 0,
        milestones: [],
      },
    ],
    maintenance_projects: [],
    people: [
      {
        person_id: 7,
        name: "傅相杰",
        capacity: 5,
        capacity_source: "default",
        total_days: 5.5,
        over_days: 0.5,
        remaining_days: null,
        reviewed: false,
        status_text: "已填投入已超额 0.5 人天",
        assignments: [],
        allocations: [],
        unallocated_milestones: [],
        conflicts: [
          {
            project_id: 4,
            project_name: "卡鉴",
            project_state: "maintenance",
            days: 2.5,
            allocations: [
              {
                id: 21,
                person_id: 7,
                project_id: 4,
                week: "2026-11-02",
                milestone_id: null,
                kind: "project_management",
                days: 2.5,
                note: "",
                person_name: "傅相杰",
                project_name: "卡鉴",
                milestone_name: null,
              },
            ],
          },
        ],
      },
    ],
    todos: [],
    has_pending: false,
  });
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

function renderPersons(path: string) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route path="/persons" element={<PersonPage />} />
      </Routes>
    </MemoryRouter>,
  );
}

function renderProject(path: string) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route path="/projects/:projectId" element={<ProjectDetailPage />} />
      </Routes>
    </MemoryRouter>,
  );
}

describe("三页同源", () => {
  it("人员页沿用工作台选定的月份与人员", async () => {
    renderPersons("/persons?month=2026-10&person=8");
    await waitFor(() => expect(getPersonMonth).toHaveBeenCalled());
    expect(getPersonMonth).toHaveBeenCalledWith(8, "2026-10");
  });

  it("人员页切换月份后按新月份请求同一份汇总", async () => {
    renderPersons("/persons?month=2026-10&person=8");
    await waitFor(() => expect(getPersonMonth).toHaveBeenCalled());
    fireEvent.click(screen.getByRole("button", { name: "›" }));
    await waitFor(() => expect(getPersonMonth).toHaveBeenCalledWith(8, "2026-11"));
  });

  it("项目页沿用同一个周", async () => {
    renderProject("/projects/3?week=2026-10-26");
    await waitFor(() => expect(getPersonWeek).toHaveBeenCalled());
    expect(getPersonWeek).toHaveBeenCalledWith(7, "2026-10-26");
  });

  it("工作台人员卡显示与人员页同一份 Allocation ID", async () => {
    render(
      <MemoryRouter initialEntries={["/workbench"]}>
        <Routes>
          <Route path="/workbench" element={<WorkbenchPage />} />
        </Routes>
      </MemoryRouter>,
    );
    const cards = await screen.findAllByText("傅相杰");
    expect(cards.length).toBeGreaterThan(0);
    expect(screen.getByText("分配#21")).toBeTruthy();
  });

  it("工作台卡片链接带上当前周所在月，形成工作台到项目、人员的主循环", async () => {
    render(
      <MemoryRouter initialEntries={["/workbench"]}>
        <Routes>
          <Route path="/workbench" element={<WorkbenchPage />} />
        </Routes>
      </MemoryRouter>,
    );
    const projectLink = await screen.findByRole("link", { name: "查看项目" });
    expect(projectLink.getAttribute("href")).toBe("/projects/3?week=2026-11-02");
    const personLink = screen.getByRole("link", { name: "查看人员" });
    expect(personLink.getAttribute("href")).toBe("/persons?month=2026-11&person=7");
  });
});
