// Typed client for the mogi API. Same-origin cookies (or the Vite dev proxy's Bearer).
import { syncClock } from "./model";

export interface Problem {
  pid: string; id: string; title: string; corpus: string; tier: string;
  genre: string; genre_corpus: string; family: string; family_n: number; rank: number | null;
  pubs: number; confidence: number; importance: number; practice_stars: number; practice_url: string;
  published: string; round: string; checks: number;
  status: string; attempts: number; solved_at: number | null; last_at: number | null;
  priority: number; tags: string[];
  // Easy | Medium | Hard, where it came from (twin | twin+size | size), and a rough time in minutes (15 | 30 | 45 | 60).
  difficulty: string; difficulty_src: string; minutes: number; loc: number;
  // Hints opened so far. redo_at is the day the problem comes back for a redo, and redo_why says why:
  // "assisted" (you read the solution), "effort" or "shaky" (how you rated the solve).
  hints: number; redo_at: number | null; redo_why: string;
}
export interface Practice { stars: number; url: string; label: string; note: string }
export interface Submission { sk: string; verdict: string; passed: number | null; total: number | null; ms: number; mode: string; created: number; detail: string }
/** A question an interviewer asks after the code works. reps 0 = you have not answered it yet. */
export interface Card { key: string; kind: string; q: string; a: string; reps: number; ivl: number; due: number | null }
/** A card in a review sitting: it also says which problem it belongs to. */
export interface ReviewCard extends Card { pid: string; id: string; title: string }
export interface Review { cards: ReviewCard[]; due: number; problems: number; now: number }
/** What grading a card returns: its next interval in days and when it is due. */
export interface Grade { pid: string; key: string; known: boolean; due: number; ivl: number; reps: number; lapses: number }
export type Rating = "clean" | "effort" | "shaky";
/** The companion in brief. stage 0 is the egg. mood: egg | awake | hungry | asleep (only on the home and companion pages). */
export interface Pet {
  egg: "jelly" | "shell" | "kelp"; name: string; plan: string; hatched: boolean; to_hatch: number;
  stage: number; xp: number; next_xp: number | null; mood?: string;
}
/** What one problem has paid the companion. pending: you read its solution, so it pays when the redo is accepted. */
export interface XpPaid { xp: number; pending: boolean; size?: number; hints?: number; redos?: number; new_genre?: boolean }
export interface CompanionPage {
  pet: Pet | null;
  eggs: { key: Pet["egg"]; name: string; plan: string }[];
  plans: { key: string; total: number; solved: number }[];
  plan: string;
  xp: { total: number; problems: number; reviews: number };
  solved: number; hatch_at: number; stage_xp: number[]; genres: { solved: number; total: number }; reviews_due: number;
  rules: { genre_xp: number; redo_xp: number; review_xp: number; sleep_days: number };
  recent: { pid: string; id: string; title: string; genre: string; at: number | null; xp: number; size: number; hints: number; redos: number; new_genre: boolean }[];
  waiting: { pid: string; id: string; title: string; redo_at: number }[];
}
/** One problem of a mock. What kind of problem it is (genre, difficulty, minutes) only arrives once the mock is over. */
export interface MockProblem {
  pid: string; id: string; title: string; ac_s: number | null; runs: number; submits: number;
  genre?: string; difficulty?: string; minutes?: number;
}
/** A mock round. reason: "done" (all solved) | "time" | "ended" (you stopped it). Times are epoch seconds. */
export interface Mock {
  id: string; corpus: string; format: string; minutes: number; started_at: number; ends_at: number; ended_at: number | null;
  reason: string; active: boolean; solved: number; total: number; problems: MockProblem[];
}
export interface MockFormat { count: number; minutes: number; choices: number[] }
export interface MockHome {
  active: Mock | null; history: Mock[]; formats: Record<string, MockFormat>;
  /** How many unsolved problems each mock could draw from: pools[corpus][format]. */
  pools: Record<string, Record<string, number>>;
}
/** On a problem that belongs to the running mock. */
export interface MockSeat { id: string; ends_at: number; index: number; total: number; solved: boolean; next: { pid: string; id: string; title: string } | null }
/** One step of the hint ladder. The body only arrives once the step is open. */
export interface Rung { key: string; title: string; free: boolean; open: boolean; body?: string }
export interface ProblemDetail extends Problem {
  slug: string; statement: string; required: string[]; stub: string; link: string; alt_link: string;
  practice: Practice; solved: boolean; submissions: Submission[];
  analysis?: string; reference?: string; tests?: string; ac_code?: string;
  next: { pid: string; id: string; title: string; same_genre: boolean } | null; genres: string[];
  ladder: Rung[];
  // unlocked: the analysis, reference and tests are in this response.
  // assisted: you read the solution and a redo is pending. redo_due: that day has come, so they are closed again.
  unlocked: boolean; assisted: boolean; redo_due: boolean; assisted_at: number | null; redo_days: number;
  // The debrief: how you rated the solve, your note, and the questions (only once solved and unlocked).
  rating: Rating | ""; rating_days: Record<string, number>; note?: string; cards?: Card[];
  // Seconds the page's clock counted before the first accepted solve, and before the latest one.
  runs: number; solve_s: number | null; last_solve_s: number | null;
  /** Set while this problem is part of a running mock: hints are off and its details stay hidden. */
  mock?: MockSeat;
  /** With a companion: how it is doing, and what this problem has paid it. */
  pet?: Pet | null; xp?: XpPaid;
}
export interface JudgeCase { status: "pass" | "fail"; label: string; got?: string; want?: string; call?: string }
export interface Verdict {
  pid: string; sk: string; verdict: string; passed: number | null; total: number | null; ms: number;
  detail: string; stdout_tail: string; trace: string; mode: string; cases: JudgeCase[];
  sync?: { state: string; path?: string; why?: string; url?: string };
}
export interface Slim {
  pid: string; id: string; title: string; genre: string; importance: number; priority: number; status: string;
  attempts: number; last_at: number | null; tier: string; corpus: string;
  difficulty: string; difficulty_src: string; minutes: number; redo_at: number | null; redo_why: string;
}
/** The home page's "Today": items[0] is the pick, the rest are alternates. */
export interface Daily { kind: "pick" | "redo"; why: "start" | "back" | "ramp" | "redo"; budget: number; due: number; items: Slim[] }
export interface GenreStat { genre: string; solved: number; left: number; top: number }
export interface Home {
  login: string; solved: number; total: number; streak: number; last_ac_day: string | null; today: string;
  last: Slim | null; next: Slim | null; next2: Slim | null; hint: Slim | null;
  near: GenreStat | null; top_genre: GenreStat | null; genres_left: number; genres_total: number;
  events: ActivityEvent[]; daily: Daily;
  /** Question cards that are due, and how many problems they come from. */
  review: { due: number; problems: number };
  /** The mock that is running, if any. */
  mock: { id: string; ends_at: number; solved: number; total: number } | null;
  /** The companion, if an egg was picked. */
  pet: Pet | null;
}
export interface ActivityEvent { ts: number; verdict: string; pid: string; mode: string; ms: number }
export interface MetaPatch { genre?: string; priority?: number; tags?: string[] | string }
export interface MetaResult { pid: string; genre: string; genre_corpus: string; priority: number; tags: string[] }
export interface ProblemList { problems: Problem[]; solved: number; total: number; genres: string[] }

