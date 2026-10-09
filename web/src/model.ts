// Pure helpers shared by pages: ranking, sorting, grouping, copy. No DOM, unit-tested.
import type { Problem, Slim } from "./api";

export type SortBy = "importance" | "frequency" | "genre" | "tier" | "recent" | "attempts" | "id";
export const SORT_LABELS: Record<SortBy, string> = {
  importance: "Importance", frequency: "Frequency", genre: "Genre", tier: "Tier",
  recent: "Recently worked", attempts: "Attempts", id: "ID",
};
export const IMPORTANCE_HELP =
  "Importance 0–100 = shape rank (Amazon README “Start here”: 45…15 for ranks 1–7) + 2 × problems sharing the genre (max 12) " +
  "+ 8 × extra publications (max 2) + 4 × confidence stars + 6 if Tier A. Your own ★ priority always sorts above it.";
export const VERDICT_NAMES: Record<string, string> = {
  AC: "Accepted", WA: "Wrong Answer", RE: "Runtime Error", TLE: "Time Limit Exceeded", CE: "Compile Error", PENDING: "Judging…",
};

type Rankable = Pick<Problem, "priority" | "importance">;
export const rankScore = (p: Rankable) => (p.priority || 0) * 1000 + (p.importance || 0);

export const SORTS: Record<SortBy, (a: Problem, b: Problem) => number> = {
  importance: (a, b) => rankScore(b) - rankScore(a) || a.pid.localeCompare(b.pid),
  frequency: (a, b) => (b.pubs || 0) - (a.pubs || 0) || (b.family_n || 0) - (a.family_n || 0) || rankScore(b) - rankScore(a),
  genre: (a, b) => (a.genre || "").localeCompare(b.genre || "") || rankScore(b) - rankScore(a),
  tier: (a, b) => (a.tier || "").localeCompare(b.tier || "") || rankScore(b) - rankScore(a),
  recent: (a, b) => (b.last_at || 0) - (a.last_at || 0) || rankScore(b) - rankScore(a),
  attempts: (a, b) => (b.attempts || 0) - (a.attempts || 0) || rankScore(b) - rankScore(a),
  id: (a, b) => a.pid.localeCompare(b.pid),
};

export interface Filters { corpus: string; status: string; tier: string; genre: string; q: string; sort: SortBy; group: boolean }
export const DEFAULT_FILTERS: Filters = { corpus: "", status: "", tier: "", genre: "", q: "", sort: "importance", group: false };

export function applyFilters(rows: Problem[], f: Filters): Problem[] {
  const q = f.q.trim().toLowerCase();
  return rows
    .filter(p =>
      (!f.corpus || p.corpus === f.corpus) &&
      (!f.tier || p.tier === f.tier) &&
      (!f.genre || p.genre === f.genre) &&
      (!f.status || (f.status === "fresh" ? !p.status : p.status === f.status)) &&
      (!q || `${p.id} ${p.title} ${p.genre} ${(p.tags || []).join(" ")}`.toLowerCase().includes(q)))
    .sort(SORTS[f.sort] || SORTS.importance);
}

export interface Group { key: string; rows: Problem[]; solved: number; top: number }
/** Groups keep the order of first appearance in the sorted rows, so the group
 * holding the most important problem comes first under the importance sort. */
export function groupByGenre(rows: Problem[]): Group[] {
  const map = new Map<string, Problem[]>();
  for (const p of rows) {
    const k = p.genre || "—";
    if (!map.has(k)) map.set(k, []);
    map.get(k)!.push(p);
  }
  return [...map.entries()].map(([key, rs]) => ({
    key, rows: rs, solved: rs.filter(r => r.status === "solved").length, top: Math.max(...rs.map(r => r.importance || 0)),
  }));
}

export const pickBest = (rows: Problem[]) => rows.filter(p => p.status !== "solved").sort(SORTS.importance)[0];

/** Resolve a bare id ("A16") or pid against the list; null when absent or ambiguous. */
export function resolveId(rows: Problem[], token: string): { pid: string } | { ambiguous: string[] } | null {
  const t = token.trim().toLowerCase();
  if (!t) return null;
  const exact = rows.find(p => p.pid.toLowerCase() === t);
  if (exact) return { pid: exact.pid };
  const hits = rows.filter(p => p.id.toLowerCase() === t);
  if (hits.length === 1) return { pid: hits[0].pid };
  if (hits.length > 1) return { ambiguous: hits.map(h => h.pid) };
  return null;
}

