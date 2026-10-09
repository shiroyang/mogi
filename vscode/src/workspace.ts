// Local problem directories — identical layout to the CLI (cli/mogi_cli/workspace.py):
//   <workspace>/<Corpus>/<slug>/{problem.md, solution.py, .mogi.json}
import * as fs from "fs";
import * as path from "path";
import type { ProblemDetail } from "./api";

export const MARKER = ".mogi.json";
export const SOLUTION = "solution.py";
export const STATEMENT = "problem.md";

export interface Marker { pid: string; id: string; title: string; corpus: string; slug?: string }

export function problemDir(ws: string, p: ProblemDetail): string {
  const slug = p.slug || `${p.id}_${p.title || ""}`.replace(/[^A-Za-z0-9_]+/g, "_").slice(0, 60);
  return path.join(ws, p.corpus, slug);
}

export function readMarker(file: string): Marker | undefined {
  try {
    const m = JSON.parse(fs.readFileSync(file, "utf8"));
    return m && typeof m === "object" && m.pid ? (m as Marker) : undefined;
  } catch {
    return undefined;
  }
}

/** Walk up from a file or directory to the nearest .mogi.json. */
export function findMarker(start: string): { dir: string; marker: Marker } | undefined {
  let cur = start;
  try { if (fs.statSync(cur).isFile()) cur = path.dirname(cur); } catch { return undefined; }
  for (;;) {
    const m = readMarker(path.join(cur, MARKER));
    if (m) return { dir: cur, marker: m };
    const parent = path.dirname(cur);
    if (parent === cur) return undefined;
    cur = parent;
  }
}

export function dirForPid(ws: string, pid: string): string | undefined {
  let corpora: string[] = [];
  try { corpora = fs.readdirSync(ws); } catch { return undefined; }
  for (const c of corpora) {
    const cdir = path.join(ws, c);
    let subs: string[] = [];
    try { subs = fs.readdirSync(cdir); } catch { continue; }
    for (const s of subs) {
      const m = readMarker(path.join(cdir, s, MARKER));
      if (m?.pid === pid) return path.join(cdir, s);
    }
  }
  return undefined;
}

export function renderProblemMd(p: ProblemDetail): string {
  const pr = p.practice || ({} as ProblemDetail["practice"]);
  const rows: [string, string][] = [
    ["Corpus", `${p.corpus} · Tier ${p.tier}${p.round ? ` · ${p.round}` : ""}${p.published ? ` · published ${p.published}` : ""}`],
    ["Genre", p.genre + (p.genre_corpus && p.genre_corpus !== p.genre ? ` (corpus: ${p.genre_corpus})` : "")],
    ["Importance", `${p.importance || 0}/100${p.rank ? ` · shape rank #${p.rank}` : ""}${p.priority ? ` · priority ${"★".repeat(p.priority)}` : ""}`],
    ["Seen", `${p.pubs || 1} publication(s) · ${p.family_n || 0} problems share the genre`],
    ["Source", p.link || "—"],
  ];
  if (pr.url) rows.push(["Practice", `[${pr.label || "judge"}](${pr.url}) ${"⭐".repeat(pr.stars || 0)}${pr.note ? ` — ${pr.note}` : ""}`]);
  if (p.tags?.length) rows.push(["Tags", p.tags.join(", ")]);
  const table = "| | |\n|---|---|\n" + rows.map(([k, v]) => `| **${k}** | ${v} |`).join("\n");
  const required = (p.required || []).map(r => `\`${r}\``).join(" ") || "—";
  return [
    `# ${p.id} — ${p.title}`, "", table, "", (p.statement || "").trim(), "",
    "## Required API", "", `The tests call these top-level names: ${required}`, "",
    "Your own `if __name__ == \"__main__\":` block is stripped before judging, so scratch tests there are safe.", "",
    "```python", (p.stub || "").trimEnd(), "```", "", "---",
    `\`mogi run\` · \`mogi submit\` from this directory — or Alt+R / Alt+S in VS Code.`, "",
  ].join("\n");
}

/** Create/refresh the directory. solution.py is kept unless reset. */
export function materialize(ws: string, p: ProblemDetail, reset = false): { dir: string; solution: string } {
  const dir = problemDir(ws, p);
  fs.mkdirSync(dir, { recursive: true });
  fs.writeFileSync(path.join(dir, STATEMENT), renderProblemMd(p));
  const solution = path.join(dir, SOLUTION);
  if (reset || !fs.existsSync(solution)) {
    const seed = p.ac_code || p.stub || "";
    const header = `# ${p.pid} — ${p.title}\n# statement: ./${STATEMENT}  ·  judge: Alt+R run · Alt+S submit (or mogi run / mogi submit)\n\n`;
    fs.writeFileSync(solution, header + seed.trimEnd() + "\n");
  }
  const marker: Marker = { pid: p.pid, id: p.id, title: p.title, corpus: p.corpus, slug: p.slug };
  fs.writeFileSync(path.join(dir, MARKER), JSON.stringify(marker, null, 2) + "\n");
  return { dir, solution };
}
