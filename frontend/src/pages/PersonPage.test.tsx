// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter } from "react-router-dom";
import PersonPage from "./PersonPage";

// ---------- 1. 声明 vi.fn()，写在 vi.mock 之前 ----------
// 顺序有意义：vi.mock 的工厂里用箭头包一层转发，而不是直接引用变量。
const listMonthlyRoster = vi.fn();
const getPersonMonth = vi.fn();
const createPerson = vi.fn();
const updatePerson = vi.fn();
const archivePerson = vi.fn();
const restorePerson = vi.fn();
const listProjects = vi.fn();
const listMilestones = vi.fn();
const listAssignments = vi.fn();
const createAssignment = vi.fn();
const createAllocation = vi.fn();
const updateAllocation = vi.fn();
const deleteAllocation = vi.fn();
const setWeekReview = vi.fn();

// ---------- 2. vi.mock 工厂 ----------
vi.mock("../api", () => ({
  api: {
    listMonthlyRoster: (...args: unknown[]) => listMonthlyRoster(...args),
    getPersonMonth: (...args: unknown[]) => getPersonMonth(...args),
    createPerson: (...args: unknown[]) => createPerson(...args),
    updatePerson: (...args: unknown[]) => updatePerson(...args),
    archivePerson: (...args: unknown[]) => archivePerson(...args),
    restorePerson: (...args: unknown[]) => restorePerson(...args),
    listProjects: (...args: unknown[]) => listProjects(...args),
    listMilestones: (...args: unknown[]) => listMilestones(...args),
    listAssignments: (...args: unknown[]) => listAssignments(...args),
    createAssignment: (...args: unknown[]) => createAssignment(...args),
    createAllocation: (...args: unknown[]) => createAllocation(...args),
    updateAllocation: (...args: unknown[]) => updateAllocation(...args),
    deleteAllocation: (...args: unknown[]) => deleteAllocation(...args),
    setWeekReview: (...args: unknown[]) => setWeekReview(...args),
  },
  // 页面 catch 里 instanceof ApiError 靠它；**不能省**，省了整个文件 import 就炸。
  ApiError: class extends Error {},
}));

// ---------- 3. render 一律走 renderPage() ----------
// initialEntries 钉住月份：不钉的话 MemoryRouter 默认进 `/`，
// useMonthParam() 回落成真实当前月，工具行就不是「2026年11月」，
// 传给 listMonthlyRoster 的 month 也和 fixture 的 "2026-11" 对不上。
const renderPage = () =>
  render(
    <MemoryRouter initialEntries={["/persons?month=2026-11"]}>
      <PersonPage />
    </MemoryRouter>,
  );

// ---------- 4. fixture ----------
// 2026-11 的五个周一：11-02 / 11-09 / 11-16 / 11-23 / 11-30。
const weeks = ["2026-11-02", "2026-11-09", "2026-11-16", "2026-11-23", "2026-11-30"];

const rosterActive = {
  month: "2026-11",
  weeks,
  people: [
    {
      person_id: 1,
      name: "傅相杰",
      skills: "",
      roles: "",
      note: "",
      monthly_capacity: 30,
      weekly_capacity: 5,
      used_days: 18.5,
      over_days: null,
      remaining_days: 11.5,
      reviewed: true,
      archived: false,
      projects: [
        {
          project_id: 2,
          project_name: "贵州矿产预测",
          roles: ["项目负责人"],
          days: 10,
          has_allocation: true,
          has_assignment: true,
        },
      ],
    },
  ],
};

