import type { ReactNode } from "react";

/** 把接口或运行时异常转成可展示的中文提示。 */
export function errorMessage(error: unknown): string {
  if (error && typeof error === "object") {
    const candidate = error as { detail?: unknown; message?: unknown };
    if (typeof candidate.detail === "string" && candidate.detail) return candidate.detail;
    if (typeof candidate.message === "string" && candidate.message) return candidate.message;
  }
  return String(error);
}

export function ErrorBanner({ error }: { error: string | null }) {
  if (!error) return null;
  return (
    <div className="banner banner-error" role="alert">
      {error}
    </div>
  );
}

export function InfoBanner({ message }: { message: string | null }) {
  if (!message) return null;
  return (
    <div className="banner banner-info" role="status">
      {message}
    </div>
  );
}

export function Loading({ text = "加载中…" }: { text?: string }) {
  return <p className="muted">{text}</p>;
}

export function EmptyState({ text }: { text: string }) {
  return <p className="muted empty">{text}</p>;
}

export function Field({
  label,
  children,
  hint,
}: {
  label: string;
  children: ReactNode;
  hint?: string;
}) {
  return (
    <label className="field">
      <span className="field-label">{label}</span>
      {children}
      {hint ? <span className="field-hint">{hint}</span> : null}
    </label>
  );
}
