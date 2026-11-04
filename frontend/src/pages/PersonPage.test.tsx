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
const listMilestones = vi.fn();
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
    listMilestones: (...args: unknown[]) => listMilestones(...args),
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

// 「本月分配」标签页用的月度明细：5 个周块，其中 11-23 / 11-30 两周未核对。
// 周块标题是纯文本节点（周区间那处不许套 <span>），否则 getByText 匹配不到整串。
const detailFixture = {
  person_id: 1,
  month: "2026-11",
  monthly_capacity: 30,
  used_days: 18.5,
  over_days: null,
  remaining_days: 11.5,
  reviewed: true,
  weeks: [
    { week: "2026-11-02", week_end: "2026-11-08", total_days: 10, reviewed: true, allocations: [] },
    { week: "2026-11-09", week_end: "2026-11-15", total_days: 8.5, reviewed: true, allocations: [] },
    { week: "2026-11-16", week_end: "2026-11-22", total_days: 0, reviewed: true, allocations: [] },
    { week: "2026-11-23", week_end: "2026-11-29", total_days: 0, reviewed: false, allocations: [] },
    { week: "2026-11-30", week_end: "2026-12-06", total_days: 0, reviewed: false, allocations: [] },
  ],
  assignments: [],
  projects: [],
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

  it("选中某人后默认停在「本月分配」标签页", async () => {
    listMonthlyRoster.mockResolvedValue(rosterActive);
    getPersonMonth.mockResolvedValue(detailFixture);
    renderPage();
    fireEvent.click(await screen.findByText("傅相杰"));

    // 选中态只能直接断言 aria-selected 属性：aria-selected 不是 getByRole 的合法选项键
    // （写进 options 会被静默忽略，形成假阳性断言），而 role="tab" 又让 getByRole("button")
    // 再也找不到这三个按钮。
    expect(screen.getByRole("tab", { name: "本月分配" }).getAttribute("aria-selected")).toBe("true");
    expect(screen.getByRole("tab", { name: "资料" }).getAttribute("aria-selected")).toBe("false");
    // 默认标签页已经把面板渲染出来了：第一周块的周区间是纯文本节点（别在里面插 <span>）。
    // 注意：面板是挂载后异步拉 getPersonMonth 的，fireEvent.click 不排空微任务队列，
    // 所以这里必须用等待式查询，同步查询看不到还没回来的数据。
    expect(await screen.findByText("11-02 ~ 11-08")).toBeTruthy();
  });

  it("两个标签页可切换", async () => {
    listMonthlyRoster.mockResolvedValue(rosterActive);
    getPersonMonth.mockResolvedValue(detailFixture);
    renderPage();
    fireEvent.click(await screen.findByText("傅相杰"));

    fireEvent.click(screen.getByRole("tab", { name: "资料" }));
    // getByLabelText **不过滤 hidden 元素**，而资料面板是常驻挂载 + hidden 切页：
    // 旧的 getByLabelText("默认周容量") 在切页前后都能命中，等于没断言。
    // 改成「选中态」+「可见性」两条（getByRole 默认排除 hidden 元素）。
    expect(screen.getByRole("tab", { name: "资料" }).getAttribute("aria-selected")).toBe("true");
    // type="number" 的 ARIA role 是 spinbutton，不是 textbox。
    expect(screen.getByRole("spinbutton", { name: "默认周容量" })).toBeTruthy();
  });

  it("未全部核对时汇总条显示「待核对」", async () => {
    // 汇总条读的是 roster 行，所以「待核对」要打在 roster 上，打在 detailFixture 上没用
    listMonthlyRoster.mockResolvedValue({
      ...rosterActive,
      people: [{ ...rosterActive.people[0], remaining_days: null, reviewed: false }],
    });
    // 默认标签页是「本月分配」，面板一挂载就调 getPersonMonth——不 mock 的话它拿到
    // undefined，渲染时 .weeks 直接抛错，那条「待核对」断言就永远等不到
    getPersonMonth.mockResolvedValue(detailFixture);
    renderPage();
    fireEvent.click(await screen.findByText("傅相杰"));
    // 页面上有 4 处「待核对」（汇总条 1 + 表格单元格 1 + 未核对周块 2）：
    // 不能用 findByText（多匹配直接抛错），用 findAllByText 再挑出汇总条那一条——
    // 只有它的 textContent 含「核定」字样，逐周的是独立 span，文本就两字。
    const hits = await screen.findAllByText(/待核对/);
    expect(hits.length).toBeGreaterThanOrEqual(1);
    expect(hits.some((el) => (el.textContent ?? "").includes("核定"))).toBe(true);
    // 逐字契约（待核对分支）：汇总条是唯一一个含「核定」的命中，它的 textContent 就是整串。
    expect(hits.map((el) => el.textContent)).toContain(
      "傅相杰 · 核定 30 人天 · 本月已用 18.5 · 待核对 · 2026年11月",
    );
  });

  it("资料标签页保存调 updatePerson 且带 weekly_capacity", async () => {
    listMonthlyRoster.mockResolvedValue(rosterActive);
    getPersonMonth.mockResolvedValue(detailFixture);
    renderPage();
    fireEvent.click(await screen.findByText("傅相杰"));
    fireEvent.click(screen.getByRole("tab", { name: "资料" }));

    // 「默认周容量」允许留空（= 未知），提交时转成数字或 null
    fireEvent.change(screen.getByLabelText("默认周容量"), { target: { value: "6" } });
    fireEvent.click(screen.getByRole("button", { name: "保存资料" }));

    expect(updatePerson).toHaveBeenCalledWith(
      rosterActive.people[0].person_id,
      expect.objectContaining({ weekly_capacity: 6 }),
    );
  });

  it("本月分配标签页加载失败时显示错误信息", async () => {
    listMonthlyRoster.mockResolvedValue(rosterActive);
    getPersonMonth.mockRejectedValue(new Error("服务器 500"));
    renderPage();
    fireEvent.click(await screen.findByText("傅相杰"));
    // errorMessage(new Error("服务器 500")) 返回 "Error: 服务器 500"，正则匹配即可
    expect(await screen.findByText(/服务器 500/)).toBeTruthy();
  });

  it("汇总条文本逐字符合契约（剩余分支）", async () => {
    listMonthlyRoster.mockResolvedValue(rosterActive);
    getPersonMonth.mockResolvedValue(detailFixture);
    renderPage();
    fireEvent.click(await screen.findByText("傅相杰"));
    // summaryText 是单个模板字面量 ⇒ 渲染成**一个**文本节点，getByText 精确匹配可命中。
    expect(
      await screen.findByText("傅相杰 · 核定 30 人天 · 本月已用 18.5 · 剩余 11.5 · 2026年11月"),
    ).toBeTruthy();
  });

  it("roster 重拉后资料表单重置为服务端新值（编辑弹窗保存触发 reload）", async () => {
    getPersonMonth.mockResolvedValue(detailFixture);
    // vi.clearAllMocks() 不清 implementation ⇒ 用调用计数自己分派：
    // 第 1 次 roster = 核定 30；第 2 次（编辑弹窗保存 ⇒ onSaved ⇒ reload）= 核定 40。
    let rosterCall = 0;
    listMonthlyRoster.mockImplementation(() => {
      rosterCall += 1;
      return Promise.resolve({
        ...rosterActive,
        people: [{ ...rosterActive.people[0], monthly_capacity: rosterCall <= 1 ? 30 : 40 }],
      });
    });
    renderPage();
    fireEvent.click(await screen.findByText("傅相杰"));
    fireEvent.click(screen.getByRole("tab", { name: "资料" }));
    // 初值 = 服务端 30。
    expect((screen.getByRole("spinbutton", { name: "核定人天" }) as HTMLInputElement).value).toBe("30");

    // 编辑弹窗保存 ⇒ onSaved ⇒ reload ⇒ roster 重拉：person_id 不变 ⇒ key 不变 ⇒ 组件不重挂载。
    fireEvent.click(screen.getByRole("button", { name: "编辑" }));
    fireEvent.click(screen.getByRole("button", { name: "保存" }));
    // 等弹窗卸掉，否则「核定人天」会同时命中弹窗与资料面板两个 spinbutton。
    await waitFor(() => expect(screen.queryByRole("heading", { name: "编辑 · 傅相杰" })).toBeNull());

    // 快照变了且表单没 dirty ⇒ 输入框重新 seed 成服务端新值 40（旧实现会留着 30）。
    await waitFor(() =>
      expect((screen.getByRole("spinbutton", { name: "核定人天" }) as HTMLInputElement).value).toBe("40"),
    );

    // 保存资料必须带**新**值 40，而不是组件里残留的旧值 30。
    fireEvent.click(screen.getByRole("button", { name: "保存资料" }));
    await waitFor(() =>
      expect(updatePerson).toHaveBeenLastCalledWith(
        rosterActive.people[0].person_id,
        expect.objectContaining({ monthly_capacity: 40 }),
      ),
    );
  });

  it("资料表单有未保存修改时 roster 重拉不覆盖用户输入", async () => {
    getPersonMonth.mockResolvedValue(detailFixture);
    let rosterCall = 0;
    listMonthlyRoster.mockImplementation(() => {
      rosterCall += 1;
      return Promise.resolve({
        ...rosterActive,
        people: [{ ...rosterActive.people[0], monthly_capacity: rosterCall <= 1 ? 30 : 40 }],
      });
    });
    renderPage();
    fireEvent.click(await screen.findByText("傅相杰"));
    fireEvent.click(screen.getByRole("tab", { name: "资料" }));
    // 用户把核定人天改成 20 但没保存 ⇒ dirty。
    fireEvent.change(screen.getByRole("spinbutton", { name: "核定人天" }), { target: { value: "20" } });
    expect((screen.getByRole("spinbutton", { name: "核定人天" }) as HTMLInputElement).value).toBe("20");

    // 触发 roster 重拉（值变成 40）：用「显示已禁用」开关，避免弹窗与面板的 spinbutton 撞名。
    fireEvent.click(screen.getByLabelText("显示已禁用"));
    // 汇总条已经反映服务端新值 40。
    expect(
      await screen.findByText("傅相杰 · 核定 40 人天 · 本月已用 18.5 · 剩余 11.5 · 2026年11月"),
    ).toBeTruthy();
    // 但表单保留用户未保存的 20，不被服务端覆盖（否则「重置」会比原 bug 更糟）。
    expect((screen.getByRole("spinbutton", { name: "核定人天" }) as HTMLInputElement).value).toBe("20");

    // 保存时发的是用户填的 20。
    fireEvent.click(screen.getByRole("button", { name: "保存资料" }));
    await waitFor(() =>
      expect(updatePerson).toHaveBeenLastCalledWith(
        rosterActive.people[0].person_id,
        expect.objectContaining({ monthly_capacity: 20 }),
      ),
    );
  });
});
