"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useRef,
  useState,
  type ReactNode,
} from "react";
import type { Opt } from "@/lib/options";

/* ── Page header (consistent across every screen) ─────────────────── */
export function PageHeader({
  title,
  subtitle,
  actions,
}: {
  title: string;
  subtitle?: string;
  actions?: ReactNode;
}) {
  return (
    <div className="flex flex-col sm:flex-row sm:items-start sm:justify-between gap-3 mb-7">
      <div>
        <h1 className="text-[21px] sm:text-[22px] font-bold tracking-tight">{title}</h1>
        {subtitle && (
          <p className="text-[var(--muted)] text-[13px] mt-1.5 max-w-xl leading-relaxed">
            {subtitle}
          </p>
        )}
      </div>
      {actions && <div className="flex gap-2 shrink-0 mt-0.5">{actions}</div>}
    </div>
  );
}

/* ── Card ─────────────────────────────────────────────────────────── */
export function Card({
  title,
  desc,
  actions,
  children,
  className = "",
}: {
  title?: string;
  desc?: string;
  actions?: ReactNode;
  children: ReactNode;
  className?: string;
}) {
  return (
    <div className={`card ${className}`}>
      {(title || actions) && (
        <div className="flex flex-col sm:flex-row sm:items-start sm:justify-between gap-3 mb-5">
          <div>
            {title && <div className="card-h">{title}</div>}
            {desc && (
              <p className="text-[var(--muted)] text-[13px] mt-1.5">
                {desc}
              </p>
            )}
          </div>
          {actions && <div className="shrink-0">{actions}</div>}
        </div>
      )}
      {children}
    </div>
  );
}

/* ── KPI stat tile ────────────────────────────────────────────────── */
export function Stat({
  label,
  value,
  hint,
  icon,
  tone = "default",
}: {
  label: string;
  value: ReactNode;
  hint?: string;
  icon?: ReactNode;
  tone?: "default" | "ok" | "warn" | "bad";
}) {
  const valColor =
    tone === "ok"
      ? "var(--ok)"
      : tone === "warn"
        ? "var(--warn)"
        : tone === "bad"
          ? "var(--bad)"
          : "var(--txt)";
  return (
    <div className="card !p-5 flex flex-col gap-3">
      <div className="flex items-center justify-between gap-2">
        <span className="text-[11.5px] font-semibold uppercase tracking-wider text-[var(--faint)]">
          {label}
        </span>
        {icon && (
          <span className="grid place-items-center w-8 h-8 rounded-lg bg-[var(--accent-soft)] text-[var(--accent)] shrink-0">
            {icon}
          </span>
        )}
      </div>
      <div>
        <div
          className="text-[28px] font-bold tracking-tight leading-none"
          style={{ color: valColor }}
        >
          {value}
        </div>
        {hint && (
          <div className="text-[11.5px] text-[var(--faint)] mt-1.5 font-medium">
            {hint}
          </div>
        )}
      </div>
    </div>
  );
}

export function StatGrid({ children }: { children: ReactNode }) {
  return (
    <div className="grid grid-cols-2 lg:grid-cols-4 gap-4 mb-6">
      {children}
    </div>
  );
}

/* ── Form controls ────────────────────────────────────────────────── */
export function Field({
  label,
  hint,
  children,
}: {
  label: string;
  hint?: string;
  children: ReactNode;
}) {
  return (
    <label className="block">
      <span className="label">{label}</span>
      {children}
      {hint && (
        <span className="text-[11px] text-[var(--faint)] mt-1.5 block">
          {hint}
        </span>
      )}
    </label>
  );
}

export function Select({
  value,
  onChange,
  options,
}: {
  value: string;
  onChange: (v: string) => void;
  options: Opt[];
}) {
  return (
    <select
      className="select"
      value={value}
      onChange={(e) => onChange(e.target.value)}
    >
      {options.map((o) => (
        <option key={o.value} value={o.value}>
          {o.label}
        </option>
      ))}
    </select>
  );
}

export function Input(props: React.InputHTMLAttributes<HTMLInputElement>) {
  return <input {...props} className={"input " + (props.className || "")} />;
}

export function Textarea(
  props: React.TextareaHTMLAttributes<HTMLTextAreaElement>
) {
  return (
    <textarea {...props} className={"textarea " + (props.className || "")} />
  );
}

export function Range({
  value,
  min,
  max,
  step,
  onChange,
}: {
  value: number;
  min: number;
  max: number;
  step: number;
  onChange: (v: number) => void;
}) {
  return (
    <div className="flex items-center gap-3">
      <input
        type="range"
        className="flex-1 accent-[var(--accent)] cursor-pointer"
        value={value}
        min={min}
        max={max}
        step={step}
        onChange={(e) => onChange(parseFloat(e.target.value))}
      />
      <input
        type="number"
        className="input w-[88px] text-center"
        value={value}
        min={min}
        max={max}
        step={step}
        onChange={(e) => onChange(parseFloat(e.target.value))}
      />
    </div>
  );
}

