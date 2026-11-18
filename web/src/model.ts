// Pure helpers shared by pages: ranking, sorting, grouping, copy. No DOM, unit-tested.
import type { Card, CompanionPage, Daily, Mock, MockProblem, Pet, Problem, ProblemDetail, Slim, XpPaid } from "./api";

export type SortBy = "importance" | "easiest" | "shortest" | "frequency" | "genre" | "tier" | "recent" | "attempts" | "id";
export const SORT_LABELS: Record<SortBy, string> = {
  importance: "Importance", easiest: "Easiest first", shortest: "Shortest first", frequency: "Frequency",
  genre: "Genre", tier: "Tier", recent: "Recently worked", attempts: "Attempts", id: "ID",
};
export const IMPORTANCE_HELP =
  "Importance 0–100 = shape rank (Amazon README “Start here”: 45…15 for ranks 1–7) + 2 × problems sharing the genre (max 12) " +
  "+ 8 × extra publications (max 2) + 4 × confidence stars + 6 if Tier A. Your own ★ priority always sorts above it.";
export const VERDICT_NAMES: Record<string, string> = {
  AC: "Accepted", WA: "Wrong Answer", RE: "Runtime Error", TLE: "Time Limit Exceeded", CE: "Compile Error", PENDING: "Judging…",
};

type Rankable = Pick<Problem, "priority" | "importance">;
export const rankScore = (p: Rankable) => (p.priority || 0) * 1000 + (p.importance || 0);

// ---- difficulty and time ---------------------------------------------------
export const DIFFICULTIES = ["Easy", "Medium", "Hard"] as const;
/** 1 Easy … 3 Hard. A problem without a rating sorts last. */
export const difficultyRank = (d: string) => { const i = DIFFICULTIES.indexOf(d as (typeof DIFFICULTIES)[number]); return i < 0 ? 9 : i + 1; };
export const DIFFICULTY_HELP: Record<string, string> = {
  twin: "The rating of its LeetCode twin.",
  "twin+size": "Its LeetCode twin is rated lower. Raised because this version is much longer.",
  size: "Estimated from the size of the reference solution. There is no LeetCode twin to borrow a rating from.",
};
/** "15 min" for a chip. The top bucket is open-ended. */
export const minutesShort = (m: number) => (m >= 60 ? "60+ min" : `${m} min`);
/** "about 15 minutes" for a sentence. */
export const minutesText = (m: number) => (m >= 60 ? "about an hour" : `about ${m} minutes`);
export const minutesHelp = (loc: number) =>
  `A rough guide, from the size of the reference solution${loc ? ` (${loc} lines of code)` : ""} and the twin's rating.`;
/** "Easy graph problem, about 15 minutes." */
export function sizeSentence(p: { difficulty: string; genre: string; minutes: number }): string {
  const what = [p.difficulty, p.genre, "problem"].filter(Boolean).join(" ");
  return `${what[0].toUpperCase()}${what.slice(1)}${p.minutes ? `, ${minutesText(p.minutes)}` : ""}.`;
}

// ---- redo: a problem whose solution you read comes back later ---------------
// The server decides when a redo is due, so "now" follows the server's clock.
// Each API response carries it. The difference is kept and applied to this device's clock.
let clockSkew = 0;
export const syncClock = (serverSeconds: number) => { clockSkew = serverSeconds * 1000 - Date.now(); };
export const serverNow = () => Date.now() + clockSkew;

export type RedoState = "none" | "resting" | "due";
export const redoState = (redoAt: number | null | undefined, now = serverNow()): RedoState =>
  !redoAt ? "none" : redoAt * 1000 <= now ? "due" : "resting";
