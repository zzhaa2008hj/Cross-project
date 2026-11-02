// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import WeekPanel from "./WeekPanel";

const getPersonWeek = vi.fn();
const listProjects = vi.fn();
const listMilestones = vi.fn();
const createAllocation = vi.fn();
const updateAllocation = vi.fn();
const deleteAllocation = vi.fn();
const setWeekCapacity = vi.fn();
const clearWeekCapacity = vi.fn();
const setWeekReview = vi.fn();

vi.mock("../api", () => ({
  api: {
    getPersonWeek: (...args: unknown[]) => getPersonWeek(...args),
    listProjects: (...args: unknown[]) => listProjects(...args),
    listMilestones: (...args: unknown[]) => listMilestones(...args),
    createAllocation: (...args: unknown[]) => createAllocation(...args),
    updateAllocation: (...args: unknown[]) => updateAllocation(...args),
    deleteAllocation: (...args: unknown[]) => deleteAllocation(...args),
    setWeekCapacity: (...args: unknown[]) => setWeekCapacity(...args),
    clearWeekCapacity: (...args: unknown[]) => clearWeekCapacity(...args),
    setWeekReview: (...args: unknown[]) => setWeekReview(...args),
  },
  ApiError: class extends Error {
    status: number;
    detail: string;
    constructor(status: number, detail: string) {
      super(detail);
      this.status = status;
      this.detail = detail;
    }
  },
}));

const WEEK = "2026-11-02";

function weekView(overrides: Record<string, unknown> = {}) {
  return {
    person_id: 7,
    week: WEEK,
    week_end: "2026-11-08",
    capacity: 5,
    capacity_source: "default",
    total_days: 5.5,
    over_days: 0.5,
    remaining_days: null,
    reviewed: false,
    allocations: [
      {
        id: 11,
        person_id: 7,
        project_id: 1,
        week: WEEK,
        week_end: "2026-11-08",
        days: 3,
        milestone_id: null,
        kind: "project_management",
        note: "",
        project_name: "贵州V1.5",
        milestone_name: null,
      },
      {
        id: 12,
        person_id: 7,
        project_id: 2,
        week: WEEK,
        week_end: "2026-11-08",
        days: 2.5,
        milestone_id: 5,
        kind: "milestone",
        note: "",
        project_name: "卡鉴",
        milestone_name: "接口联调",
      },
    ],
    assignments: [],
    unallocated_milestones: [],
    status_text: "已填投入已超额 0.5 人天",
    ...overrides,
  };
}

const projects = [
  { id: 1, name: "贵州V1.5" },
  { id: 2, name: "卡鉴" },
];

function setup(overrides: Record<string, unknown> = {}) {
  getPersonWeek.mockResolvedValue(weekView(overrides));
  listProjects.mockResolvedValue(projects);
  listMilestones.mockResolvedValue([
    { id: 5, project_id: 2, name: "接口联调" },
    { id: 6, project_id: 1, name: "数据接入" },
  ]);
}

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("人员周视图", () => {
  it("加载完成后显示容量、占用合计与状态文字", async () => {
    setup();
    render(<WeekPanel personId={7} week={WEEK} />);
    expect(screen.getByText("加载中…")).toBeTruthy();
    await waitFor(() => expect(screen.getByText(/本周占用 5.5 人天/)).toBeTruthy());
    expect(screen.getByText(/容量 5 人天/)).toBeTruthy();
    expect(screen.getByText("已填投入已超额 0.5 人天")).toBeTruthy();
  });

  it("接口失败时显示错误信息", async () => {
    getPersonWeek.mockRejectedValue(new Error("人员不存在"));
    render(<WeekPanel personId={7} week={WEEK} />);
    await waitFor(() => expect(screen.getByRole("alert").textContent).toContain("人员不存在"));
  });

  it("没有分配时显示空状态", async () => {
    setup({ allocations: [], total_days: 0, over_days: null, status_text: "投入待补充" });
    render(<WeekPanel personId={7} week={WEEK} />);
    await waitFor(() => expect(screen.getByText("本周还没有分配")).toBeTruthy());
  });

  it("容量未知时不给出精确剩余，投入未核对时提示待补充", async () => {
    setup({
      capacity: null,
      capacity_source: "override",
      over_days: null,
      remaining_days: null,
      status_text: "容量待确认",
    });
    render(<WeekPanel personId={7} week={WEEK} />);
    await waitFor(() => expect(screen.getByText("容量待确认")).toBeTruthy());
    expect(screen.queryByText(/剩余/)).toBeNull();
  });

  it("按项目聚焦时仍展示该人的全部冲突分配，不做隐藏", async () => {
    setup();
    render(<WeekPanel personId={7} week={WEEK} focusProjectId={1} />);
    await waitFor(() => expect(screen.getByText(/本周占用 5.5 人天/)).toBeTruthy());
    const list = screen.getByLabelText("分配列表");
    expect(within(list).getByText(/贵州V1.5/)).toBeTruthy();
    expect(within(list).getByText(/卡鉴/)).toBeTruthy();
    expect(within(list).getByText(/接口联调/)).toBeTruthy();
  });

  it("新增分配成功���调用接口并刷新汇总", async () => {
    setup();
    createAllocation.mockResolvedValue({ id: 20 });
    render(<WeekPanel personId={7} week={WEEK} />);
    await waitFor(() => expect(screen.getByText(/本周占用 5.5 人天/)).toBeTruthy());
    fireEvent.change(screen.getByLabelText("新增分配项目"), { target: { value: "1" } });
    fireEvent.change(screen.getByLabelText("新增分配人天"), { target: { value: "1.5" } });
    fireEvent.click(screen.getByText("新增分配"));
    await waitFor(() =>
      expect(createAllocation).toHaveBeenCalledWith({
        person_id: 7,
        project_id: 1,
        week: WEEK,
        days: 1.5,
        milestone_id: null,
      }),
    );
    await waitFor(() => expect(getPersonWeek).toHaveBeenCalledTimes(2));
  });

  it("保存失败时保留已填值并提示错误", async () => {
    setup();
    createAllocation.mockRejectedValue(new Error("人天粒度为 0.5"));
    render(<WeekPanel personId={7} week={WEEK} />);
    await waitFor(() => expect(screen.getByText(/本周占用 5.5 人天/)).toBeTruthy());
    fireEvent.change(screen.getByLabelText("新增分配项目"), { target: { value: "1" } });
    fireEvent.change(screen.getByLabelText("新增分配人天"), { target: { value: "1.5" } });
    fireEvent.click(screen.getByText("新增分配"));
    await waitFor(() => expect(screen.getByRole("alert").textContent).toContain("人天粒度为 0.5"));
    expect((screen.getByLabelText("新增分配人天") as HTMLInputElement).value).toBe("1.5");
  });

  it("点击核对按钮提交显式核对状态", async () => {
    setup();
    setWeekReview.mockResolvedValue({ reviewed: true });
    render(<WeekPanel personId={7} week={WEEK} />);
    await waitFor(() => expect(screen.getByText("标记本周投入已核对")).toBeTruthy());
    fireEvent.click(screen.getByText("标记本周投入已核对"));
    await waitFor(() => expect(setWeekReview).toHaveBeenCalledWith(7, WEEK, true));
  });
});
