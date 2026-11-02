import { describe, expect, it } from "vitest";
import { shiftWeek, weekEnd } from "./week";

describe("周工具", () => {
  it("weekEnd 返回该周的周日（周键 + 6 天），不是六周之后", () => {
    expect(weekEnd("2026-11-02")).toBe("2026-11-08");
    expect(weekEnd("2026-11-02")).not.toBe(shiftWeek("2026-11-02", 6));
  });

  it("weekEnd 跨月周仍落在周日", () => {
    expect(weekEnd("2026-10-26")).toBe("2026-11-01");
  });
});
