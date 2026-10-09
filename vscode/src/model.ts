// Pure helpers: ranking, sorting, grouping — no vscode imports, unit-testable.
import type { Problem } from "./api";

export type GroupBy = "genre" | "tier" | "corpus" | "status" | "none";
export type SortBy = "importance" | "frequency" | "id" | "recent" | "attempts";

export const GROUP_BYS: GroupBy[] = ["genre", "tier", "corpus", "status", "none"];
export const SORT_BYS: SortBy[] = ["importance", "frequency", "id", "recent", "attempts"];

export const IMPORTANCE_HELP =
  "Importance 0–100 = shape rank (Amazon README “Start here”: 45…15 for ranks 1–7) " +
  "+ 2 × problems sharing the genre (max 12) + 8 × extra publications (max 2) " +
  "+ 4 × confidence stars + 6 if Tier A. Your own ★ priority always sorts above it.";

export const VERDICT_NAMES: Record<string, string> = {
  AC: "Accepted", WA: "Wrong Answer", RE: "Runtime Error", TLE: "Time Limit Exceeded",
  CE: "Compile Error", PENDING: "Judging…",
};

export function rankScore(p: Problem): number {
  return (p.priority || 0) * 1000 + (p.importance || 0);
}

export const SORTS: Record<SortBy, (a: Problem, b: Problem) => number> = {
  importance: (a, b) => rankScore(b) - rankScore(a) || a.pid.localeCompare(b.pid),
  frequency: (a, b) => (b.pubs || 0) - (a.pubs || 0) || (b.family_n || 0) - (a.family_n || 0) || rankScore(b) - rankScore(a),
  id: (a, b) => a.pid.localeCompare(b.pid),
  recent: (a, b) => (b.last_at || 0) - (a.last_at || 0) || rankScore(b) - rankScore(a),
  attempts: (a, b) => (b.attempts || 0) - (a.attempts || 0) || rankScore(b) - rankScore(a),
};

export function statusLabel(p: Problem): string {
  return p.status === "solved" ? "solved" : p.status === "attempted" ? "attempted" : "untouched";
}

export function groupKey(p: Problem, by: GroupBy): string {
  switch (by) {
    case "genre": return p.genre || "—";
    case "tier": return p.tier === "A" ? "Tier A — design & implement" : p.tier === "B" ? "Tier B — algorithm" : "Tier ?";
    case "corpus": return p.corpus;
    case "status": return statusLabel(p);
    default: return "";
  }
}

export interface Group { label: string; rows: Problem[]; solved: number; top: number }

/** Groups appear in order of their best row under the chosen sort, so the
 * most important genre comes first when sorting by importance. */
export function groupProblems(rows: Problem[], by: GroupBy, sort: SortBy, hideSolved: boolean): Group[] {
  const sorted = rows.filter(p => !hideSolved || p.status !== "solved").sort(SORTS[sort]);
  const groups = new Map<string, Problem[]>();
  for (const p of sorted) {
    const k = groupKey(p, by);
    if (!groups.has(k)) groups.set(k, []);
    groups.get(k)!.push(p);
  }
  return [...groups.entries()].map(([label, rs]) => ({
    label, rows: rs,
    solved: rs.filter(r => r.status === "solved").length,
    top: Math.max(...rs.map(r => r.importance || 0)),
  }));
}

export function stars(n: number): string {
  return "★".repeat(Math.max(0, Math.min(5, n || 0)));
}

/** "your code line 12, in f:  return x" → 12 (editor line, 1-based) */
export function failingLine(trace: string | undefined): number | undefined {
  if (!trace) return undefined;
  const lines = trace.split("\n").filter(l => /^your code line \d+/.test(l));
  const last = lines[lines.length - 1];
  const m = last && /^your code line (\d+)/.exec(last);
  return m ? parseInt(m[1], 10) : undefined;
}

export function pickBest(rows: Problem[]): Problem | undefined {
  return rows.filter(p => p.status !== "solved").sort(SORTS.importance)[0];
}
