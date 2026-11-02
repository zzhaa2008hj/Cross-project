import type { BufferInfo, ProjectState } from "./types";

export const PROJECT_STATE_LABEL: Record<ProjectState, string> = {
  active: "进行中",
  "on-hold": "暂停",
  done: "已完成",
  maintenance: "维护期",
};

export const MILESTONE_STATE_LABEL: Record<string, string> = {
  外部阻塞: "外部阻塞",
  内部资源阻塞: "内部资源阻塞",
  进行中: "进行中",
  未开始: "未开始",
  已完成: "已完成",
  已取消: "已取消",
};

export const TERMINAL_STATES = ["已完成", "已取消"];

export const BUFFER_SOURCE_LABEL: Record<string, string> = {
  内部: "内部缓冲",
  外部资源: "外部阻塞",
  外部阻塞: "外部阻塞",
};

export function projectStateLabel(state: string): string {
  return PROJECT_STATE_LABEL[state as ProjectState] ?? state;
}

export function milestoneStateLabel(state: string): string {
  return MILESTONE_STATE_LABEL[state] ?? state;
}

export function isTerminal(state: string): boolean {
  return TERMINAL_STATES.includes(state);
}

/** 缓冲派生结果的可读摘要；只展示后端算好的值，前端不重复推算。 */
export function describeBuffer(buffer: BufferInfo | undefined): string {
  if (!buffer || !buffer.status) return "—";
  if (buffer.status !== "ok") {
    const reason = buffer.reason ? `：${buffer.reason}` : "";
    return `${buffer.status}${reason}`;
  }
  const target = buffer.internal_target ? `，内部目标 ${buffer.internal_target}` : "";
  const consumable = buffer.consumable ? "" : "（外部缓冲不可消费）";
  return `W${buffer.window_workdays} / 缓冲 ${buffer.buffer_days} 天${target}${consumable}`;
}

/** 提示文案：周末承诺日、窗口不足等 */
export function bufferWarnings(buffer: BufferInfo | undefined): string[] {
  if (!buffer) return [];
  const warnings = [...(buffer.warnings ?? [])];
  if (buffer.commit_on_weekend) warnings.push("承诺日落在周末");
  if (buffer.start_after_commit) warnings.push("开始日晚于承诺日");
  if (buffer.status === "窗口不足") warnings.push("窗口不足，无法容纳内部缓冲");
  if (buffer.status === "待确认") warnings.push("日期缺失，待确认");
  return Array.from(new Set(warnings));
}

export function formatDate(value: string | null | undefined): string {
  return value ? value : "—";
}
