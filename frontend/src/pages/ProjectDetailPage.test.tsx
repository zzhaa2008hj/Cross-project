// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import ProjectDetailPage from "./ProjectDetailPage";

const getProject = vi.fn();
const listPersons = vi.fn();
const updateProject = vi.fn();
const archiveProject = vi.fn();
const restoreProject = vi.fn();

vi.mock("../api", () => ({
  api: {
    getProject: (...args: unknown[]) => getProject(...args),
    listPersons: (...args: unknown[]) => listPersons(...args),
    updateProject: (...args: unknown[]) => updateProject(...args),
    archiveProject: (...args: unknown[]) => archiveProject(...args),
    restoreProject: (...args: unknown[]) => restoreProject(...args),
    listHistory: () => Promise.resolve([]),
    history: () => Promise.resolve([]),
  },
  ApiError: class extends Error {},
}));

const project = {
  id: 3,
  name: "示例项目",
  state: "active",
  priority: "P1",
  progress: "",
  note: "",
  archived: false,
  current_focus_milestone_id: null,
  milestones: [],
};

function renderPage() {
  return render(
    <MemoryRouter initialEntries={["/projects/3"]}>
      <Routes>
        <Route path="/projects/:projectId" element={<ProjectDetailPage />} />
      </Routes>
    </MemoryRouter>,
  );
}

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("项目归档/恢复", () => {
  it("未归档项目点击归档走归档接口，而不是 PATCH archived 字段", async () => {
    getProject.mockResolvedValue(project);
    listPersons.mockResolvedValue([]);
    archiveProject.mockResolvedValue({ ...project, archived: true });

    renderPage();
    await waitFor(() => expect(screen.getByText("归档项目")).toBeTruthy());

    fireEvent.click(screen.getByText("归档项目"));

    await waitFor(() => expect(archiveProject).toHaveBeenCalledWith(3));
    expect(updateProject).not.toHaveBeenCalled();
  });

  it("已归档项目点击恢复走恢复接口", async () => {
    getProject.mockResolvedValue({ ...project, archived: true });
    listPersons.mockResolvedValue([]);
    restoreProject.mockResolvedValue({ ...project, archived: false });

    renderPage();
    await waitFor(() => expect(screen.getByText("恢复项目")).toBeTruthy());

    fireEvent.click(screen.getByText("恢复项目"));

    await waitFor(() => expect(restoreProject).toHaveBeenCalledWith(3));
    expect(updateProject).not.toHaveBeenCalled();
  });
});
