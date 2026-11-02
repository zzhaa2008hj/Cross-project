import { useSearchParams } from "react-router-dom";
import { currentWeek } from "./week";

/**
 * 三页共用的选周来源：URL 上的 ?week=，缺省为本周。
 * 工作台 → 项目页 → 人员页传递同一个周键，三页看到的占用是同一份 Allocation。
 */
export function useWeekParam(): [string, (week: string) => void] {
  const [params, setParams] = useSearchParams();
  const week = params.get("week") ?? currentWeek();
  const setWeek = (next: string) => {
    const p = new URLSearchParams(params);
    p.set("week", next);
    setParams(p);
  };
  return [week, setWeek];
}
