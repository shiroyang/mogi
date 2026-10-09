// Typed client for the mogi API. Same-origin cookies (or the Vite dev proxy's Bearer).
export interface Problem {
  pid: string; id: string; title: string; corpus: string; tier: string;
  genre: string; genre_corpus: string; family: string; family_n: number; rank: number | null;
  pubs: number; confidence: number; importance: number; practice_stars: number; practice_url: string;
  published: string; round: string; checks: number;
  status: string; attempts: number; solved_at: number | null; last_at: number | null;
  priority: number; tags: string[];
}
export interface Practice { stars: number; url: string; label: string; note: string }
export interface Submission { sk: string; verdict: string; passed: number | null; total: number | null; ms: number; mode: string; created: number; detail: string }
export interface ProblemDetail extends Problem {
  slug: string; statement: string; required: string[]; stub: string; link: string; alt_link: string;
  practice: Practice; solved: boolean; submissions: Submission[];
  analysis?: string; reference?: string; tests?: string; ac_code?: string;
  next: { pid: string; id: string; title: string; same_genre: boolean } | null; genres: string[];
}
export interface JudgeCase { status: "pass" | "fail"; label: string; got?: string; want?: string; call?: string }
export interface Verdict {
  pid: string; sk: string; verdict: string; passed: number | null; total: number | null; ms: number;
  detail: string; stdout_tail: string; trace: string; mode: string; cases: JudgeCase[];
  sync?: { state: string; path?: string; why?: string; url?: string };
}
export interface Slim { pid: string; id: string; title: string; genre: string; importance: number; priority: number; status: string; attempts: number; last_at: number | null; tier: string; corpus: string }
export interface GenreStat { genre: string; solved: number; left: number; top: number }
export interface Home {
  login: string; solved: number; total: number; streak: number; last_ac_day: string | null; today: string;
  last: Slim | null; next: Slim | null; next2: Slim | null; hint: Slim | null;
  near: GenreStat | null; top_genre: GenreStat | null; genres_left: number; genres_total: number;
  events: ActivityEvent[];
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
  const data = (await r.json().catch(() => ({}))) as { error?: string };
  if (!r.ok) throw new ApiError(r.status, data.error || `HTTP ${r.status}`);
  return data as T;
}

export const api = {
  me: () => call<{ login: string; cli: boolean; can_sync: boolean }>("GET", "/me"),
  home: (hint?: string) => call<Home>("GET", `/home${hint ? `?hint=${encodeURIComponent(hint)}` : ""}`),
  problems: () => call<ProblemList>("GET", "/problems"),
  problem: (pid: string) => call<ProblemDetail>("GET", `/problems/${pidPath(pid)}`),
  setMeta: (pid: string, patch: MetaPatch) => call<MetaResult>("PUT", `/problems/${pidPath(pid)}/meta`, patch),
  submit: (pid: string, code: string, mode: "run" | "submit") => call<{ pid: string; sk: string }>("POST", "/submit", { pid, code, mode }),
  poll: (pid: string, sk: string) => call<Verdict>("GET", `/submissions/${pidPath(pid)}/${encodeURIComponent(sk)}`),
  async judge(pid: string, code: string, mode: "run" | "submit", onTick?: (i: number) => void, timeoutMs = 125_000): Promise<Verdict> {
    const sub = await api.submit(pid, code, mode);
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
