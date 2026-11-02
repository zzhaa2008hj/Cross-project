import { describe, expect, it } from "vitest";
import {
  bufferWarnings,
  describeBuffer,
  isTerminal,
  milestoneStateLabel,
  projectStateLabel,
} from "./labels";

describe("状态标签", () => {
  it("项目四态", () => {
    expect(projectStateLabel("active")).toBe("进行中");
    expect(projectStateLabel("on-hold")).toBe("暂停");
    expect(projectStateLabel("done")).toBe("已完成");
    expect(projectStateLabel("maintenance")).toBe("维护期");
  });

  it("节点六态", () => {
    expect(milestoneStateLabel("外部阻塞")).toBe("外部阻塞");
    expect(milestoneStateLabel("内部资源阻塞")).toBe("内部资源阻塞");
    expect(milestoneStateLabel("进行中")).toBe("进行中");
    expect(milestoneStateLabel("未开始")).toBe("未开始");
    expect(milestoneStateLabel("已完成")).toBe("已完成");
    expect(milestoneStateLabel("已取消")).toBe("已取消");
  });

  it("终态判定", () => {
    expect(isTerminal("已完成")).toBe(true);
    expect(isTerminal("已取消")).toBe(true);
    expect(isTerminal("进行中")).toBe(false);
  });
});

describe("缓冲摘要", () => {
  it("内部缓冲显示工作日与内部目标", () => {
    const text = describeBuffer({
      status: "ok",
      window_workdays: 10,
      buffer_days: 2,
      internal_target: "2026-11-11",
      consumable: true,
    });
    expect(text).toContain("W10");
    expect(text).toContain("2026-11-11");
  });

  it("外部缓冲标注不可消费", () => {
    const text = describeBuffer({
      status: "ok",
      window_workdays: 10,
      buffer_days: 2,
      internal_target: null,
      consumable: false,
    });
    expect(text).toContain("不可消费");
  });

  it("缺日期时提示待确认", () => {
    const text = describeBuffer({
      status: "待确认",
      window_workdays: null,
      buffer_days: null,
      internal_target: null,
      consumable: false,
      reason: "缺开始日",
    });
    expect(text).toContain("待确认");
    expect(bufferWarnings({
      status: "待确认",
      window_workdays: null,
      buffer_days: null,
      internal_target: null,
      consumable: false,
    })).toContain("日期缺失，待确认");
  });
});
