// Small shared pieces: top bar, stars, heatmap, segmented control, markdown, toasts.
import { marked } from "marked";
import { AnimatePresence, motion, useReducedMotion } from "motion/react";
import { useSyncExternalStore, type ReactNode } from "react";
import { Link } from "react-router";
import { heatmapCells, IMPORTANCE_HELP } from "../model";

export function TopBar({ crumbs = [], title, right }: { crumbs?: { label: string; to?: string }[]; title?: ReactNode; right?: ReactNode }) {
  return (
    <header className="topbar">
      <Link className="wordmark" to="/">mogi</Link>
      {crumbs.map(c => (
        <span key={c.label} className="crumb">› {c.to ? <Link to={c.to}>{c.label}</Link> : c.label}</span>
      ))}
      {title && <span className="title">{title}</span>}
      <span className="spacer" />
      {right}
    </header>
  );
}

export function Stars({ value, onChange, size = "sm", label }: { value: number; onChange?: (n: number) => void; size?: "sm" | "lg"; label?: string }) {
  return (
    <span className={`stars ${size}`} role="group" aria-label={label || `priority ${value} of 5`}>
      {[1, 2, 3, 4, 5].map(k => (
        <button key={k} type="button" className={k <= value ? "on" : ""} disabled={!onChange}
          aria-label={`priority ${k}`} aria-pressed={k <= value}
          onClick={e => { e.preventDefault(); e.stopPropagation(); onChange?.(k === value ? 0 : k); }}>★</button>
      ))}
    </span>
  );
}

export function Importance({ value, rank }: { value: number; rank?: number | null }) {
  return (
    <span className="imp" title={IMPORTANCE_HELP}>
      <i><b style={{ width: `${value || 0}%` }} /></i>{value || 0}
      {rank ? <span className="chip rank" title="shape rank in the Amazon README">#{rank}</span> : null}
    </span>
  );
}

export function Heatmap({ events, weeks = 26, caption }: { events: { ts: number; verdict: string }[]; weeks?: number; caption?: string }) {
  const cells = heatmapCells(events, weeks);
  return (
    <div className="pulse">
      <div className="heatmap" aria-label="activity, last 26 weeks">
        {cells.map(c => <i key={c.key} className={c.lvl ? `l${c.lvl}` : ""} title={`${c.key}: ${c.n}`} />)}
      </div>
      {caption && <span className="faint" style={{ fontSize: 12.5 }}>{caption}</span>}
    </div>
  );
}

export function Segmented<T extends string>({ options, value, onChange, id = "seg" }:
  { options: { key: T; label: string }[]; value: T; onChange: (k: T) => void; id?: string }) {
  const reduce = useReducedMotion();
  return (
    <div className="seg" role="tablist">
      {options.map(o => (
        <button key={o.key} role="tab" aria-selected={o.key === value} className={o.key === value ? "on" : ""} onClick={() => onChange(o.key)}>
          {o.key === value && (
            <motion.span layoutId={`${id}-thumb`} className="thumb" style={{ left: 0, right: 0 }}
              transition={reduce ? { duration: 0 } : { type: "spring", stiffness: 500, damping: 40 }} />
          )}
          <span style={{ position: "relative", zIndex: 1 }}>{o.label}</span>
        </button>
      ))}
    </div>
  );
}

export function Markdown({ source, className = "" }: { source: string; className?: string }) {
  const html = marked.parse(source || "", { async: false, gfm: true }) as string;
  return <div className={`md ${className}`} dangerouslySetInnerHTML={{ __html: html }} />;
}

// ---- toasts: a tiny store, rendered once at the root -----------------------
interface Toast { id: number; text: string }
let toasts: Toast[] = [];
const subs = new Set<() => void>();
const emit = () => subs.forEach(s => s());
export function toast(text: string, ms = 3200) {
  const id = Date.now() + Math.random();
  toasts = [...toasts, { id, text }];
  emit();
  setTimeout(() => { toasts = toasts.filter(t => t.id !== id); emit(); }, ms);
}
export function Toasts() {
  const list = useSyncExternalStore(cb => { subs.add(cb); return () => subs.delete(cb); }, () => toasts);
  return (
    <AnimatePresence>
      {list.map((t, i) => (
        <motion.div key={t.id} className="toast" role="status" style={{ bottom: `calc(${18 + i * 52}px + var(--safe-b))` }}
          initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: 8 }}>{t.text}</motion.div>
      ))}
    </AnimatePresence>
  );
}

export function Spinner({ label }: { label?: string }) {
  return <span style={{ display: "inline-flex", alignItems: "center", gap: 10 }} className="muted"><span className="spin" />{label}</span>;
}
