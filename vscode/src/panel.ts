// The statement panel: a webview beside the editor with the problem text,
// required API, Run / Submit buttons, and the LeetCode-style verdict console.
import * as vscode from "vscode";
import type { ProblemDetail, Verdict } from "./api";
import { IMPORTANCE_HELP, stars, VERDICT_NAMES } from "./model";

export type PanelMessage =
  | { type: "run" } | { type: "submit" } | { type: "insertStub" } | { type: "loadAC" }
  | { type: "openWeb" } | { type: "openNext" } | { type: "openLink"; url: string }
  | { type: "setPriority"; value: number } | { type: "editGenre" } | { type: "editTags" };

const esc = (s: unknown) => String(s ?? "").replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]!));

async function renderMarkdown(md: string): Promise<string> {
  try {
    const html = await vscode.commands.executeCommand<string>("markdown.api.render", md);
    if (typeof html === "string" && html.trim()) return html;
  } catch { /* built-in markdown extension unavailable */ }
  return `<pre>${esc(md)}</pre>`;
}

export function verdictHtml(res: Verdict, mode: string): string {
  const v = res.verdict;
  let meta = `${res.ms} ms`;
  if (v === "AC") meta += ` · ${res.passed}${res.total ? "/" + res.total : ""} checks`;
  else if (res.passed != null && v !== "CE") meta += ` · ${res.passed} check${res.passed === 1 ? "" : "s"} passed before failure`;
  let h = `<div class="vhead v-${esc(v)}"><span class="vtitle">${esc(VERDICT_NAMES[v] || v)}</span>` +
    `<span class="muted">${esc(meta)} · ${esc(mode)}</span></div>`;
  if (v !== "AC" && res.detail) h += `<div class="muted detail">${esc(res.detail)}</div>`;
  const cases = res.cases || [];
  const passes = cases.filter(c => c.status === "pass").length;
  if (cases.length) {
    h += `<div class="chips">` + cases.map((c, i) =>
      `<span class="chip ${c.status}">${c.status === "pass" ? "✓" : "✕"} ${i + 1}</span>`).join("") +
      `</div>`;
    for (const [i, c] of cases.entries()) {
      if (c.status === "pass") continue;
      h += `<div class="case"><div class="label">✕ Case ${i + 1} — ${esc(c.label)}</div>`;
      if (c.call) h += io("Input (the failing test call)", c.call);
      if (res.stdout_tail) h += io("Stdout (your prints)", res.stdout_tail);
      if (c.got !== undefined && c.got !== "") h += io("Output", c.got, "bad");
      if (c.want !== undefined && c.want !== "") h += io("Expected", c.want, "good");
      h += `</div>`;
    }
    if (v === "AC") h += `<div class="muted">${passes} checks passed</div>`;
  }
  if (res.trace && v !== "AC") h += io("Where it failed", res.trace);
  if (v === "CE" && !res.trace) h += io("Where", res.detail);
  if (res.sync?.state === "done") h += `<div class="good">↑ synced to GitHub: ${esc(res.sync.path)}</div>`;
  if (res.sync && (res.sync.state === "error" || res.sync.state === "skipped"))
    h += `<div class="bad">⚠ GitHub sync ${esc(res.sync.state)}: ${esc(res.sync.why)}</div>`;
  return h;

  function io(label: string, content: string, cls = ""): string {
    return `<div class="iolabel">${esc(label)}</div><pre class="iobox ${cls}">${esc(content)}</pre>`;
  }
}

export class StatementPanel {
  private static current?: StatementPanel;
  private disposed = false;
  detail: ProblemDetail;

  static get currentDetail(): ProblemDetail | undefined { return StatementPanel.current?.detail; }
  static get isOpen(): boolean { return !!StatementPanel.current; }