/** The dot and the status filter treat a pending redo as its own state, above solved. */
export const rowStatus = (p: Pick<Problem, "status" | "redo_at">) => (p.redo_at ? "assisted" : p.status);
const dayStart = (ms: number) => { const d = new Date(ms); d.setHours(0, 0, 0, 0); return d.getTime(); };
/** Whole calendar days from now to a moment, in local time. Negative means past. */
export const daysUntil = (sec: number, now = serverNow()) => Math.round((dayStart(sec * 1000) - dayStart(now)) / 86400000);
/** "today" · "tomorrow" · "in 3 days" · "yesterday" · "3 days ago" */
export function dayText(sec: number, now = serverNow()): string {
  const d = daysUntil(sec, now);
  return d === 0 ? "today" : d === 1 ? "tomorrow" : d === -1 ? "yesterday" : d > 0 ? `in ${d} days` : `${-d} days ago`;
}
/** The chip on a problem that waits for a redo: "redo in 3 days" · "redo tomorrow" · "redo today" · "redo due" */
export function redoText(redoAt: number, now = serverNow()): string {
  if (redoAt * 1000 <= now) return "redo due";
  const d = daysUntil(redoAt, now);
  return d <= 0 ? "redo today" : d === 1 ? "redo tomorrow" : `redo in ${d} days`;
}
/** "Fri 20 Nov" */
export const dateText = (sec: number) =>
  new Date(sec * 1000).toLocaleDateString("en-GB", { weekday: "short", day: "numeric", month: "short" });

export const SORTS: Record<SortBy, (a: Problem, b: Problem) => number> = {
  importance: (a, b) => rankScore(b) - rankScore(a) || a.pid.localeCompare(b.pid),
  easiest: (a, b) => difficultyRank(a.difficulty) - difficultyRank(b.difficulty) || (a.minutes || 99) - (b.minutes || 99)
    || rankScore(b) - rankScore(a) || a.pid.localeCompare(b.pid),
  shortest: (a, b) => (a.minutes || 99) - (b.minutes || 99) || difficultyRank(a.difficulty) - difficultyRank(b.difficulty)
    || rankScore(b) - rankScore(a) || a.pid.localeCompare(b.pid),
  frequency: (a, b) => (b.pubs || 0) - (a.pubs || 0) || (b.family_n || 0) - (a.family_n || 0) || rankScore(b) - rankScore(a),
  genre: (a, b) => (a.genre || "").localeCompare(b.genre || "") || rankScore(b) - rankScore(a),
  tier: (a, b) => (a.tier || "").localeCompare(b.tier || "") || rankScore(b) - rankScore(a),
  recent: (a, b) => (b.last_at || 0) - (a.last_at || 0) || rankScore(b) - rankScore(a),
  attempts: (a, b) => (b.attempts || 0) - (a.attempts || 0) || rankScore(b) - rankScore(a),
  id: (a, b) => a.pid.localeCompare(b.pid),
};

export interface Filters { corpus: string; status: string; tier: string; difficulty: string; genre: string; q: string; sort: SortBy; group: boolean }
export const DEFAULT_FILTERS: Filters = { corpus: "", status: "", tier: "", difficulty: "", genre: "", q: "", sort: "importance", group: false };
/** status: solved | attempted | fresh (never touched) | redo (waiting for a redo) */
const statusMatches = (p: Problem, want: string) =>
  want === "fresh" ? !p.status && !p.redo_at : want === "redo" ? !!p.redo_at : p.status === want;

