// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import RescheduleDialog from "./RescheduleDialog";

const previewReschedule = vi.fn();
const applyReschedule = vi.fn();

vi.mock("../api", () => ({
  api: {
    previewReschedule: (...args: unknown[]) => previewReschedule(...args),
    applyReschedule: (...args: unknown[]) => applyReschedule(...args),
  },
  ApiError: class extends Error {},
}));

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