// ---- copy ------------------------------------------------------------------
const WORDS = ["", "One", "Two", "Three", "Four", "Five", "Six", "Seven", "Eight", "Nine", "Ten"];
export const countWord = (n: number) => WORDS[n] || String(n);
export const plural = (n: number, one: string, many: string) => `${n} ${n === 1 ? one : many}`;

export function agoFromSeconds(sec: number | null | undefined, now = Date.now()): string {
  if (!sec) return "";
  const d = Math.floor((now / 1000 - sec) / 86400);
  if (d <= 0) return "today";
  if (d === 1) return "yesterday";
  if (d < 30) return `${d} days ago`;
  if (d < 365) return `${Math.round(d / 30)} months ago`;
  return "over a year ago";
}
export function agoFromDay(iso: string, now = Date.now()): string {
  const d = Math.round((now - Date.parse(iso + "T12:00:00Z")) / 86400000);
  return d <= 0 ? "today" : d === 1 ? "yesterday" : d < 30 ? `${d} days ago` : `${Math.round(d / 30)} months ago`;
}

/** "Specification/Filter, submitted twice 3 days ago" */
export function progressText(p: Slim & { local?: boolean }, now = Date.now()): string {
  const n = p.attempts || 0;
  const when = p.last_at ? ` ${agoFromSeconds(p.last_at, now)}` : "";
  const parts = [p.genre];
  if (n > 0) parts.push(`submitted ${n === 1 ? "once" : n === 2 ? "twice" : `${n} times`}${when}`);
  else if (p.last_at) parts.push(`tests run${when}, nothing submitted yet`);
  if (p.local) parts.push("draft saved in this browser");
  else if (n === 0 && !p.last_at) parts.push("not started");
  return parts.join(", ");
}

export interface HomeCopy { headline: string; support: string[] }
export function homeCopy(h: { solved: number; total: number; streak: number; last_ac_day: string | null;
                             near: { genre: string; solved: number; left: number } | null;
                             top_genre: { genre: string; left: number } | null }, now = Date.now()): HomeCopy {
  const headline = h.solved ? `${h.solved} of ${h.total} solved.` : `${h.total} problems, none solved yet.`;
  const support: string[] = [];
  if (h.streak >= 2) support.push(`${countWord(h.streak)}-day streak.`);
  else if (h.streak === 1) support.push("Accepted today.");
  else if (h.last_ac_day) support.push(`Last accepted ${agoFromDay(h.last_ac_day, now)}.`);
  const near = h.near && (h.near.left <= 3 || h.near.solved >= h.near.left) ? h.near : null;
  if (near) support.push(`${near.genre} is ${plural(near.left, "problem", "problems")} from done.`);
  else if (h.top_genre) support.push(`${h.top_genre.genre} holds the highest-ranked problems, ${h.top_genre.left} still open.`);
  return { headline, support };
}

/** "your code line 12, in f:  return x" → 12 */
export function failingLine(trace: string | undefined): number | undefined {
  if (!trace) return undefined;
  const lines = trace.split("\n").filter(l => /^your code line \d+/.test(l));
  const m = lines.length ? /^your code line (\d+)/.exec(lines[lines.length - 1]) : null;
  return m ? parseInt(m[1], 10) : undefined;
}

/** GitHub-style heatmap cells for the last N weeks: level 0–4 per day. */
export function heatmapCells(events: { ts: number; verdict: string }[], weeks = 26, now = new Date()): { key: string; n: number; lvl: number }[] {
  const byDay: Record<string, number> = {};
  for (const e of events) {
    const d = new Date(e.ts).toISOString().slice(0, 10);
    byDay[d] = (byDay[d] || 0) + (e.verdict === "AC" ? 1 : 0.25);
  }
  const cells: { key: string; n: number; lvl: number }[] = [];
  const start = new Date(now); start.setDate(now.getDate() - (weeks * 7 - 1) - now.getDay());
  for (let i = 0; i < weeks * 7 + now.getDay() + 1; i++) {
    const d = new Date(start); d.setDate(start.getDate() + i);
    if (d > now) break;
    const key = d.toISOString().slice(0, 10);
    const n = byDay[key] || 0;
    cells.push({ key, n, lvl: n === 0 ? 0 : n < 1 ? 1 : n < 3 ? 2 : n < 6 ? 3 : 4 });
  }
  return cells;
}