  static async show(context: vscode.ExtensionContext, detail: ProblemDetail,
                    onMessage: (m: PanelMessage, d: ProblemDetail) => void, reveal = true): Promise<StatementPanel> {
    if (!StatementPanel.current) {
      const panel = vscode.window.createWebviewPanel("mogiStatement", "mogi", {
        viewColumn: vscode.ViewColumn.Beside, preserveFocus: true,
      }, { enableScripts: true, retainContextWhenHidden: true, enableFindWidget: true,
           localResourceRoots: [vscode.Uri.joinPath(context.extensionUri, "media")] });
      StatementPanel.current = new StatementPanel(panel, detail);
      panel.onDidDispose(() => { StatementPanel.current!.disposed = true; StatementPanel.current = undefined; });
      panel.webview.onDidReceiveMessage((m: PanelMessage) => onMessage(m, StatementPanel.current!.detail));
    }
    const cur = StatementPanel.current;
    await cur.setProblem(detail);
    if (reveal) cur.panel.reveal(undefined, true);
    return cur;
  }

  static showVerdict(res: Verdict, mode: string): void {
    const cur = StatementPanel.current;
    if (!cur) return;
    void cur.panel.webview.postMessage({ type: "verdict", html: verdictHtml(res, mode) });
    cur.panel.reveal(undefined, true);
  }

  static setBusy(text: string): void {
    void StatementPanel.current?.panel.webview.postMessage({ type: "busy", text });
  }

  private constructor(private readonly panel: vscode.WebviewPanel, detail: ProblemDetail) {
    this.detail = detail;
  }

  async setProblem(detail: ProblemDetail): Promise<void> {
    if (this.disposed) return;
    this.detail = detail;
    this.panel.title = `${detail.id} — ${detail.title}`;
    const statement = await renderMarkdown(detail.statement || "");
    this.panel.webview.html = this.html(detail, statement);
  }

  /** Re-render only the header after a genre / priority / tags change. */
  updateMeta(fields: Partial<ProblemDetail>): void {
    Object.assign(this.detail, fields);
    void this.panel.webview.postMessage({ type: "meta", html: headerHtml(this.detail) });
  }

