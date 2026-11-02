// @vitest-environment jsdom
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import WorkbenchPage from "./WorkbenchPage";

const getWorkbench = vi.fn();
const listProjects = vi.fn();
const listPersons = vi.fn();

vi.mock("../api", () => ({
  api: {
    getWorkbench: (...args: unknown[]) => getWorkbench(...args),
    listProjects: (...args: unknown[]) => listProjects(...args),
    listPersons: (...args: unknown[]) => listPersons(...args),
  },
  ApiError: class extends Error {},
}));

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

beforeEach(() => {
  listProjects.mockResolvedValue([]);
  listPersons.mockResolvedValue([]);
});

function project(overrides: Record<string, unknown> = {}) {
  return {
    id: 1,
    name: "贵州V1.5",
    state: "active",
    on_hold: false,
    priority: "P1",
    priority_rank: 1,
    current_focus_milestone_id: 11,
    current_focus_name: "V1.5交付",
    allocation_days: 3,
    overdue_count: 0,
    blocked_count: 0,
    due_soon_count: 0,
    milestones: [],
    ...overrides,
  };
}

function person(overrides: Record<string, unknown> = {}) {
  return {
    person_id: 7,
    name: "傅相杰",
    capacity: 5,
    capacity_source: "default",
    total_days: 0,
    over_days: null,
    remaining_days: 5,
    reviewed: true,
    status_text: "剩余 5 人天",
    assignments: [],
    allocations: [],
    unallocated_milestones: [],
    conflicts: [],
    ...overrides,
  };
}

function board(overrides: Record<string, unknown> = {}) {
  return {
    week: "2026-11-02",
    week_end: "2026-11-08",
    today: "2026-11-02",
    projects: [],
    maintenance_projects: [],
    people: [],
    todos: [],
    has_pending: false,
    ...overrides,
  };
}

function renderPage(url = "/") {
  return render(
    <MemoryRouter initialEntries={[url]}>
      <WorkbenchPage />
    </MemoryRouter>,
  );
}

/** 可手动兑现的 Promise，用于模拟乱序返回的请求。 */
function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((r) => {
    resolve = r;
  });
  return { promise, resolve };
}