export class ApiError extends Error { constructor(public status: number, message: string) { super(message); } }
export class AuthError extends ApiError { constructor() { super(401, "not signed in"); } }

export const pidPath = (pid: string) => pid.split("/").map(encodeURIComponent).join("/");
export const problemHref = (pid: string) => `/problem/${pidPath(pid)}`;
export const vscodeHref = (pid: string) => `vscode://shiroyang.mogi/open?pid=${encodeURIComponent(pid)}`;

async function call<T>(method: string, path: string, body?: unknown): Promise<T> {
  const headers: Record<string, string> = { "x-mogi": "1", accept: "application/json" };
  if (body !== undefined) headers["content-type"] = "application/json";
  let r: Response;
  try {
    r = await fetch(`/api${path}`, { method, headers, credentials: "same-origin", body: body === undefined ? undefined : JSON.stringify(body) });
  } catch (e) {
    throw new ApiError(0, `network error: ${(e as Error).message}`);
  }
  if (r.status === 401) throw new AuthError();
  const data = (await r.json().catch(() => ({}))) as { error?: string; now?: number };
  if (!r.ok) throw new ApiError(r.status, data.error || `HTTP ${r.status}`);
  if (typeof data.now === "number") syncClock(data.now);
  return data as T;
}

export const api = {
  me: () => call<{ login: string; cli: boolean; can_sync: boolean }>("GET", "/me"),
  home: (hint?: string) => call<Home>("GET", `/home${hint ? `?hint=${encodeURIComponent(hint)}` : ""}`),
  problems: () => call<ProblemList>("GET", "/problems"),
  problem: (pid: string) => call<ProblemDetail>("GET", `/problems/${pidPath(pid)}`),
  setMeta: (pid: string, patch: MetaPatch) => call<MetaResult>("PUT", `/problems/${pidPath(pid)}/meta`, patch),
  /** Open one hint. Returns the whole problem again, with that step's text in it. */
  hint: (pid: string, key: string) => call<ProblemDetail>("POST", `/problems/${pidPath(pid)}/hint`, { key }),
  /** Open the analysis, reference and tests before an accepted submission. Schedules the redo. */
  solution: (pid: string) => call<ProblemDetail>("POST", `/problems/${pidPath(pid)}/solution`, {}),
  submit: (pid: string, code: string, mode: "run" | "submit", elapsed?: number) =>
    call<{ pid: string; sk: string }>("POST", "/submit", { pid, code, mode, ...(elapsed === undefined ? {} : { elapsed_s: elapsed }) }),
  /** Save the debrief: how the solve went and/or a note. Returns the whole problem again. */
  debrief: (pid: string, patch: { rating?: Rating; note?: string }) => call<ProblemDetail>("POST", `/problems/${pidPath(pid)}/debrief`, patch),
  /** Record one answer to a question card. */
  grade: (pid: string, key: string, known: boolean) => call<Grade>("POST", `/problems/${pidPath(pid)}/card`, { key, known }),
  review: () => call<Review>("GET", "/review"),
  companion: () => call<CompanionPage>("GET", "/companion"),
  /** Pick an egg, change the path or the name. egg: "" puts the companion away. */
  companionSet: (patch: { egg?: string; plan?: string; name?: string }) => call<CompanionPage>("POST", "/companion", patch),
  mock: () => call<MockHome>("GET", "/mock"),
  mockOne: (id: string) => call<Mock>("GET", `/mock/${encodeURIComponent(id)}`),
  mockStart: (corpus: string, format: string, minutes: number) => call<Mock>("POST", "/mock", { corpus, format, minutes }),
  mockEnd: () => call<Mock>("POST", "/mock/end", {}),
  poll: (pid: string, sk: string) => call<Verdict>("GET", `/submissions/${pidPath(pid)}/${encodeURIComponent(sk)}`),
  async judge(pid: string, code: string, mode: "run" | "submit", elapsed?: number, onTick?: (i: number) => void, timeoutMs = 125_000): Promise<Verdict> {
    const sub = await api.submit(pid, code, mode, elapsed);
    const deadline = Date.now() + timeoutMs;
    for (let i = 0; Date.now() < deadline; i++) {
      await new Promise(r => setTimeout(r, i < 6 ? 700 : 1500));
      const res = await api.poll(pid, sub.sk);
      if (res.verdict !== "PENDING") return res;
      onTick?.(i);
    }
    throw new ApiError(0, "still judging — the verdict will appear in the submissions list");
  },
};