  private html(d: ProblemDetail, statementHtml: string): string {
    const nonce = Math.random().toString(36).slice(2) + Date.now().toString(36);
    const csp = `default-src 'none'; style-src ${this.panel.webview.cspSource} 'unsafe-inline'; ` +
      `script-src 'nonce-${nonce}'; img-src ${this.panel.webview.cspSource} https: data:;`;
    const required = (d.required || []).map(r => `<code class="req">${esc(r)}</code>`).join(" ");
    return `<!doctype html><html><head><meta charset="utf-8">
<meta http-equiv="Content-Security-Policy" content="${csp}">
<style>
  body { font-family: var(--vscode-font-family); font-size: var(--vscode-font-size); color: var(--vscode-foreground);
         padding: 0 18px 24px; line-height: 1.5; }
  a { color: var(--vscode-textLink-foreground); text-decoration: none; } a:hover { text-decoration: underline; }
  code, pre { font-family: var(--vscode-editor-font-family); font-size: 0.92em; }
  pre { background: var(--vscode-textCodeBlock-background); padding: 10px 12px; border-radius: 6px; overflow: auto; }
  h1 { font-size: 1.25em; margin: 14px 0 6px; } h2 { font-size: 1.05em; margin-top: 1.3em; }
  blockquote { border-left: 3px solid var(--vscode-textBlockQuote-border); margin: 0; padding-left: 12px; color: var(--vscode-descriptionForeground); }
  table { border-collapse: collapse; } th, td { border: 1px solid var(--vscode-panel-border); padding: 3px 9px; }
  .muted { color: var(--vscode-descriptionForeground); font-size: .9em; }
  .hdr { position: sticky; top: 0; background: var(--vscode-editor-background); padding: 10px 0 8px; z-index: 2;
         border-bottom: 1px solid var(--vscode-panel-border); }
  .row { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; margin-top: 6px; }
  .chip { display: inline-block; border: 1px solid var(--vscode-panel-border); border-radius: 10px; padding: 0 8px; font-size: .8em;
          color: var(--vscode-descriptionForeground); }
  .chip.genre { color: var(--vscode-textLink-foreground); cursor: pointer; }
  .chip.tag { color: var(--vscode-charts-purple); }
  .chip.rank { color: var(--vscode-charts-yellow); }
  .chip.pass { color: var(--vscode-charts-green); } .chip.fail { color: var(--vscode-errorForeground); }
  .stars span { cursor: pointer; color: var(--vscode-disabledForeground); font-size: 1.05em; }
  .stars span.on { color: var(--vscode-charts-yellow); }
  .imp { display: inline-flex; align-items: center; gap: 6px; }
  .impbar { display: inline-block; width: 56px; height: 6px; background: var(--vscode-panel-border); border-radius: 3px; overflow: hidden; }
  .impbar i { display: block; height: 100%; background: var(--vscode-progressBar-background); }
  button { background: var(--vscode-button-secondaryBackground); color: var(--vscode-button-secondaryForeground); border: none;
           border-radius: 4px; padding: 5px 12px; cursor: pointer; font-family: inherit; }
  button:hover { background: var(--vscode-button-secondaryHoverBackground); }
  button.primary { background: var(--vscode-button-background); color: var(--vscode-button-foreground); }
  button.primary:hover { background: var(--vscode-button-hoverBackground); }
  kbd { font-size: .78em; opacity: .7; margin-left: 5px; }
  #verdict { margin-top: 14px; border: 1px solid var(--vscode-panel-border); border-radius: 6px; padding: 10px 14px; display: none; }
  #verdict.show { display: block; }
  .vhead { display: flex; gap: 14px; align-items: baseline; margin-bottom: 8px; } .vtitle { font-size: 1.3em; font-weight: 700; }
  .v-AC .vtitle { color: var(--vscode-charts-green); } .v-WA .vtitle, .v-CE .vtitle { color: var(--vscode-errorForeground); }
  .v-RE .vtitle { color: var(--vscode-charts-yellow); } .v-TLE .vtitle { color: var(--vscode-charts-purple); }
  .v-PENDING .vtitle { color: var(--vscode-textLink-foreground); }
  .chips { display: flex; flex-wrap: wrap; gap: 6px; margin: 6px 0 10px; }
  .case { margin-top: 8px; } .case .label { font-weight: 600; }
  .iolabel { color: var(--vscode-descriptionForeground); font-size: .85em; margin: 10px 0 3px; }
  .iobox { margin: 0; white-space: pre-wrap; overflow-wrap: anywhere; } .iobox.bad { color: var(--vscode-errorForeground); }
  .iobox.good, .good { color: var(--vscode-charts-green); } .bad { color: var(--vscode-errorForeground); }
  .req { padding: 1px 6px; border: 1px solid var(--vscode-panel-border); border-radius: 8px; }
  details { margin-top: 10px; } summary { cursor: pointer; color: var(--vscode-descriptionForeground); }
</style></head><body>
<div class="hdr" id="hdr">${headerHtml(d)}</div>
<div class="row" style="margin:10px 0 4px">
  <button class="primary" data-cmd="run">▶ Run tests<kbd>Alt+R</kbd></button>
  <button data-cmd="submit">Submit<kbd>Alt+S</kbd></button>
  <button data-cmd="insertStub">Insert stub</button>
  ${d.ac_code ? `<button data-cmd="loadAC">Load my accepted solution</button>` : ""}
  <button data-cmd="openWeb">Open on the web</button>
  <span class="muted" id="busy"></span>
</div>
<div id="verdict"></div>
<div id="statement">${statementHtml}</div>
<h2>Required API</h2>
<p class="muted">The tests call these top-level names — your file must define them. Your own
  <code>if __name__ == "__main__":</code> block is stripped before judging.</p>
<p>${required || "—"}</p>
<details><summary>starter stub</summary><pre>${esc(d.stub || "")}</pre></details>
${d.solved && d.analysis ? `<details><summary>🔓 analysis (unlocked)</summary><div id="analysis"></div></details>` : ""}
${d.solved && d.reference ? `<details><summary>🔓 reference solution (unlocked)</summary><pre>${esc(d.reference)}</pre></details>` : ""}
${d.solved && d.tests ? `<details><summary>🔓 tests (unlocked)</summary><pre>${esc(d.tests)}</pre></details>` : ""}
<script nonce="${nonce}">
  const vscode = acquireVsCodeApi();
  const analysis = ${JSON.stringify(d.solved && d.analysis ? d.analysis : "")};
  if (analysis) { const el = document.getElementById("analysis"); el.innerHTML = "<pre>" + analysis.replace(/[&<>]/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;"}[c])) + "</pre>"; }
  function wire() {
    document.querySelectorAll("[data-cmd]").forEach(b => b.onclick = () => vscode.postMessage({ type: b.dataset.cmd }));
    document.querySelectorAll(".stars span").forEach(s => s.onclick = () => {
      const k = +s.dataset.k, cur = +s.parentElement.dataset.cur;
      vscode.postMessage({ type: "setPriority", value: k === cur ? 0 : k });
    });
    document.querySelectorAll("[data-link]").forEach(a => a.onclick = (e) => { e.preventDefault(); vscode.postMessage({ type: "openLink", url: a.dataset.link }); });
    const g = document.getElementById("genreChip"); if (g) g.onclick = () => vscode.postMessage({ type: "editGenre" });
    const t = document.getElementById("tagsBtn"); if (t) t.onclick = () => vscode.postMessage({ type: "editTags" });
    const n = document.getElementById("nextBtn"); if (n) n.onclick = () => vscode.postMessage({ type: "openNext" });
  }
  wire();
  window.addEventListener("message", e => {
    const m = e.data;
    if (m.type === "verdict") { const v = document.getElementById("verdict"); v.className = "show"; v.innerHTML = m.html; document.getElementById("busy").textContent = ""; v.scrollIntoView({ block: "nearest" }); }
    if (m.type === "busy") { document.getElementById("busy").textContent = m.text; }
    if (m.type === "meta") { document.getElementById("hdr").innerHTML = m.html; wire(); }
  });
</script></body></html>`;
  }
}