export function applyFilters(rows: Problem[], f: Filters): Problem[] {
  const q = f.q.trim().toLowerCase();
  return rows
    .filter(p =>
      (!f.corpus || p.corpus === f.corpus) &&
      (!f.tier || p.tier === f.tier) &&
      (!f.difficulty || p.difficulty === f.difficulty) &&
      (!f.genre || p.genre === f.genre) &&
      (!f.status || statusMatches(p, f.status)) &&
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

/** The most important problem you can start now: not solved, and not resting before a redo. */
export const pickBest = (rows: Problem[]) => rows.filter(p => p.status !== "solved" && !p.redo_at).sort(SORTS.importance)[0];

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

/** The corpus statement opens with its own `# ID — title` and front-matter table.
 * Pages show the title themselves, so the body starts at the first section
 * and the table is returned apart, for a collapsible "details" block. */
export function splitStatement(md: string): { details: string; body: string } {
  const i = md.search(/^## /m);
  if (i < 0) return { details: "", body: md };
  const table = md.slice(0, i).split("\n").filter(l => l.startsWith("|")).join("\n");
  return { details: table, body: md.slice(i) };
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

/** Why a problem comes back for a redo, as the start of a sentence. */
export const REDO_REASON: Record<string, string> = {
  assisted: "You read the solution",
  effort: "You said it was a struggle",
  shaky: "You were not sure you could repeat it",
};
export const redoReason = (why: string | undefined) => REDO_REASON[why || "assisted"] || REDO_REASON.assisted;

/** The words on the home page's Today tile. `index` is which alternate is showing. */
export interface DailyCopy { title: string; sub: string; another: boolean }
export function dailyCopy(d: Daily | undefined, index = 0): DailyCopy | null {
  const items = d?.items || [];
  if (!d || !items.length) return null;
  const p = items[index % items.length];
  if (d.kind === "redo") {
    const waiting = d.due - 1;
    return {
      title: p.title, another: false,
      sub: `Redo day. ${redoReason(p.redo_why)}, now write it again from a blank editor.`
        + (waiting > 0 ? ` ${waiting === 1 ? "One more is" : `${waiting} more are`} waiting after this one.` : ""),
    };
  }
  const why = index > 0 ? "" : d.why === "start" ? " A short one to get moving." : d.why === "back" ? " A short one to get back into it." : "";
  return { title: p.title, sub: sizeSentence(p) + why, another: items.length > 1 };
}

// ---- the hint ladder ---------------------------------------------------------
/** What each step is called, what to think about before opening it, and the button that opens it. */
export const RUNG_COPY: Record<string, { title: string; lead: string }> = {
  clarify: { title: "Ask the interviewer", lead: "What would you ask before writing any code? Think of your own questions first, then compare." },
  brute: { title: "Brute force", lead: "The simplest correct approach, and what it costs." },
  approach: { title: "The approach, in words", lead: "The idea behind the efficient solution. No code yet." },
  growth: { title: "What will change", lead: "The part of the problem the follow-up questions will push on." },
  boxes: { title: "The pieces", lead: "Which classes exist, and what each one owns." },
  structure: { title: "The design", lead: "The structure the reference chose, and the ones it turned down." },
};
/** Number the hints that count. The free step has no number. */
export function ladderSteps<T extends { key: string; free: boolean; open: boolean }>(ladder: T[]) {
  const total = ladder.filter(r => !r.free).length;
  let n = 0, prevOpen = true;
  return ladder.map(r => {
    const step = r.free ? 0 : ++n;
    const canOpen = r.free || prevOpen;      // hints open in order
    if (!r.free) prevOpen = r.open;
    return { ...r, step, total, canOpen, copy: RUNG_COPY[r.key] };
  });
}

// ---- the clock, the debrief and the question cards ----------------------------
/** "12:40" for the clock on the problem page, "1:02:05" past an hour. */
export function clockText(secs: number): string {
  const s = Math.max(0, Math.floor(secs)), h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60);
  const two = (n: number) => String(n).padStart(2, "0");
  return h ? `${h}:${two(m)}:${two(s % 60)}` : `${m}:${two(s % 60)}`;
}
/** "23 minutes" · "1 hour 5 minutes" · "under a minute" */
export function durationText(secs: number): string {
  const m = Math.round(secs / 60);
  if (m < 1) return "under a minute";
  const h = Math.floor(m / 60), rest = m % 60;
  if (!h) return plural(m, "minute", "minutes");
  return plural(h, "hour", "hours") + (rest ? ` ${plural(rest, "minute", "minutes")}` : "");
}
/** The line that opens the debrief: "Accepted in 23 minutes." */
export const debriefHeadline = (p: Pick<ProblemDetail, "solve_s" | "last_solve_s">) => {
  const secs = p.last_solve_s ?? p.solve_s;
  return secs ? `Accepted in ${durationText(secs)}.` : "Accepted.";
};
/** "2 runs, 1 submission and no hints." */
export function debriefFacts(p: Pick<ProblemDetail, "runs" | "attempts" | "hints">): string {
  const parts = [
    ...(p.runs ? [plural(p.runs, "run", "runs")] : []),
    plural(p.attempts || 1, "submission", "submissions"),
    p.hints ? plural(p.hints, "hint", "hints") : "no hints",
  ];
  return `${parts.slice(0, -1).join(", ")} and ${parts[parts.length - 1]}.`;
}
/** The three answers to "How did it go?" and what each one does. */
export const RATINGS = [
  { key: "clean", label: "I could do it again" },
  { key: "effort", label: "It was a struggle" },
  { key: "shaky", label: "Not sure I could repeat it" },
] as const;
/** What a card is called, and the question the app asks when the corpus has none of its own. */
export const CARD_COPY: Record<string, { label: string; q?: string }> = {
  approach: { label: "Approach", q: "How would you solve it? Say the approach in two or three sentences." },
  design: { label: "Design", q: "Which structure would you choose, and which alternative would you turn down?" },
  complexity: { label: "Complexity", q: "What are the time and space costs, and why?" },
  edges: { label: "Edge cases", q: "Which edge cases would you check out loud?" },
  dive: { label: "Follow-up" },
  followup: { label: "Follow-up" },
};
export const cardLabel = (kind: string) => CARD_COPY[kind]?.label || "Question";
export const cardQuestion = (c: Pick<Card, "kind" | "q">) => c.q || CARD_COPY[c.kind]?.q || "";
/** The debrief asks the complexity and the follow-ups. The approach and the edge cases wait for the review queue. */
export const debriefCards = (cards: Card[] | undefined) => (cards || []).filter(c => ["complexity", "dive", "followup"].includes(c.kind));
/** "Comes back tomorrow." · "Comes back in 7 days." */
export const comesBack = (days: number) => `Comes back ${days <= 1 ? "tomorrow" : `in ${days} days`}.`;
/** The words on the home page's Review tile. Half a minute per question is close enough. */
export function reviewCopy(r: { due: number; problems: number } | undefined): { title: string; sub: string } | null {
  if (!r || !r.due) return null;
  return {
    title: `${plural(r.due, "question", "questions")} due`,
    sub: `From ${r.problems === 1 ? "one problem" : `${r.problems} problems`} you solved. About ${plural(Math.max(1, Math.round(r.due / 2)), "minute", "minutes")}.`,
  };
}

// ---- the companion -----------------------------------------------------------
export const STAGE_NAMES = ["egg", "hatchling", "juvenile", "grown one", "elder", "ancient"];
export const stageName = (stage: number) => STAGE_NAMES[Math.max(0, Math.min(stage, STAGE_NAMES.length - 1))];
/** What each egg turns into, in three words. */
export const EGG_KIND: Record<string, string> = { jelly: "a glass drifter", shell: "a shell dweller", kelp: "a kelp sprite" };
/** The paths an egg can come with. Today draws from the companion's path. */
export const PLAN_COPY: Record<string, { label: string; what: string }> = {
  classics: { label: "Classics", what: "the Classics path, one problem per pattern" },
  amazon: { label: "Amazon", what: "the Amazon corpus" },
  google: { label: "Google", what: "the Google corpus" },
  all: { label: "Everything", what: "every problem" },
};
/** How the companion is drawn. An egg cracks a little with each solved problem. */
export const petLook = (pet: Pet, hatchAt = 3) => ({ egg: pet.egg, stage: pet.stage, mood: pet.mood, cracks: pet.hatched ? 0 : Math.max(0, hatchAt - pet.to_hatch) });
/** The two or three words under the porthole on the home page. */
export function petCaption(pet: Pet): string {
  if (!pet.hatched) return pet.to_hatch > 0 ? `${pet.to_hatch} to hatch` : "hatching";
  return pet.mood === "asleep" || pet.mood === "hungry" ? pet.mood : stageName(pet.stage);
}
/** One sentence on what it is and what it needs next. */
export function petStatus(pet: Pet): string {
  if (!pet.hatched) {
    const n = pet.to_hatch;
    return n >= 3 ? "An egg. It hatches when you have solved three problems."
      : `An egg. ${n === 1 ? "One more solved problem" : `${countWord(n)} more solved problems`} and it hatches.`;
  }
  const name = stageName(pet.stage);
  return `${/^[aeiou]/.test(name) ? "An" : "A"} ${name}, with ${pet.xp} XP.${pet.next_xp ? ` It grows at ${pet.next_xp}.` : " It is fully grown."}`;
}
/** How it feels, and what changes that. Empty for an egg. */
export function petMoodLine(pet: Pet, due: number, sleepDays = 7): string {
  if (pet.mood === "asleep") return `It is asleep after ${sleepDays} quiet days. A run, a submission or a review answer wakes it.`;
  if (pet.mood === "hungry") return `It is hungry: ${plural(due, "question is", "questions are")} due.`;
  return pet.mood === "awake" ? "It is awake and fed." : "";
}
/** How far along it is: toward hatching while it is an egg, toward the next stage after. */
export function petProgress(pet: Pet, stageXp: number[], hatchAt = 3): { value: number; label: string } {
  if (!pet.hatched) return { value: (hatchAt - pet.to_hatch) / hatchAt, label: `${hatchAt - pet.to_hatch} of ${hatchAt} solved` };
  if (!pet.next_xp) return { value: 1, label: `${pet.xp} XP` };
  const from = [0, ...stageXp].filter(t => t <= pet.xp).pop() || 0;
  return { value: (pet.xp - from) / (pet.next_xp - from), label: `${pet.xp} of ${pet.next_xp} XP` };
}
/** The debrief's line about the companion. */
export function xpLine(name: string, paid: XpPaid, genre: string): string {
  if (paid.pending) return `${name} gets its XP when the redo is accepted.`;
  return `${name} gets ${paid.xp} XP${paid.new_genre ? `, with the bonus for your first ${genre} problem` : ""}.`;
}
/** Why a solve paid what it did: "first graph problem, 1 hint" */
export function paidNote(r: CompanionPage["recent"][number]): string {
  return [
    ...(r.new_genre ? [`first ${r.genre} problem`] : []),
    ...(r.hints ? [plural(r.hints, "hint", "hints")] : []),
    ...(r.redos ? [plural(r.redos, "redo", "redos")] : []),
  ].join(", ");
}

// ---- mock rounds ---------------------------------------------------------------
/** The three mocks, in the order they are offered. */
export const MOCK_FORMATS = [
  { key: "coding", label: "Coding round", what: "One algorithm problem." },
  { key: "design", label: "Design round", what: "One design-and-implement problem." },
  { key: "oa", label: "Online assessment", what: "Two problems on one clock." },
] as const;
/** "Amazon coding round" */
export const mockName = (m: Pick<Mock, "corpus" | "format">) =>
  `${m.corpus} ${(MOCK_FORMATS.find(f => f.key === m.format)?.label || "mock").toLowerCase()}`;
/** Seconds left on a mock's clock, by the server's time. */
export const mockLeft = (endsAt: number, now = serverNow()) => Math.max(0, Math.ceil(endsAt - now / 1000));
/** The first line of a mock's result. */
export function mockHeadline(m: Mock): string {
  const used = (m.ended_at ?? m.ends_at) - m.started_at;
  const spare = Math.floor((m.minutes * 60 - used) / 60);
  const score = `${m.solved} of ${m.total} solved`;
  if (m.reason === "done") {
    const left = spare >= 1 ? `, with ${plural(spare, "minute", "minutes")} left` : ", right on the bell";
    return m.total === 1 ? `Solved${left}.` : `${score}${left}.`;
  }
  if (m.reason === "time") return m.total === 1 ? "Time ran out before it was solved." : `Time ran out. ${score}.`;
  return `${used < 60 ? "Ended in the first minute" : `Ended after ${durationText(used)}`}. ${score}.`;
}
/** What happened on one problem of a finished mock. */
export function mockProblemLine(p: MockProblem): string {
  const work = [...(p.runs ? [plural(p.runs, "run", "runs")] : []), ...(p.submits ? [plural(p.submits, "submission", "submissions")] : [])].join(" and ");
  if (p.ac_s !== null) return `Accepted at ${clockText(p.ac_s)}${work ? `, after ${work}` : ""}.`;
  return work ? `Not accepted, after ${work}.` : "Not attempted.";
}
/** One line for the list of earlier mocks: "1 of 2, time ran out" */
export function mockHistoryLine(m: Mock): string {
  const used = (m.ended_at ?? m.ends_at) - m.started_at;
  const how = m.reason === "done" ? `in ${durationText(used)}` : m.reason === "time" ? "time ran out" : "ended early";
  return `${m.solved} of ${m.total}, ${how}`;
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
