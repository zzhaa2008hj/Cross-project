import { useSearchParams } from "react-router-dom";
import { currentMonth } from "./month";

/** 月份参数只认 YYYY-MM；别的写法（手改的 URL、脏链接）一律回退当前月。 */
const MONTH_RE = /^\d{4}-\d{2}$/;

/**
 * 人员页共用的选月来源：URL 上的 ?month=，缺省为当前月（Asia/Shanghai）。
 * 非法月份回退当前月，不把脏参数透传给后端；写回时保留 ?person= 等其它参数。
 */
export function useMonthParam(): [string, (month: string) => void] {
  const [params, setParams] = useSearchParams();
  const raw = params.get("month");
  const month = raw !== null && MONTH_RE.test(raw) ? raw : currentMonth();
  const setMonth = (next: string) => {
    const p = new URLSearchParams(params);
    p.set("month", next);
    setParams(p);
  };
  return [month, setMonth];
}
