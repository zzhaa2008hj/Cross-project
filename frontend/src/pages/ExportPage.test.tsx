// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import ExportPage from "./ExportPage";

const createExportPreview = vi.fn();
const listExportPreviews = vi.fn();

vi.mock("../api", () => ({
  api: {
    createExportPreview: (...args: unknown[]) => createExportPreview(...args),
    listExportPreviews: (...args: unknown[]) => listExportPreviews(...args),
  },
  ApiError: class extends Error {},
  exportPreviewUrl: (previewId: string, kind: string) =>
    `/api/export/previews/${previewId}/${kind}`,
}));

const preview = {
  preview_id: "prev-20261102T100000Z-abc123",
  generated_at: "2026-11-02T10:00:00Z",
  snapshot_id: "snap-abc123",
  counts: { projects: 3, milestones: 12 },
  diff: {
    is_first: false,
    tables: {
      projects: { added: 2, changed: 1, removed: 0, ids: [] },
    },
  },
  markdown: "# 跨项目管理软件导出",
  obsidian: "# 跨项目管理软件摘要",
};

function setup() {
  listExportPreviews.mockResolvedValue({ items: [] });
  createExportPreview.mockResolvedValue(preview);
  return render(<ExportPage />);
}

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("导出预览页", () => {
  it("点击生成后展示快照版本与行数", async () => {
    setup();

    fireEvent.click(screen.getByRole("button", { name: "生成导出预览" }));

    await waitFor(() => expect(screen.getByText(/snap-abc123/)).toBeTruthy());
    expect(screen.getByText("项目：3")).toBeTruthy();
    expect(screen.getByText("节点：12")).toBeTruthy();
  });

  it("展示与上次预览的差异", async () => {
    setup();

    fireEvent.click(screen.getByRole("button", { name: "生成导出预览" }));

    await waitFor(() => expect(screen.getByText(/snap-abc123/)).toBeTruthy());
    expect(screen.getByText("新增 2")).toBeTruthy();
    expect(screen.getByText("修改 1")).toBeTruthy();
    expect(screen.getByText("删除 0")).toBeTruthy();
  });

  it("提供 JSON/Markdown/Obsidian 摘要三个下载入口", async () => {
    setup();

    fireEvent.click(screen.getByRole("button", { name: "生成导出预览" }));

    await waitFor(() => expect(screen.getByText(/snap-abc123/)).toBeTruthy());
    const json = screen.getByRole("link", { name: "下载 JSON" });
    const markdown = screen.getByRole("link", { name: "下载 Markdown" });
    const obsidian = screen.getByRole("link", { name: "下载 Obsidian 摘要" });
    expect(json.getAttribute("href")).toBe(
      "/api/export/previews/prev-20261102T100000Z-abc123/json",
    );
    expect(markdown.getAttribute("href")).toBe(
      "/api/export/previews/prev-20261102T100000Z-abc123/markdown",
    );
    expect(obsidian.getAttribute("href")).toBe(
      "/api/export/previews/prev-20261102T100000Z-abc123/obsidian",
    );
  });

  it("提示预览不写回 vault", () => {
    setup();

    expect(screen.getByText(/不会写回 vault/)).toBeTruthy();
  });

  it("接口失败时显示错误", async () => {
    listExportPreviews.mockResolvedValue({ items: [] });
    createExportPreview.mockRejectedValue(new Error("生成预览失败"));
    render(<ExportPage />);

    fireEvent.click(screen.getByRole("button", { name: "生成导出预览" }));

    await waitFor(() => expect(screen.getByRole("alert").textContent).toContain("生成预览失败"));
  });
});
