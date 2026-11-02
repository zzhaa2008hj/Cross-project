/** 周键：Asia/Shanghai 时区的周一日期，覆盖周一至周日。 */
const SHANGHAI = "Asia/Shanghai";

function todayInShanghai(): string {
  return new Intl.DateTimeFormat("en-CA", {
    timeZone: SHANGHAI,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).format(new Date());
}

/** 返回所给日期所在周的周一（Asia/Shanghai）。跨年周保持周键不变。 */
export function weekKeyOf(date: string): string {
  const day = new Date(`${date}T00:00:00Z`).getUTCDay();
  const offset = (day + 6) % 7; // 周一=0
  const monday = new Date(`${date}T00:00:00Z`);
  monday.setUTCDate(monday.getUTCDate() - offset);
  return monday.toISOString().slice(0, 10);
}

/** 当前周（Asia/Shanghai）的周键。 */
export function currentWeek(): string {
  return weekKeyOf(todayInShanghai());
}

/** 周键加减若干周（delta 为正向后、为负向前）。 */
export function shiftWeek(week: string, delta: number): string {
  const d = new Date(`${week}T00:00:00Z`);
  d.setUTCDate(d.getUTCDate() + delta * 7);
  return d.toISOString().slice(0, 10);
}
