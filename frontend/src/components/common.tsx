import type { ReactNode } from "react";

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