export function Check({
  checked,
  onChange,
  label,
}: {
  checked: boolean;
  onChange: (v: boolean) => void;
  label: string;
}) {
  return (
    <button
      type="button"
      onClick={() => onChange(!checked)}
      className="flex items-center gap-2.5 text-[14px] select-none"
    >
      <span
        className="w-5 h-5 rounded-md border grid place-items-center transition-colors shrink-0"
        style={{
          borderColor: checked ? "var(--accent)" : "var(--line)",
          background: checked ? "var(--accent)" : "transparent",
        }}
      >
        {checked && (
          <svg
            width="13"
            height="13"
            viewBox="0 0 24 24"
            fill="none"
            stroke="#fff"
            strokeWidth="3"
            strokeLinecap="round"
            strokeLinejoin="round"
          >
            <path d="M20 6 9 17l-5-5" />
          </svg>
        )}
      </span>
      {label}
    </button>
  );
}

export function Button({
  variant = "default",
  className = "",
  ...p
}: React.ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: "default" | "primary" | "danger" | "ghost";
}) {
  const v =
    variant === "primary"
      ? "btn-primary"
      : variant === "danger"
        ? "btn-danger"
        : variant === "ghost"
          ? "btn-ghost"
          : "";
  return <button {...p} className={`btn ${v} ${className}`} />;
}

export function Badge({
  tone = "default",
  children,
}: {
  tone?: "default" | "ok" | "warn" | "bad" | "info";
  children: ReactNode;
}) {
  const c =
    tone === "ok"
      ? "badge-ok"
      : tone === "warn"
        ? "badge-warn"
        : tone === "bad"
          ? "badge-bad"
          : tone === "info"
            ? "badge-info"
            : "";
  return <span className={`badge ${c}`}>{children}</span>;
}

export function Spinner({ className = "" }: { className?: string }) {
  return (
    <span
      className={
        "inline-block w-4 h-4 border-2 border-current border-t-transparent rounded-full animate-spin opacity-70 " +
        className
      }
    />
  );
}

export function Skeleton({ className = "" }: { className?: string }) {
  return <div className={`skeleton ${className}`} />;
}

export function TableWrap({ children }: { children: ReactNode }) {
  return <div className="tbl-wrap">{children}</div>;
}

export function EmptyState({
  icon,
  title,
  desc,
  action,
}: {
  icon?: ReactNode;
  title: string;
  desc?: string;
  action?: ReactNode;
}) {
  return (
    <div className="text-center py-16 px-4">
      <span className="inline-grid place-items-center w-14 h-14 rounded-2xl bg-[var(--accent-soft)] text-[var(--accent)] mb-4">
        {icon ?? (
          <svg
            width="24"
            height="24"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="2"
            strokeLinecap="round"
            strokeLinejoin="round"
          >
            <circle cx="12" cy="12" r="9" />
            <path d="M12 8v4M12 16h.01" />
          </svg>
        )}
      </span>
      <div className="font-semibold text-[15px]">{title}</div>
      {desc && (
        <p className="text-[var(--muted)] text-[13px] mt-1.5 max-w-sm mx-auto">
          {desc}
        </p>
      )}
      {action && <div className="mt-5">{action}</div>}
    </div>
  );
}

/* ── Progress bar ─────────────────────────────────────────────────── */
export function ProgressBar({
  value,
  max,
  tone = "ok",
}: {
  value: number;
  max: number;
  tone?: "ok" | "warn" | "bad" | "info";
}) {
  const pct = max > 0 ? Math.min(100, Math.round((value / max) * 100)) : 0;
  const col =
    tone === "ok"
      ? "var(--ok)"
      : tone === "warn"
        ? "var(--warn)"
        : tone === "bad"
          ? "var(--bad)"
          : "var(--accent)";
  return (
    <div className="flex items-center gap-2">
      <div className="flex-1 h-1.5 rounded-full bg-[var(--line-soft)] overflow-hidden">
        <div
          className="h-full rounded-full transition-all duration-500"
          style={{ width: `${pct}%`, background: col }}
        />
      </div>
      <span className="text-[11px] text-[var(--muted)] tabular-nums w-8 text-right">
        {pct}%
      </span>
    </div>
  );
}

