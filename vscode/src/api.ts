// HTTP client for the mogi API (global fetch — VS Code ships Node ≥ 20).
export interface Problem {
  pid: string;
  id: string;
  title: string;
  corpus: string;
  tier: string;
  genre: string;
  genre_corpus: string;
  family: string;
  family_n: number;
  rank: number | null;
  pubs: number;
  confidence: number;
  importance: number;
  practice_stars: number;
  practice_url: string;
  published: string;
  round: string;
  checks: number;
  status: string;
  attempts: number;
  solved_at: number | null;
  last_at: number | null;
  priority: number;
  tags: string[];
}

export interface Practice { stars: number; url: string; label: string; note: string }

export interface ProblemDetail extends Problem {
  slug: string;
  statement: string;
  required: string[];
  stub: string;
  link: string;
  alt_link: string;
  practice: Practice;
  solved: boolean;
  submissions: Submission[];
  analysis?: string;
  reference?: string;
  tests?: string;
  ac_code?: string;
  next: { pid: string; id: string; title: string; same_genre: boolean } | null;
  genres: string[];
}

export interface Submission {
  sk: string; verdict: string; passed: number | null; total: number | null;
  ms: number; mode: string; created: number; detail: string;
}

export interface JudgeCase { status: "pass" | "fail"; label: string; got?: string; want?: string; call?: string }

export interface Verdict {
  pid: string;
  sk: string;
  verdict: string;
  passed: number | null;
  total: number | null;
  ms: number;
  detail: string;
  stdout_tail: string;
  trace: string;
  mode: string;
  cases: JudgeCase[];
  sync?: { state: string; path?: string; why?: string; url?: string };
}

export interface MetaPatch { genre?: string; priority?: number; tags?: string[] | string }
export interface MetaResult { pid: string; genre: string; genre_corpus: string; priority: number; tags: string[] }

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

const pidPath = (pid: string) => pid.split("/").map(encodeURIComponent).join("/");

export class Api {
  constructor(private readonly siteOf: () => string, private readonly tokenOf: () => string | undefined) {}

  get site(): string { return this.siteOf(); }

  private async call<T>(method: string, p: string, body?: unknown): Promise<T> {
    const headers: Record<string, string> = {
      accept: "application/json", "x-mogi": "1", "user-agent": "mogi-vscode/0.1.0",
    };
    const t = this.tokenOf();
    if (t) headers.authorization = `Bearer ${t}`;
    if (body !== undefined) headers["content-type"] = "application/json";
    let r: Response;
    try {
      r = await fetch(`${this.site}/api${p}`, {
        method, headers, body: body === undefined ? undefined : JSON.stringify(body),
      });
    } catch (e) {
      throw new ApiError(0, `cannot reach ${this.site}: ${(e as Error).message}`);
    }
    const data = (await r.json().catch(() => ({}))) as { error?: string };
    if (r.status === 401) throw new ApiError(401, "not signed in — run “mogi: Sign in with GitHub”");
    if (!r.ok) throw new ApiError(r.status, data.error || `HTTP ${r.status}`);
    return data as T;
  }

  me() { return this.call<{ login: string; cli: boolean; can_sync: boolean }>("GET", "/me"); }
  problems() { return this.call<{ problems: Problem[]; solved: number; total: number; genres: string[] }>("GET", "/problems"); }
  problem(pid: string) { return this.call<ProblemDetail>("GET", `/problems/${pidPath(pid)}`); }
  setMeta(pid: string, patch: MetaPatch) { return this.call<MetaResult>("PUT", `/problems/${pidPath(pid)}/meta`, patch); }
  submit(pid: string, code: string, mode: "run" | "submit") {
    return this.call<{ pid: string; sk: string }>("POST", "/submit", { pid, code, mode });
  }
  poll(pid: string, sk: string) {
    return this.call<Verdict>("GET", `/submissions/${pidPath(pid)}/${encodeURIComponent(sk)}`);
  }

  async judge(pid: string, code: string, mode: "run" | "submit", timeoutMs = 125_000): Promise<Verdict> {
    const sub = await this.submit(pid, code, mode);
    const deadline = Date.now() + timeoutMs;
    for (let i = 0; Date.now() < deadline; i++) {
      await new Promise(r => setTimeout(r, i < 6 ? 700 : 1500));
      const res = await this.poll(pid, sub.sk);
      if (res.verdict !== "PENDING") return res;
    }
    throw new ApiError(0, "timed out waiting for a verdict");
  }
}
