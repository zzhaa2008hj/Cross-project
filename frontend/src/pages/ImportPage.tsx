import { useCallback, useEffect, useState } from "react";
import { api, ApiError } from "../api";
import { EmptyState, ErrorBanner, Field, Loading } from "../components/common";
import type { ImportReport } from "../types";

const STATUS_LABEL: Record<string, string> = {
  import: "导入",
  skip: "跳过",
  fail: "失败",
};

export default function ImportPage() {
  const [runs, setRuns] = useState<ImportReport[] | null>(null);
  const [selected, setSelected] = useState<ImportReport | null>(null);
  const [sourceRoot, setSourceRoot] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    setError(null);
    try {
      const rows = await api.listImports();
      setRuns(rows);
      if (rows.length > 0) setSelected((cur) => cur ?? rows[0]);
    } catch (e) {
      setError(e instanceof ApiError ? e.detail : String(e));
      setRuns([]);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  async function run(apply: boolean) {
    setError(null);
    setMessage(null);
    setBusy(true);
    try {
      const report = await api.runImport({
        source_root: sourceRoot.trim() || null,
        apply,
      });
      setSelected(report);
      setMessage(
        apply
          ? `已执行导入（快照 ${report.snapshot_hash.slice(0, 12)}…）`
          : `已完成 dry-run（未写库，快照 ${report.snapshot_hash.slice(0, 12)}…）`,
      );
      await load();
    } catch (e) {
      setError(e instanceof ApiError ? e.detail : String(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <section>
      <div className="page-head">
        <h1>只读源导入报告</h1>
      </div>

      <ErrorBanner error={error} />
      {message ? <p className="banner banner-ok">{message}</p> : null}

      <form
        className="card form-grid"
        onSubmit={(e) => {
          e.preventDefault();
          void run(false);
        }}
      >
        <Field label="源目录" hint="留空使用配置的 vault 目录">
          <input
            value={sourceRoot}
            onChange={(e) => setSourceRoot(e.target.value)}
            placeholder="例如：/home/hui/MyData/AI/my-vault"
          />
        </Field>
        <div className="form-actions">
          <button type="submit" disabled={busy}>
            {busy ? "运行中…" : "Dry-run（不写库）"}
          </button>
          <button type="button" className="ghost" disabled={busy} onClick={() => void run(true)}>
            正式导入
          </button>
        </div>
      </form>

      <div className="card">
        <h3>导入记录</h3>
        {runs === null ? (
          <Loading />
        ) : runs.length === 0 ? (
          <EmptyState text="暂无导入记录。" />
        ) : (
          <table className="table">
            <thead>
              <tr>
                <th>#</th>
                <th>模式</th>
                <th>快照</th>
                <th>读取</th>
                <th>导入</th>
                <th>跳过</th>
                <th>失败</th>
                <th>时间</th>
              </tr>
            </thead>
            <tbody>
              {runs.map((r) => (
                <tr
                  key={r.id}
                  className={selected?.id === r.id ? "row-selected" : undefined}
                  onClick={() => setSelected(r)}
                >
                  <td>{r.id}</td>
                  <td>{r.applied ? "正式导入" : "dry-run"}</td>
                  <td className="mono">{r.snapshot_hash.slice(0, 12)}…</td>
                  <td>{r.read_count}</td>
                  <td>{r.imported_count}</td>
                  <td>{r.skipped_count}</td>
                  <td>{r.failed_count}</td>
                  <td className="muted">{r.created_at?.slice(0, 19).replace("T", " ")}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {selected ? (
        <div className="card">
          <h3>报告详情 #{selected.id}</h3>
          <p className="muted">
            快照哈希 <span className="mono">{selected.snapshot_hash}</span>
          </p>

          <h4>源文件定位</h4>
          <table className="table">
            <thead>
              <tr>
                <th>相对路径</th>
                <th>字节</th>
                <th>行数</th>
                <th>sha256</th>
              </tr>
            </thead>
            <tbody>
              {selected.sources.map((s) => (
                <tr key={s.rel}>
                  <td className="mono">{s.rel}</td>
                  <td>{s.bytes}</td>
                  <td>{s.lines}</td>
                  <td className="mono">{s.sha256?.slice(0, 16)}…</td>
                </tr>
              ))}
            </tbody>
          </table>

          <h4>记录与映射</h4>
          <table className="table">
            <thead>
              <tr>
                <th>类型</th>
                <th>来源</th>
                <th>结果</th>
                <th>说明</th>
                <th>映射</th>
              </tr>
            </thead>
            <tbody>
              {selected.records.map((r, i) => (
                <tr key={`${r.source_ref}-${i}`}>
                  <td>{r.kind}</td>
                  <td className="mono">{r.source_ref}</td>
                  <td>{STATUS_LABEL[r.status] ?? r.status}</td>
                  <td className="muted">{r.reason || "—"}</td>
                  <td className="muted mono">
                    {Object.entries(r.mapping ?? {})
                      .map(([k, v]) => `${k}→${v}`)
                      .join("，") || "—"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>

          {selected.diffs.length > 0 ? (
            <>
              <h4>与库内现有值的差异</h4>
              <table className="table">
                <thead>
                  <tr>
                    <th>对象</th>
                    <th>字段</th>
                    <th>库内值</th>
                    <th>源值</th>
                  </tr>
                </thead>
                <tbody>
                  {selected.diffs.map((d, i) => (
                    <tr key={i}>
                      <td>{d.key ?? d.kind ?? "—"}</td>
                      <td>{d.field}</td>
                      <td>{d.old_value ?? "—"}</td>
                      <td>{d.new_value ?? "—"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </>
          ) : null}

          {selected.pending.length > 0 ? (
            <>
              <h4>待确认清单（保留原值）</h4>
              <table className="table">
                <thead>
                  <tr>
                    <th>来源</th>
                    <th>字段</th>
                    <th>原值</th>
                    <th>原因</th>
                  </tr>
                </thead>
                <tbody>
                  {selected.pending.map((p, i) => (
                    <tr key={i}>
                      <td className="mono">{p.ref}</td>
                      <td>{p.field}</td>
                      <td>{p.raw}</td>
                      <td className="muted">{p.reason}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </>
          ) : null}

          <h4>对账</h4>
          <ul className="list">
            {Object.entries(selected.reconciliation ?? {}).map(([k, v]) => (
              <li key={k}>
                {k}：{String(v)}
              </li>
            ))}
          </ul>

          <h4>Markdown 报告</h4>
          <pre className="report">{selected.report_markdown}</pre>
        </div>
      ) : null}
    </section>
  );
}
