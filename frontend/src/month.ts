import { weekKeyOf } from "./week";

/** 月键：Asia/Shanghai 时区的自然月，格式 "YYYY-MM"。 */
const SHANGHAI = "Asia/Shanghai";

/** 上海时区的今天（"YYYY-MM-DD"）。week.ts 里的同名函数是模块私有的，这里自带一份。 */
function todayInShanghai(now?: Date): string {
  return new Intl.DateTimeFormat("en-CA", {
    timeZone: SHANGHAI,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).format(now ?? new Date());
}

/** 某一周所属的月：取该周周一所在月。传入的 week 未必是周一，所以要先归一到周一。 */
export function monthOfWeek(week: string): string {
  return weekKeyOf(week).slice(0, 7);
}

/** 当前月（Asia/Shanghai），格式 "YYYY-MM"。 */
export function currentMonth(now?: Date): string {
  return todayInShanghai(now).slice(0, 7);
}

/** 月份加减若干月（delta 为正向后、为负向前），跨年自动处理。 */
export function shiftMonth(month: string, delta: number): string {
  const [y, m] = month.split("-").map((n) => Number(n));
  // Date.UTC 的月首在 UTC 下恒为 00:00，本地时区/夏令时不会把月首推走。
  const d = new Date(Date.UTC(y, m - 1 + delta, 1));
  return d.toISOString().slice(0, 7);
}

/** 中文月份标签，如 "2026年11月"（月份不补零）。 */
export function monthLabel(month: string): string {
  const [y, m] = month.split("-").map((n) => Number(n));
  return `${y}年${m}月`;
}
