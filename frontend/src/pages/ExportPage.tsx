import { useCallback, useEffect, useState } from "react";
import { api, exportPreviewUrl } from "../api";
import { EmptyState, ErrorBanner, InfoBanner, errorMessage } from "../components/common";
import type { ExportPreview, ExportPreviewItem } from "../types";

const TABLE_LABEL: Record<string, string> = {
  projects: "项目",
  milestones: "节点",
  persons: "人员",
  assignments: "分配",
  allocations: "投入",
};

function tableLabel(name: string): string {
  return TABLE_LABEL[name] ?? name;
}

export default function ExportPage() {
  const [preview, setPreview] = useState<ExportPreview | null>(null);
  const [history, setHistory] = useState<ExportPreviewItem[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    try {
      const res = await api.listExportPreviews();
      setHistory(res.items);
    } catch (e) {
      setError(errorMessage(e));
      setHistory([]);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  async function generate() {
    setError(null);
    setBusy(true);
    try {
      const res = await api.createExportPreview();
      setPreview(res);
      await load();
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="page">
      <h2>导出预览</h2>

      <InfoBanner message="本预览只读取软件数据库，不会写回 vault 笔记或脚本。" />

      <ErrorBanner error={error} />

      <div className="actions">
        <button type="button" onClick={generate} disabled={busy}>
          {busy ? "生成中…" : "生成导出预览"}
        </button>
      </div>

      {preview ? (
        <div className="panel">
          <h3>本次预览</h3>
          <dl>
            <dt>快照版本</dt>
            <dd>{preview.snapshot_id}</dd>
            <dt>生成时间</dt>
            <dd>{preview.generated_at}</dd>
          </dl>

          <h4>各表行数</h4>
          {Object.keys(preview.counts).length === 0 ? (
            <EmptyState text="没有可导出的数据" />
          ) : (
            <ul className="counts">
              {Object.entries(preview.counts).map(([name, count]) => (
                <li key={name}>{`${tableLabel(name)}：${count}`}</li>
              ))}
            </ul>
          )}

          <h4>与上次预览的差异</h4>
          {preview.diff.is_first ? (
            <p className="muted">首次预览，全部数据记作新增。</p>
          ) : (
            <table className="table">
              <thead>
                <tr>
                  <th>表</th>
                  <th>新增</th>
                  <th>修改</th>
                  <th>删除</th>
                </tr>
              </thead>
              <tbody>
                {Object.entries(preview.diff.tables).map(([name, stat]) => (
                  <tr key={name}>
                    <td>{tableLabel(name)}</td>
                    <td>
                      <span>{`新增 ${stat.added}`}</span>
                    </td>
                    <td>
                      <span>{`修改 ${stat.changed}`}</span>
                    </td>
                    <td>
                      <span>{`删除 ${stat.removed}`}</span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}

          <h4>下载</h4>
          <ul className="downloads">
            <li>
              <a href={exportPreviewUrl(preview.preview_id, "json")} download>
                下载 JSON
              </a>
            </li>
            <li>
              <a href={exportPreviewUrl(preview.preview_id, "markdown")} download>
                下载 Markdown
              </a>
            </li>
            <li>
              <a href={exportPreviewUrl(preview.preview_id, "obsidian")} download>
                下载 Obsidian 摘要
              </a>
            </li>
          </ul>
        </div>
      ) : (
        <EmptyState text="还没有生成过预览" />
      )}

      <h3>历史预览</h3>
      {history === null ? (
        <p className="muted">加载中…</p>
      ) : history.length === 0 ? (
        <EmptyState text="暂无历史预览" />
      ) : (
        <ul className="history">
          {history.map((item) => (
            <li key={item.preview_id}>
              {item.generated_at} · {item.snapshot_id}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
