// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import PersonMonthPanel from "./PersonMonthPanel";

const getPersonMonth = vi.fn();
const listProjects = vi.fn();
const listMilestones = vi.fn();
const createAllocation = vi.fn();
const updateAllocation = vi.fn();
const deleteAllocation = vi.fn();
const setWeekReview = vi.fn();

vi.mock("../api", () => ({
  api: {
    getPersonMonth: (...args: unknown[]) => getPersonMonth(...args),
    listProjects: (...args: unknown[]) => listProjects(...args),
    listMilestones: (...args: unknown[]) => listMilestones(...args),
    createAllocation: (...args: unknown[]) => createAllocation(...args),
    updateAllocation: (...args: unknown[]) => updateAllocation(...args),
    deleteAllocation: (...args: unknown[]) => deleteAllocation(...args),
    setWeekReview: (...args: unknown[]) => setWeekReview(...args),
  },
  ApiError: class extends Error {},
}));

beforeEach(() => {
  // 不设默认返回值的话，`api.listProjects()` 解析成 undefined，
  // 实现里一 `.map` 就炸——这里给空数组兜底。
  listProjects.mockResolvedValue([]);
  listMilestones.mockResolvedValue([]);
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

const renderPanel = () =>
  render(<PersonMonthPanel personId={1} month="2026-11" archived={false} onChanged={() => {}} />);

// Allocation 形状照 `frontend/src/types.ts` 的 `Allocation` 接口填。
const allocA = {
  id: 11, person_id: 1, project_id: 1, week: "2026-11-02", week_end: "2026-11-08",
  days: 10, milestone_id: null, kind: "milestone", note: "",
  person_name: "傅相杰", project_name: "贵州矿产预测", milestone_name: null,
};
const allocB = {
  ...allocA, id: 12, week: "2026-11-09", week_end: "2026-11-15", days: 5.5,
  project_id: 2, project_name: "北京仓储",
};

const detailFixture = {
  person_id: 1,
  month: "2026-11",
  monthly_capacity: 30,
  used_days: 15.5,
  over_days: null,
  remaining_days: null,
  reviewed: false,
  weeks: [
    { week: "2026-11-02", week_end: "2026-11-08", total_days: 10, reviewed: true, allocations: [allocA] },
    { week: "2026-11-09", week_end: "2026-11-15", total_days: 5.5, reviewed: false, allocations: [allocB] },
    { week: "2026-11-16", week_end: "2026-11-22", total_days: 0, reviewed: false, allocations: [] },
  ],
  assignments: [],
  projects: [],
};

// Milestone 形状照 `frontend/src/types.ts` 的 `Milestone` 接口填（值随意，
// 测试里只有 id / project_id / name 有意义）。
const msFixture = (id: number, projectId: number, name: string) => ({
  id,
  project_id: projectId,
  name,
  deliverable: "",
  start_date: null,
  commit_date: null,
  state: "进行中",
  assignee_id: null,
  assignee_name: null,
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
    status: "",
    window_workdays: null,
    buffer_days: null,
    internal_target: null,
    consumable: false,
  },
});

describe("本月分配面板", () => {
  it("每月一周一块，显示周区间", async () => {
    getPersonMonth.mockResolvedValue(detailFixture);
    renderPanel();
    expect(await screen.findByText("11-02 ~ 11-08")).toBeTruthy();
    expect(screen.getByText("11-09 ~ 11-15")).toBeTruthy();
    expect(screen.getByText("11-16 ~ 11-22")).toBeTruthy();
  });

  it("空周照常渲染核对开关", async () => {
    getPersonMonth.mockResolvedValue(detailFixture);
    renderPanel();
    // 周块是异步拉到的：先等它渲染出来，再做下面这两条同步断言。
    await screen.findByTestId("week-2026-11-02");
    // fixture 里 11-09 与 11-16 都没核对（11-16 是空周，也要有开关），
    // 所以「待核对」恰好出现两次；11-02 已核对，渲染的是「已核对」。
    // 用 getAllByText：getByText 遇到两个匹配会直接抛错，而不是返回数组。
    expect(screen.getAllByText("待核对")).toHaveLength(2);
    expect(screen.getByText("已核对")).toBeTruthy();
  });

  it("点核对调 setWeekReview", async () => {
    getPersonMonth.mockResolvedValue(detailFixture);
    renderPanel();
    // 三块周里各有 1 个 checkbox，取第一块（11-02）的；开关是 toggle，
    // 已核对的点下去要传 false。
    fireEvent.click(within(await screen.findByTestId("week-2026-11-02")).getByRole("checkbox"));
    expect(setWeekReview).toHaveBeenCalledWith(1, "2026-11-02", false);
  });

  it("改人天调 updateAllocation", async () => {
    getPersonMonth.mockResolvedValue(detailFixture);
    renderPanel();
    // 点「改」之后整行可能整个换成行内编辑态（DOM 节点换了），所以两步分开取。
    // 行是异步拉到的：先等 alloc-11 出现，再去点它。
    await screen.findByTestId("alloc-11");
    fireEvent.click(within(screen.getByTestId("alloc-11")).getByRole("button", { name: /改/ }));
    const editing = screen.getByTestId("alloc-11");
    fireEvent.change(within(editing).getByLabelText("改人天"), { target: { value: "12" } });
    fireEvent.click(within(editing).getByRole("button", { name: "保存" }));
    await waitFor(() => expect(updateAllocation).toHaveBeenCalledWith(allocA.id, { days: 12 }));
  });

  it("删分配调 deleteAllocation", async () => {
    getPersonMonth.mockResolvedValue(detailFixture);
    renderPanel();
    // 分配行是异步拉到的：先等它出现，再去点它。
    await screen.findByTestId("alloc-11");
    fireEvent.click(within(screen.getByTestId("alloc-11")).getByRole("button", { name: /删/ }));
    await waitFor(() => expect(deleteAllocation).toHaveBeenCalledWith(allocA.id));
  });

  it("新增分配落到该周周一", async () => {
    getPersonMonth.mockResolvedValue(detailFixture);
    // `api.listProjects()` 返回值不设的话会是 undefined，实现里 `.map` 就炸。
    // `<option value={String(p.id)}>` 决定了这里要传字符串 "1"（见 Step 3）。
    listProjects.mockResolvedValue([{ id: 1, name: "贵州矿产预测" }]);
    renderPanel();
    const block = await screen.findByTestId("week-2026-11-02");
    fireEvent.click(within(block).getByRole("button", { name: /新增分配/ }));
    fireEvent.change(within(block).getByLabelText("新增分配项目"), { target: { value: "1" } });
    fireEvent.change(within(block).getByLabelText("新增分配人天"), { target: { value: "3" } });
    fireEvent.click(within(block).getByRole("button", { name: "保存" }));
    await waitFor(() =>
      expect(createAllocation).toHaveBeenCalledWith({
        person_id: 1, project_id: 1, week: "2026-11-02", days: 3, milestone_id: null,
      }),
    );
  });

  it("已禁用的人不给新增分配，但已有分配照改照删", async () => {
    getPersonMonth.mockResolvedValue(detailFixture);
    render(<PersonMonthPanel personId={1} month="2026-11" archived={true} onChanged={() => {}} />);
    const block = await screen.findByTestId("week-2026-11-02");
    // 每块都有「+ 新增分配」，禁用时它们全是 disabled，取第一块的断言即可。
    expect(within(block).getByRole("button", { name: /新增分配/ }).hasAttribute("disabled")).toBe(true);
    fireEvent.click(within(block).getByRole("button", { name: /删/ }));
    await waitFor(() => expect(deleteAllocation).toHaveBeenCalledWith(allocA.id));
  });

  it("面板里不出现周口径的「容量 / 剩余」", async () => {
    getPersonMonth.mockResolvedValue(detailFixture);
    renderPanel();
    // 先等面板真正渲染出来再查：否则查的只是「加载中」占位，
    // 「没有容量 / 剩余」这条断言等于没测到。
    await screen.findByTestId("week-2026-11-02");
    expect(screen.queryByText(/容量/)).toBeNull();
    expect(screen.queryByText(/剩余/)).toBeNull();
  });

  // 下面三条是 fix round 1 的回归测试：I-1（写操作后的重拉要用最新月份）
  // 与 M-1（节点列表要随项目选择失效）。
  // 放在 describe 末尾：`vi.clearAllMocks()` 不清 implementation，
  // 用例之间的实现覆盖只能靠顺序解决。

  it("写操作后的重拉用最新月份，不把旧月份的数据写回面板", async () => {
    // 12 月的数据：两个空周，和 11 月的周块没有任何交集。
    const detailDec = {
      person_id: 1,
      month: "2026-12",
      monthly_capacity: 30,
      used_days: 0,
      over_days: null,
      remaining_days: null,
      reviewed: false,
      weeks: [
        { week: "2026-12-07", week_end: "2026-12-13", total_days: 0, reviewed: false, allocations: [] },
        { week: "2026-12-14", week_end: "2026-12-20", total_days: 0, reviewed: false, allocations: [] },
      ],
      assignments: [],
      projects: [],
    };
    // 记下每次拉的是哪个月：写操作后的重拉必须是「当前」月份（2026-12）。
    const months: string[] = [];
    getPersonMonth.mockImplementation((_p: number, m: string) => {
      months.push(m);
      return Promise.resolve(m === "2026-11" ? detailFixture : detailDec);
    });
    // 写请求挂住，好让我们在它飞行途中把月份切到 12 月。
    let releaseWrite: (v?: unknown) => void = () => {};
    setWeekReview.mockImplementation(
      () => new Promise<unknown>((res) => { releaseWrite = res; }),
    );

    // 这里不能用 renderPanel()：它把 month 钉死在 2026-11。
    const { rerender } = render(
      <PersonMonthPanel personId={1} month="2026-11" archived={false} onChanged={() => {}} />,
    );
    const novBlock = await screen.findByTestId("week-2026-11-02");
    fireEvent.click(within(novBlock).getByRole("checkbox"));
    expect(setWeekReview).toHaveBeenCalledWith(1, "2026-11-02", false);

    // 写请求还在飞，父组件把月份切到 12 月。
    rerender(
      <PersonMonthPanel personId={1} month="2026-12" archived={false} onChanged={() => {}} />,
    );
    await screen.findByTestId("week-2026-12-07");

    releaseWrite();
    await waitFor(() => expect(getPersonMonth).toHaveBeenCalledTimes(3));
    // 第三次拉必须是 12 月。旧实现捕获的是点击那刻的 load 闭包，
    // 会拉回 11 月（months = ["2026-11", "2026-12", "2026-11"]）。
    expect(months).toEqual(["2026-11", "2026-12", "2026-12"]);
    // 面板还得停在 12 月，不能被旧月份的数据顶回来。
    expect(screen.queryByTestId("week-2026-11-02")).toBeNull();

    // 复位：clearAllMocks 不清 implementation。
    setWeekReview.mockResolvedValue(undefined);
  });

  it("关掉再打开新增分配表单，节点下拉不许残留上一轮的节点", async () => {
    getPersonMonth.mockResolvedValue(detailFixture);
    listProjects.mockResolvedValue([{ id: 1, name: "贵州矿产预测" }]);
    listMilestones.mockResolvedValue([msFixture(100, 1, "阶段一")]);
    renderPanel();
    const block = await screen.findByTestId("week-2026-11-02");
    fireEvent.click(within(block).getByRole("button", { name: /新增分配/ }));
    // 项目下拉要等项目列表加载完才有得选。
    await waitFor(() =>
      expect(
        Array.from(
          (within(block).getByLabelText("新增分配项目") as HTMLSelectElement).options,
        ).map((o) => o.value),
      ).toContain("1"),
    );

    fireEvent.change(within(block).getByLabelText("新增分配项目"), { target: { value: "1" } });
    await waitFor(() =>
      expect(within(block).getByLabelText("新增分配节点").textContent).toContain("阶段一"),
    );

    // 关掉表单：按钮文案在开合两态都是「+ 新增分配」。
    fireEvent.click(within(block).getByRole("button", { name: /新增分配/ }));
    // 再打开：项目回到「请选择」，节点也必须一起清空。
    fireEvent.click(within(block).getByRole("button", { name: /新增分配/ }));
    expect(within(block).getByLabelText("新增分配节点").textContent).not.toContain("阶段一");
  });

  it("快速切换项目时节点列表只认最后一次选择", async () => {
    getPersonMonth.mockResolvedValue(detailFixture);
    listProjects.mockResolvedValue([{ id: 1, name: "项目A" }, { id: 2, name: "项目B" }]);
    // A 的请求拖到测试自己释放，B 立即返回。
    let releaseA: (v: unknown) => void = () => {};
    listMilestones.mockImplementation((pid: number) =>
      pid === 1
        ? new Promise<unknown>((res) => { releaseA = res; })
        : Promise.resolve([msFixture(102, 2, "B阶段")]),
    );
    renderPanel();
    const block = await screen.findByTestId("week-2026-11-02");
    fireEvent.click(within(block).getByRole("button", { name: /新增分配/ }));
    await waitFor(() =>
      expect(
        Array.from(
          (within(block).getByLabelText("新增分配项目") as HTMLSelectElement).options,
        ).map((o) => o.value),
      ).toContain("2"),
    );

    // 先选 A（挂住），立刻选 B（立即返回）。
    fireEvent.change(within(block).getByLabelText("新增分配项目"), { target: { value: "1" } });
    fireEvent.change(within(block).getByLabelText("新增分配项目"), { target: { value: "2" } });
    await waitFor(() =>
      expect(within(block).getByLabelText("新增分配节点").textContent).toContain("B阶段"),
    );

    // A 的响应这时才到——已经晚了一步，应当被丢弃。
    releaseA([msFixture(101, 1, "A阶段")]);
    await new Promise((r) => setTimeout(r, 0));
    expect(within(block).getByLabelText("新增分配节点").textContent).not.toContain("A阶段");
  });
});
