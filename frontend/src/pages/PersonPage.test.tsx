// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter } from "react-router-dom";
import PersonPage from "./PersonPage";

const listPersons = vi.fn();
const createPerson = vi.fn();
const updatePerson = vi.fn();
const getPersonWeek = vi.fn();
const listProjects = vi.fn();
const listMilestones = vi.fn();
const listAssignments = vi.fn();
const createAssignment = vi.fn();

vi.mock("../api", () => ({
  api: {
    listPersons: (...args: unknown[]) => listPersons(...args),
    createPerson: (...args: unknown[]) => createPerson(...args),
    updatePerson: (...args: unknown[]) => updatePerson(...args),
    getPersonWeek: (...args: unknown[]) => getPersonWeek(...args),
    listProjects: (...args: unknown[]) => listProjects(...args),
    listMilestones: (...args: unknown[]) => listMilestones(...args),
    listAssignments: (...args: unknown[]) => listAssignments(...args),
    createAssignment: (...args: unknown[]) => createAssignment(...args),
    createAllocation: vi.fn(),
    updateAllocation: vi.fn(),
    deleteAllocation: vi.fn(),
    setWeekCapacity: vi.fn(),
    clearWeekCapacity: vi.fn(),
    setWeekReview: vi.fn(),
  },
  ApiError: class extends Error {},
}));

const persons = [
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
  {
    id: 8,
    name: "文磊",
    roles: "业务对接",
    skills: "",
    weekly_capacity: null,
    note: "",
    archived: false,
    source_ref: null,
    edited_in_app: false,
  },
];

function setup() {
  listPersons.mockResolvedValue(persons);
  listProjects.mockResolvedValue([
    { id: 1, name: "贵州V1.5" },
    { id: 2, name: "卡鉴" },
  ]);
  listMilestones.mockResolvedValue([]);
  listAssignments.mockResolvedValue([]);
  getPersonWeek.mockResolvedValue({
    person_id: 7,
    week: "2026-11-02",
    week_end: "2026-11-08",
    capacity: 5,
    capacity_source: "default",
    total_days: 3,
    over_days: null,
    remaining_days: null,
    reviewed: false,
    allocations: [],
    assignments: [],
    unallocated_milestones: [],
    status_text: "投入待补充",
  });
}

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("人员页", () => {
  it("列出人员并显示其周视图", async () => {
    setup();
    render(
      <MemoryRouter>
        <PersonPage />
      </MemoryRouter>,
    );
    await waitFor(() => expect(screen.getByText("傅相杰")).toBeTruthy());
    expect(screen.getByText("文磊")).toBeTruthy();
    await waitFor(() => expect(screen.getByText(/本周占用 3 人天/)).toBeTruthy());
  });

  it("显示人员的能力标签与默认周容量", async () => {
    setup();
    render(
      <MemoryRouter>
        <PersonPage />
      </MemoryRouter>,
    );
    await waitFor(() => expect(screen.getByText("傅相杰")).toBeTruthy());
    expect(screen.getByText("地质AI")).toBeTruthy();
  });

  it("接口失败时显示错误信息", async () => {
    listPersons.mockRejectedValue(new Error("人员列表读取失败"));
    render(
      <MemoryRouter>
        <PersonPage />
      </MemoryRouter>,
    );
    await waitFor(() => expect(screen.getByRole("alert").textContent).toContain("人员列表读取失败"));
  });

  it("保存资料失败时保留已填值", async () => {
    setup();
    updatePerson.mockRejectedValue(new Error("姓名重复"));
    render(
      <MemoryRouter>
        <PersonPage />
      </MemoryRouter>,
    );
    await waitFor(() => expect(screen.getByText("傅相杰")).toBeTruthy());
    const input = screen.getByLabelText("能力标签") as HTMLInputElement;
    fireEvent.change(input, { target: { value: "地质AI、遥感" } });
    fireEvent.click(screen.getByText("保存资料"));
    await waitFor(() => expect(screen.getByRole("alert").textContent).toContain("姓名重复"));
    expect((screen.getByLabelText("能力标签") as HTMLInputElement).value).toBe("地质AI、遥感");
  });

  it("为人员添加项目职责，职责不计入占用", async () => {
    setup();
    createAssignment.mockResolvedValue({
      id: 3,
      person_id: 7,
      project_id: 1,
      role: "业务对接",
    });
    render(
      <MemoryRouter>
        <PersonPage />
      </MemoryRouter>,
    );
    await waitFor(() => expect(screen.getByText("傅相杰")).toBeTruthy());
    fireEvent.change(screen.getByLabelText("职责项目"), { target: { value: "1" } });
    fireEvent.change(screen.getByLabelText("职责角色"), { target: { value: "业务对接" } });
    fireEvent.click(screen.getByText("添加职责"));
    await waitFor(() =>
      expect(createAssignment).toHaveBeenCalledWith({
        person_id: 7,
        project_id: 1,
        role: "业务对接",
      }),
    );
    expect(screen.getByText(/职责不计入占用/)).toBeTruthy();
  });

  it("职责角色覆盖四类标准角色", async () => {
    setup();
    render(
      <MemoryRouter>
        <PersonPage />
      </MemoryRouter>,
    );
    await waitFor(() => expect(screen.getByText("傅相杰")).toBeTruthy());
    const roles = screen.getByLabelText("职责角色") as HTMLSelectElement;
    const values = Array.from(roles.options).map((o) => o.value);
    expect(values).toEqual(
      expect.arrayContaining(["项目负责人", "业务对接", "节点执行", "统筹管理"]),
    );
  });
});