// 张三2 必须**排在末尾**：后端按 archived, name 排序，已禁用的人在表尾，
// 这个顺序就是实现要复刻的顺序，也是下面 closest("tr") 能取到对的那一行的前提。
const rosterWithArchived = {
  ...rosterActive,
  people: [
    rosterActive.people[0],
    {
      person_id: 2,
      name: "张三2",
      skills: "",
      roles: "",
      note: "",
      monthly_capacity: 30,
      weekly_capacity: 5,
      used_days: 4.5,
      over_days: null,
      remaining_days: 25.5,
      reviewed: true,
      archived: true,
      projects: [
        {
          project_id: 2,
          project_name: "贵州矿产预测",
          roles: ["业务对接"],
          days: 0,
          has_allocation: false,
          has_assignment: true,
        },
      ],
    },
  ],
};

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("人员页", () => {
  it("渲染六列表格与工具行", async () => {
    listMonthlyRoster.mockResolvedValue(rosterActive);
    renderPage();
    expect(await screen.findByText("傅相杰")).toBeTruthy();
    // 表头用 columnheader 找：getByText("姓名") 会同时匹配到「参与项目」里
    // 的标签文本、以及详情区可能出现的同名元素，只有 columnheader 唯一。
    for (const head of ["姓名", "核定人天", "本月占用", "参与项目", "状态", "操作"]) {
      expect(screen.getByRole("columnheader", { name: head })).toBeTruthy();
    }
    expect(screen.getByText("2026年11月")).toBeTruthy();
    expect(screen.getByText("统计月份：")).toBeTruthy();
    expect(screen.getByRole("button", { name: "+ 新增人员" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "‹" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "›" })).toBeTruthy();
    expect(screen.getByLabelText("显示已禁用")).toBeTruthy();
  });

  it("本月占用显示数字、进度条与剩余", async () => {
    listMonthlyRoster.mockResolvedValue(rosterActive); // 傅相杰 used 18.5 / capacity 30 / 本月已核对
    renderPage();
    expect(await screen.findByText("18.5")).toBeTruthy();
    expect(screen.getByText("11.5")).toBeTruthy(); // 剩余 = 30 - 18.5
    // 只有一个人所以 progressbar 恰好一个；以后加了第二个人，这里要改成
    // getAllByRole("progressbar").length。
    expect(screen.getByRole("progressbar")).toBeTruthy();
  });

  it("本月有分配的周没核对完时显示「待核对」而不是剩余", async () => {
    listMonthlyRoster.mockResolvedValue({
      ...rosterActive,
      people: [{ ...rosterActive.people[0], reviewed: false, remaining_days: null }],
    });
    renderPage();
    expect(await screen.findByText("待核对")).toBeTruthy();
    expect(screen.queryByText("11.5")).toBeNull();
  });

  it("超额显示红色「超 N 人天」，且不给剩余", async () => {
    listMonthlyRoster.mockResolvedValue({
      ...rosterActive,
      people: [
        {
          ...rosterActive.people[0],
          used_days: 32,
          over_days: 2,
          reviewed: false,
          remaining_days: null,
        },
      ],
    });
    renderPage();
    expect(await screen.findByText("超 2 人天")).toBeTruthy();
    expect(screen.queryByText("11.5")).toBeNull();
    // 进度条转红不能只靠实现，把 class 钉住。
    const bar = screen.getByRole("progressbar");
    expect(bar.classList.contains("cell-progress-over")).toBe(true);
  });

  it("核定人天为 0 时进度条不是不确定态", async () => {
    listMonthlyRoster.mockResolvedValue({
      ...rosterActive,
      people: [
        {
          ...rosterActive.people[0],
          monthly_capacity: 0,
          used_days: 0,
          over_days: null,
          remaining_days: null,
          reviewed: true,
        },
      ],
    });
    renderPage();
    const bar = (await screen.findByRole("progressbar")) as HTMLProgressElement;
    expect(bar.max).toBeGreaterThan(0);
  });

  it("新增人员打开弹窗，核定人天默认 30，提交带 monthly_capacity", async () => {
    listMonthlyRoster.mockResolvedValue(rosterActive);
    renderPage();
    fireEvent.click(screen.getByRole("button", { name: "+ 新增人员" }));
    expect(screen.getByRole("heading", { name: "新增人员" })).toBeTruthy();
    fireEvent.change(screen.getByLabelText("姓名"), { target: { value: "李四" } });
    // 默认值：不改就提交，应该带的是 30（表单初值），而不是空。
    fireEvent.click(screen.getByRole("button", { name: "保存" }));
    expect(createPerson).toHaveBeenCalledWith(
      expect.objectContaining({ name: "李四", monthly_capacity: 30 }),
    );
  });

  it("核定人天填非法值时内联报错、不发请求", async () => {
    listMonthlyRoster.mockResolvedValue(rosterActive);
    renderPage();
    fireEvent.click(screen.getByRole("button", { name: "+ 新增人员" }));
    fireEvent.change(screen.getByLabelText("姓名"), { target: { value: "李四" } });
    fireEvent.change(screen.getByLabelText("核定人天"), { target: { value: "12.3" } });
    fireEvent.click(screen.getByRole("button", { name: "保存" }));
    // 12.3 不是 0.5 的整数倍 → parseDays 拒绝
    expect(createPerson).not.toHaveBeenCalled();
    expect(screen.getByText("核定人天必须是非负的 0.5 粒度数字")).toBeTruthy();
    expect(screen.getByRole("heading", { name: "新增人员" })).toBeTruthy();
  });

  it("编辑打开弹窗并带出原值，提交调 updatePerson", async () => {
    listMonthlyRoster.mockResolvedValue(rosterActive);
    renderPage();
    // 表在异步拉取后才渲染：先等人员名出现，再去点那一行的「编辑」。
    await screen.findByText("傅相杰");
    fireEvent.click(screen.getByRole("button", { name: "编辑" }));
    expect(screen.getByRole("heading", { name: "编辑 · 傅相杰" })).toBeTruthy();
    // 带出原值：核定人天的输入框里应该是 30，不能是空。
    expect((screen.getByLabelText("核定人天") as HTMLInputElement).value).toBe("30");
    fireEvent.change(screen.getByLabelText("核定人天"), { target: { value: "20" } });
    fireEvent.click(screen.getByRole("button", { name: "保存" }));
    expect(updatePerson).toHaveBeenCalledWith(
      rosterActive.people[0].person_id,
      expect.objectContaining({ monthly_capacity: 20 }),
    );
  });

  it("禁用 / 启用分别调 archivePerson / restorePerson", async () => {
    // 用含已禁用人的那份 fixture：启用按钮只对 archived 的人出现。
    listMonthlyRoster.mockResolvedValue(rosterWithArchived);
    renderPage();
    // 表格是异步拉到的，先等表渲染出来（张三2 在表尾）。
    await screen.findByText("张三2");
    const zhang = screen.getByText("张三2").closest("tr")!;
    fireEvent.click(within(zhang).getByRole("button", { name: "启用" }));
    expect(restorePerson).toHaveBeenCalledWith(rosterWithArchived.people[1].person_id);

    const fu = screen.getByText("傅相杰").closest("tr")!;
    fireEvent.click(within(fu).getByRole("button", { name: "禁用" }));
    expect(archivePerson).toHaveBeenCalledWith(rosterActive.people[0].person_id);
  });

  it("弹窗里没有「默认周容量」字段", async () => {
    listMonthlyRoster.mockResolvedValue(rosterActive);
    renderPage();
    fireEvent.click(screen.getByRole("button", { name: "+ 新增人员" }));
    expect(screen.queryByText(/默认周容量/)).toBeNull();
  });

  it("接口失败时显示错误信息", async () => {
    listMonthlyRoster.mockRejectedValue(new Error("服务器 500"));
    renderPage();
    expect(await screen.findByText(/服务器 500/)).toBeTruthy();
  });

  it("已禁用的人默认不显示，勾开关后出现并灰显", async () => {
    // 按 includeArchived 参数分派，不要一律返回同一份 fixture——
    // 那样「默认不显示」这条断言根本没测到开关。
    listMonthlyRoster.mockImplementation((_m: string, includeArchived = false) =>
      Promise.resolve(includeArchived ? rosterWithArchived : rosterActive),
    );
    renderPage();
    expect(screen.queryByText("张三2")).toBeNull();
    expect(listMonthlyRoster).toHaveBeenCalledWith("2026-11", false);

    fireEvent.click(screen.getByLabelText("显示已禁用"));
    // 开关自己触发重新拉表（useEffect 依赖 includeArchived），**不要**用 rerender——
    // rerender 带相同参数不会重跑 effect，`useMonthParam` 也没有变化，列表不会更新。
    await waitFor(() => expect(screen.getByText("张三2")).toBeTruthy());
    expect(listMonthlyRoster).toHaveBeenCalledWith("2026-11", true);
    const archivedRow = screen.getByText("张三2").closest("tr")!;
    expect(archivedRow.classList.contains("row-archived")).toBe(true);
    expect(within(archivedRow).getByText("已禁用")).toBeTruthy();

    // 顺序：后端按 archived, name 排，已禁用的人在表尾。
    const activeRow = screen.getByText("傅相杰").closest("tr")!;
    expect(activeRow.compareDocumentPosition(archivedRow) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  it("点姓名选中该人，行高亮", async () => {
    listMonthlyRoster.mockResolvedValue(rosterActive);
    renderPage();
    const nameBtn = await screen.findByRole("button", { name: "傅相杰" });
    fireEvent.click(nameBtn);
    const row = nameBtn.closest("tr")!;
    expect(row.classList.contains("row-selected")).toBe(true);
  });
});