/* ── Confirm dialog ───────────────────────────────────────────────── */
export function ConfirmDialog({
  open,
  title,
  desc,
  confirmLabel = "Confirm",
  tone = "danger",
  onConfirm,
  onCancel,
}: {
  open: boolean;
  title: string;
  desc?: string;
  confirmLabel?: string;
  tone?: "danger" | "primary";
  onConfirm: () => void;
  onCancel: () => void;
}) {
  useEffect(() => {
    if (!open) return;
    const handler = (e: KeyboardEvent) => {
      if (e.key === "Escape") onCancel();
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [open, onCancel]);

  if (!open) return null;
  return (
    <div className="fixed inset-0 z-[70] flex items-center justify-center p-4">
      <div
        className="absolute inset-0 bg-black/40 backdrop-blur-sm"
        onClick={onCancel}
      />
      <div className="relative card !p-7 w-full max-w-sm shadow-2xl animate-[slideIn_.15s_ease]">
        <div className="font-semibold text-[16px] mb-2">{title}</div>
        {desc && (
          <p className="text-[13px] text-[var(--muted)] leading-relaxed mb-5">
            {desc}
          </p>
        )}
        <div className="flex gap-2 justify-end mt-5">
          <Button onClick={onCancel}>Cancel</Button>
          <Button
            variant={tone}
            onClick={() => {
              onConfirm();
              onCancel();
            }}
          >
            {confirmLabel}
          </Button>
        </div>
      </div>
    </div>
  );
}

/* ── Copy to clipboard ────────────────────────────────────────────── */
export function CopyButton({
  text,
  className = "",
}: {
  text: string;
  className?: string;
}) {
  const [copied, setCopied] = useState(false);
  const copy = () => {
    navigator.clipboard.writeText(text).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 1800);
    });
  };
  return (
    <button
      onClick={copy}
      className={`btn btn-sm btn-ghost !px-2 !py-1 ${className}`}
      title="Copy to clipboard"
      type="button"
    >
      {copied ? (
        <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="var(--ok)" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
          <path d="M20 6 9 17l-5-5" />
        </svg>
      ) : (
        <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <rect x="9" y="9" width="13" height="13" rx="2" />
          <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1" />
        </svg>
      )}
    </button>
  );
}

/* ── Search input ─────────────────────────────────────────────────── */
export function SearchInput({
  value,
  onChange,
  placeholder = "Search…",
  className = "",
}: {
  value: string;
  onChange: (v: string) => void;
  placeholder?: string;
  className?: string;
}) {
  const ref = useRef<HTMLInputElement>(null);
  return (
    <div className={`relative ${className}`}>
      <svg
        className="absolute left-3 top-1/2 -translate-y-1/2 text-[var(--faint)] pointer-events-none"
        width="14" height="14" viewBox="0 0 24 24" fill="none"
        stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"
      >
        <circle cx="11" cy="11" r="8" />
        <path d="m21 21-4.35-4.35" />
      </svg>
      <input
        ref={ref}
        className="input !pl-9 !py-2 !text-[13px]"
        placeholder={placeholder}
        value={value}
        onChange={(e) => onChange(e.target.value)}
      />
      {value && (
        <button
          className="absolute right-2 top-1/2 -translate-y-1/2 text-[var(--faint)] hover:text-[var(--muted)] text-lg leading-none"
          onClick={() => { onChange(""); ref.current?.focus(); }}
          type="button"
        >
          ×
        </button>
      )}
    </div>
  );
}

/* ── Toasts ───────────────────────────────────────────────────────── */
type Toast = { id: number; msg: string; tone: "ok" | "bad" | "info" };
const ToastCtx = createContext<(m: string, t?: Toast["tone"]) => void>(
  () => {}
);
export const useToast = () => useContext(ToastCtx);

export function ToastProvider({ children }: { children: ReactNode }) {
  const [items, setItems] = useState<Toast[]>([]);
  const push = useCallback((msg: string, tone: Toast["tone"] = "info") => {
    const id = Date.now() + Math.random();
    setItems((s) => [...s, { id, msg, tone }]);
    setTimeout(() => setItems((s) => s.filter((t) => t.id !== id)), 4200);
  }, []);
  return (
    <ToastCtx.Provider value={push}>
      {children}
      <div className="fixed bottom-5 right-5 z-[60] flex flex-col gap-2.5 max-w-[calc(100vw-2.5rem)]">
        {items.map((t) => (
          <div
            key={t.id}
            className="card !py-3 !px-4 min-w-[240px] flex items-center gap-3 shadow-2xl animate-[slideIn_.2s_ease]"
            style={{
              borderColor:
                t.tone === "ok"
                  ? "rgba(61,220,151,.55)"
                  : t.tone === "bad"
                    ? "rgba(255,107,107,.55)"
                    : "var(--line)",
            }}
          >
            <span
              className="w-2 h-2 rounded-full shrink-0"
              style={{
                background:
                  t.tone === "ok"
                    ? "var(--ok)"
                    : t.tone === "bad"
                      ? "var(--bad)"
                      : "var(--accent)",
              }}
            />
            <span className="text-[13px]">{t.msg}</span>
          </div>
        ))}
      </div>
    </ToastCtx.Provider>
  );
}