function headerHtml(d: ProblemDetail): string {
  const pr = d.practice || ({} as ProblemDetail["practice"]);
  const links: string[] = [];
  if (d.link) links.push(`<a href="#" data-link="${esc(d.link)}">source ↗</a>`);
  if (pr.url) links.push(`<a href="#" data-link="${esc(pr.url)}" title="${esc(pr.note || "")}">practice: ${esc(pr.label)} ${"⭐".repeat(pr.stars || 0)} ↗</a>`);
  else if (pr.note) links.push(`<span class="muted" title="${esc(pr.note)}">no judge hosts this one</span>`);
  if (d.next) links.push(`<a href="#" id="nextBtn" title="${esc(d.next.title)}">next${d.next.same_genre ? " in genre" : ""}: ${esc(d.next.id)} →</a>`);
  const prio = d.priority || 0;
  const starsHtml = `<span class="stars" data-cur="${prio}" title="your priority — click to set, click again to clear">` +
    [1, 2, 3, 4, 5].map(k => `<span data-k="${k}" class="${k <= prio ? "on" : ""}">★</span>`).join("") + `</span>`;
  return `<h1>${esc(d.id)} — ${esc(d.title)} ${d.solved ? `<span class="chip pass">solved</span>` : d.status === "attempted" ? `<span class="chip">attempted</span>` : ""}</h1>
<div class="row">
  <span class="chip">${esc(d.corpus)}</span><span class="chip">Tier ${esc(d.tier)}</span>
  <span class="chip genre" id="genreChip" title="genre — click to change${d.genre_corpus && d.genre_corpus !== d.genre ? ` (corpus: ${esc(d.genre_corpus)})` : ""}">${esc(d.genre || "—")}</span>
  ${starsHtml}
  <span class="imp" title="${esc(IMPORTANCE_HELP)}"><span class="impbar"><i style="width:${d.importance || 0}%"></i></span>${d.importance || 0}</span>
  ${d.rank ? `<span class="chip rank" title="shape rank in the Amazon README">#${d.rank}</span>` : ""}
  <span class="muted" title="publications · problems sharing the genre">seen ${d.pubs || 1}× · ${d.family_n || 0} in genre</span>
  ${(d.tags || []).map(t => `<span class="chip tag">${esc(t)}</span>`).join("")}
  <a href="#" id="tagsBtn" class="muted" title="edit tags">${d.tags?.length ? "edit tags" : "+ tag"}</a>
</div>
<div class="row muted">${links.join(" · ")}</div>`;
}

export { stars };
