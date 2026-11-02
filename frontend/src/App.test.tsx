// @vitest-environment jsdom
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import App from "./App";

const listPersons = vi.fn();
const listProjects = vi.fn();
const listAssignments = vi.fn();
const getPersonWeek = vi.fn();

vi.mock("./api", () => ({
  api: {
    listPersons: (...args: unknown[]) => listPersons(...args),
    listProjects: (...args: unknown[]) => listProjects(...args),
    listAssignments: (...args: unknown[]) => listAssignments(...args),
    getPersonWeek: (...args: unknown[]) => getPersonWeek(...args),
    listMilestones: vi.fn().mockResolvedValue([]),
    listAllocations: vi.fn().mockResolvedValue([]),
    listProjectsForMilestones: vi.fn(),
    updatePerson: vi.fn(),
    createAssignment: vi.fn(),
    createAllocation: vi.fn(),
    updateAllocation: vi.fn(),
    deleteAllocation: vi.fn(),
    setWeekCapacity: vi.fn(),
    clearWeekCapacity: vi.fn(),
    setWeekReview: vi.fn(),
    getWorkbench: vi.fn().mockResolvedValue({
      week: "2026-11-02",
      week_end: "2026-11-08",
      today: "2026-11-02",
      projects: [],
      maintenance_projects: [],
      people: [],
      todos: [],
      has_pending: false,
    }),
  },
  ApiError: class extends Error {},
}));

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("导航与路由", () => {
  it("导航提供人员入口", () => {
    listPersons.mockResolvedValue([]);
    render(
      <MemoryRouter initialEntries={["/"]}>
        <App />
      </MemoryRouter>,
    );
    const link = screen.getByRole("link", { name: "人员" });
    expect(link.getAttribute("href")).toBe("/persons");
  });

  it("导航提供工作台入口", () => {
    listPersons.mockResolvedValue([]);
    render(
      <MemoryRouter initialEntries={["/"]}>
        <App />
      </MemoryRouter>,
    );
    const link = screen.getByRole("link", { name: "工作台" });
    expect(link.getAttribute("href")).toBe("/workbench");
  });

  it("/persons 路由渲染人员页", async () => {
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
    listProjects.mockResolvedValue([]);
    listAssignments.mockResolvedValue([]);
    getPersonWeek.mockResolvedValue({
      person_id: 7,
      week: "2026-11-02",
      week_end: "2026-11-08",
      capacity: 5,
      capacity_source: "default",
      total_days: 0,
      over_days: 0,
      remaining_days: 5,
      reviewed: false,
      allocations: [],
      assignments: [],
      unallocated_milestones: [],
      status_text: "投入待补充",
    });

    render(
      <MemoryRouter initialEntries={["/persons"]}>
        <App />
      </MemoryRouter>,
    );

    await waitFor(() => expect(screen.getByRole("heading", { name: "人员" })).toBeTruthy());
    expect(screen.getByLabelText("人员列表")).toBeTruthy();
  });
});
