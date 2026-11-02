// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import RescheduleDialog from "./RescheduleDialog";
import { ApiError } from "../api";

const previewReschedule = vi.fn();
const applyReschedule = vi.fn();

vi.mock("../api", () => {
  class MockApiError extends Error {
    status: number;
    detail: string;
    constructor(status: number, detail: string) {
      super(detail);
      this.status = status;
      this.detail = detail;
    }
  }
  return {
    api: {
      previewReschedule: (...args: unknown[]) => previewReschedule(...args),
      applyReschedule: (...args: unknown[]) => applyReschedule(...args),
    },
    ApiError: MockApiError,
  };
});

const milestone = {
  id: 7,
  name: "节点一",
  project_id: 1,
  state: "not_started",
  start_date: "2026-11-02",
  commit_date: "2026-11-13",
  version: 1,
  assignee_id: null,
  buffer: {},
  predecessor_ids: [],
};

const preview = {
  preview_id: 11,
  mode: "current",
  versions: { "7": 1 },
  buffer: { status: "ok", buffer_days: 3, internal_target: "2026-11-10", consumable: true, warnings: [] },
  changes: [
    {
      milestone_id: 7,
      name: "节点一",
      state: "not_started",
      old_start_date: "2026-11-02",
      new_start_date: "2026-11-04",
      old_commit_date: "2026-11-13",
      new_commit_date: "2026-11-15",
      note: "",
    },
  ],
  affected_not_modified: [],
};

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("改期预览失效", () => {
  it("日期输入变化后旧预览作废，不能直接提交旧 preview_id", async () => {
    previewReschedule.mockResolvedValue(preview);
    render(
      <RescheduleDialog milestone={milestone as never} onClose={() => {}} onApplied={() => {}} />,
    );

    fireEvent.change(screen.getByLabelText(/新承诺日/), { target: { value: "2026-11-20" } });
    fireEvent.click(screen.getByText("生成预览"));
    await waitFor(() => expect(screen.getByText("确认改期")).toBeTruthy());

    fireEvent.change(screen.getByLabelText(/新承诺日/), { target: { value: "2026-11-25" } });

    expect(screen.queryByText("确认改期")).toBeNull();
  });

  it("开始日变化后旧预览同样作废", async () => {
    previewReschedule.mockResolvedValue(preview);
    render(
      <RescheduleDialog milestone={milestone as never} onClose={() => {}} onApplied={() => {}} />,
    );

    fireEvent.change(screen.getByLabelText(/新开始日/), { target: { value: "2026-11-05" } });
    fireEvent.click(screen.getByText("生成预览"));
    await waitFor(() => expect(screen.getByText("确认改期")).toBeTruthy());

    fireEvent.change(screen.getByLabelText(/新开始日/), { target: { value: "2026-11-06" } });

    expect(screen.queryByText("确认改期")).toBeNull();
  });
});

describe("改期预览非法日期提示（IMP-1）", () => {
  it("预览被拒时展示可读原因，不出现未捕获异常", async () => {
    previewReschedule.mockRejectedValue(
      new ApiError(400, "非法日期：节点「节点一」开始日晚于承诺日，整笔拒绝"),
    );
    render(
      <RescheduleDialog milestone={milestone as never} onClose={() => {}} onApplied={() => {}} />,
    );

    fireEvent.change(screen.getByLabelText(/新开始日/), { target: { value: "2026-11-20" } });
    fireEvent.click(screen.getByText("生成预览"));

    await waitFor(() =>
      expect(screen.getByRole("alert").textContent).toContain("开始日晚于承诺日"),
    );
    // 被拒后不得出现可提交入口
    expect(screen.queryByText("确认改期")).toBeNull();
  });

  it("提交阶段被拒时同样展示可读原因", async () => {
    previewReschedule.mockResolvedValue(preview);
    applyReschedule.mockRejectedValue(
      new ApiError(400, "非法日期：节点「节点一」开始日晚于承诺日，整笔拒绝"),
    );
    render(
      <RescheduleDialog milestone={milestone as never} onClose={() => {}} onApplied={() => {}} />,
    );

    fireEvent.click(screen.getByText("生成预览"));
    await waitFor(() => expect(screen.getByText("确认改期")).toBeTruthy());

    fireEvent.change(screen.getByLabelText(/改期原因/), { target: { value: "客户原因" } });
    fireEvent.click(screen.getByText("确认改期"));

    await waitFor(() =>
      expect(screen.getByRole("alert").textContent).toContain("开始日晚于承诺日"),
    );
  });
});