describe("工作台页", () => {
  it("既无异常又无待补数据时才显示没有待处理事项", async () => {
    getWorkbench.mockResolvedValue(board());
    renderPage();
    await waitFor(() => expect(getWorkbench).toHaveBeenCalled());
    expect(await screen.findByText("当前没有待处理事项")).toBeTruthy();
  });

  it("有待处理事项时不显示空态文案，并标注临近交付的周区间", async () => {
    getWorkbench.mockResolvedValue(
      board({
        has_pending: true,
        todos: [
          {
            kind: "overdue",
            project_id: 1,
            project_name: "贵州V1.5",
            project_state: "active",
            milestone_id: 11,
            milestone_name: "V1.5交付",
            person_id: 7,
            person_name: "傅相杰",
            due_date: "2026-10-20",
            week_label: "2026-11-02 ~ 2026-11-08",
            detail: "节点「V1.5交付」已于 2026-10-20 到期，尚未完成",
          },
          {
            kind: "due_soon",
            project_id: 1,
            project_name: "贵州V1.5",
            project_state: "active",
            milestone_id: 12,
            milestone_name: "本周到期",
            person_id: 7,
            person_name: "傅相杰",
            due_date: "2026-11-05",
            week_label: "2026-11-02 ~ 2026-11-08",
            detail: "节点「本周到期」在 2026-11-02 ~ 2026-11-08 内到期，尚未完成",
          },
        ],
      }),
    );
    renderPage();
    expect(await screen.findByText("逾期")).toBeTruthy();
    expect(screen.queryByText("当前没有待处理事项")).toBeNull();
    expect(screen.getByText("（2026-11-02 ~ 2026-11-08）")).toBeTruthy();
  });

  it("维护项目单列在维护区，暂停项目独立标识", async () => {
    getWorkbench.mockResolvedValue(
      board({
        projects: [project({ id: 2, name: "北京仓储", state: "on-hold", on_hold: true })],
        maintenance_projects: [project({ id: 3, name: "卡鉴", state: "maintenance" })],
      }),
    );
    renderPage();
    const maintenance = await screen.findByRole("region", { name: "维护项目" });
    expect(maintenance.textContent).toContain("卡鉴");
    expect(maintenance.textContent).not.toContain("北京仓储");
    const projects = screen.getByRole("region", { name: "项目" });
    expect(projects.textContent).toContain("北京仓储");
    expect(projects.textContent).toContain("已暂停");
  });

  it("展开节点后显示逾期与临近交付标识", async () => {
    getWorkbench.mockResolvedValue(
      board({
        projects: [
          project({
            milestones: [
              {
                id: 11,
                name: "V1.5交付",
                state: "进行中",
                commit_date: "2026-10-20",
                start_date: null,
                assignee_id: 7,
                assignee_name: "傅相杰",
                overdue: true,
                due_this_week: false,
                blocked: false,
              },
              {
                id: 12,
                name: "本周到期",
                state: "未开始",
                commit_date: "2026-11-05",
                start_date: null,
                assignee_id: null,
                assignee_name: null,
                overdue: false,
                due_this_week: true,
                blocked: false,
              },
            ],
          }),
        ],
      }),
    );
    renderPage();
    const card = await screen.findByTestId("project-1");
    fireEvent.click(screen.getByRole("button", { name: "展开节点" }));
    expect(card.textContent).toContain("V1.5交付");
    expect(card.textContent).toContain("本周到期");
    expect(card.textContent).toContain("逾期");
    expect(card.textContent).toContain("临近交付");
  });

  it("按项目负责人过滤时请求带上 owner_person_id，人员合计保持完整", async () => {
    listPersons.mockResolvedValue([
      { id: 7, name: "傅相杰" },
      { id: 8, name: "赵辉辉" },
    ]);
    listProjects.mockResolvedValue([]);
    getWorkbench.mockResolvedValue(
      board({
        has_pending: true,
        todos: [
          {
            kind: "review",
            project_id: null,
            project_name: null,
            project_state: null,
            milestone_id: null,
            milestone_name: null,
            person_id: 7,
            person_name: "傅相杰",
            due_date: null,
            week_label: "2026-11-02 ~ 2026-11-08",
            detail: "傅相杰 本周投入待补充/核对",
          },
        ],
        people: [
          person({
            total_days: 5.5,
            over_days: 0.5,
            remaining_days: null,
            status_text: "已填投入已超额 0.5 人天",
            conflicts: [
              {
                project_id: 1,
                project_name: "贵州V1.5",
                project_state: "active",
                days: 3,
                allocations: [],
              },
              {
                project_id: 3,
                project_name: "卡鉴",
                project_state: "maintenance",
                days: 2.5,
                allocations: [],
              },
            ],
          }),
        ],
      }),
    );
    renderPage();
    await waitFor(() => expect(getWorkbench).toHaveBeenCalled());
    fireEvent.change(screen.getByLabelText("项目负责人筛选"), { target: { value: "8" } });
    await waitFor(() =>
      expect(getWorkbench).toHaveBeenLastCalledWith(
        expect.objectContaining({ owner_person_id: 8 }),
      ),
    );
    // 过滤不裁剪这个人的占用与冲突来源
    expect(screen.getByText(/本周投入 5.5 人天/)).toBeTruthy();
    expect(screen.getByText(/超出 0.5 人天/)).toBeTruthy();
    expect(screen.getByText("卡鉴")).toBeTruthy();
  });

  it("按项目过滤时请求带上 project_id", async () => {
    listProjects.mockResolvedValue([{ id: 1, name: "贵州V1.5" }]);
    listPersons.mockResolvedValue([]);
    getWorkbench.mockResolvedValue(board());
    renderPage();
    await waitFor(() => expect(getWorkbench).toHaveBeenCalled());
    fireEvent.change(screen.getByLabelText("项目筛选"), { target: { value: "1" } });
    await waitFor(() =>
      expect(getWorkbench).toHaveBeenLastCalledWith(
        expect.objectContaining({ project_id: 1 }),
      ),
    );
  });

  it("沿用 URL 上的周参数，与项目页、人员页同源", async () => {
    getWorkbench.mockResolvedValue(board({ week: "2026-11-09", week_end: "2026-11-15" }));
    renderPage("/?week=2026-11-09");
    await waitFor(() =>
      expect(getWorkbench).toHaveBeenCalledWith(expect.objectContaining({ week: "2026-11-09" })),
    );
    expect(await screen.findByText("周区间 2026-11-09 ~ 2026-11-15")).toBeTruthy();
  });

  it("切换周后丢弃过期响应，只渲染最后一次结果", async () => {
    const first = deferred<ReturnType<typeof board>>();
    const second = deferred<ReturnType<typeof board>>();
    getWorkbench.mockImplementationOnce(() => first.promise);
    getWorkbench.mockImplementationOnce(() => second.promise);
    renderPage("/?week=2026-11-02");
    await waitFor(() => expect(getWorkbench).toHaveBeenCalledTimes(1));
    fireEvent.click(screen.getByRole("button", { name: "下一周" }));
    await waitFor(() => expect(getWorkbench).toHaveBeenCalledTimes(2));
    await act(async () => {
      second.resolve(
        board({ week: "2026-11-09", week_end: "2026-11-15", projects: [project({ name: "第二周项目" })] }),
      );
    });
    expect(await screen.findByText("第二周项目")).toBeTruthy();
    await act(async () => {
      first.resolve(
        board({ week: "2026-11-02", week_end: "2026-11-08", projects: [project({ name: "第一周项目" })] }),
      );
    });
    expect(screen.queryByText("第一周项目")).toBeNull();
    expect(screen.getByText("第二周项目")).toBeTruthy();
  });

  it("接口失败时显示错误，且不显示没有待处理事项", async () => {
    getWorkbench.mockRejectedValue(new Error("boom"));
    renderPage();
    expect(await screen.findByRole("alert")).toBeTruthy();
    expect(screen.queryByText("当前没有待处理事项")).toBeNull();
  });
});
