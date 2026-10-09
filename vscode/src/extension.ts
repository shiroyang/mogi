import * as fs from "fs";
import * as path from "path";
import * as vscode from "vscode";
import { Api, ApiError, Problem, ProblemDetail } from "./api";
import * as config from "./config";
import { login } from "./login";
import { failingLine, GROUP_BYS, pickBest, SORT_BYS, stars, VERDICT_NAMES } from "./model";
import { PanelMessage, StatementPanel } from "./panel";
import { GroupNode, ProblemNode, ProblemTreeProvider } from "./tree";
import { dirForPid, findMarker, materialize, SOLUTION } from "./workspace";

let api: Api;
let tree: ProblemTreeProvider;
let output: vscode.OutputChannel;
let diagnostics: vscode.DiagnosticCollection;
let statusItem: vscode.StatusBarItem;
let extContext: vscode.ExtensionContext;

const setContext = (k: string, v: unknown) => vscode.commands.executeCommand("setContext", k, v);

export async function activate(context: vscode.ExtensionContext): Promise<void> {
  extContext = context;
  output = vscode.window.createOutputChannel("mogi");
  api = new Api(() => config.site(), () => config.token());
  diagnostics = vscode.languages.createDiagnosticCollection("mogi");
  tree = new ProblemTreeProvider(api, output);
  statusItem = vscode.window.createStatusBarItem(vscode.StatusBarAlignment.Left, 50);
  statusItem.command = "mogi.search";
  statusItem.text = "$(law) mogi";
  statusItem.tooltip = "mogi — search problems";
  statusItem.show();

  context.subscriptions.push(
    output, diagnostics, statusItem,
    vscode.window.registerTreeDataProvider("mogiProblems", tree),
    vscode.window.onDidChangeActiveTextEditor(ed => void onEditorChanged(ed)),
    vscode.workspace.onDidChangeConfiguration(e => {
      if (e.affectsConfiguration("mogi.groupBy") || e.affectsConfiguration("mogi.sortBy") || e.affectsConfiguration("mogi.hideSolved")) tree.repaint();
      if (e.affectsConfiguration("mogi.site")) void refresh();
    }),
    cmd("mogi.login", doLogin),
    cmd("mogi.logout", doLogout),
    cmd("mogi.refresh", refresh),
    cmd("mogi.search", search),
    cmd("mogi.pickOne", pickOne),
    cmd("mogi.groupBy", chooseGroupBy),
    cmd("mogi.sortBy", chooseSortBy),
    cmd("mogi.toggleSolved", async () => {
      const c = vscode.workspace.getConfiguration("mogi");
      await c.update("hideSolved", !c.get<boolean>("hideSolved", false), vscode.ConfigurationTarget.Global);
    }),
    cmd("mogi.openProblem", (pid: string) => openProblem(pid)),
    cmd("mogi.showStatement", showStatementForActive),
    cmd("mogi.run", () => judge("run")),
    cmd("mogi.submit", () => judge("submit")),
    cmd("mogi.setPriority", (node?: ProblemNode | GroupNode) => setPriority(targetOf(node))),
    cmd("mogi.setGenre", (node?: ProblemNode | GroupNode) => setGenre(targetOf(node))),
    cmd("mogi.setTags", (node?: ProblemNode | GroupNode) => setTags(targetOf(node))),
    cmd("mogi.openInBrowser", (node?: ProblemNode | GroupNode) => openInBrowser(targetOf(node))),
    cmd("mogi.openWorkspaceFolder", openWorkspaceFolder),
  );

  await setContext("mogi.signedIn", !!config.token());
  await onEditorChanged(vscode.window.activeTextEditor);
  if (config.token()) await refresh();
}

export function deactivate(): void { /* nothing to clean up beyond subscriptions */ }

function cmd(id: string, fn: (...args: any[]) => unknown): vscode.Disposable {
  return vscode.commands.registerCommand(id, async (...args: any[]) => {
    try {
      await fn(...args);
    } catch (e) {
      const msg = (e as Error).message || String(e);
      output.appendLine(`${id}: ${msg}`);
      if (e instanceof ApiError && e.status === 401) {
        const pick = await vscode.window.showWarningMessage("mogi: not signed in.", "Sign in with GitHub");
        if (pick) await doLogin();
      } else {
        void vscode.window.showErrorMessage(`mogi: ${msg}`);
      }
    }
  });
}

// ------------------------------------------------------------------ auth
async function doLogin(): Promise<void> {
  const res = await vscode.window.withProgress(
    { location: vscode.ProgressLocation.Notification, title: "mogi: finish signing in with GitHub in your browser…", cancellable: false },
    () => login(config.site()));
  config.writeFileConfig({ token: res.token, login: res.login, site: config.readFileConfig().site || config.site() });
  await setContext("mogi.signedIn", true);
  void vscode.window.showInformationMessage(`mogi: signed in as @${res.login}`);
  await refresh();
}

async function doLogout(): Promise<void> {
  config.writeFileConfig({ token: undefined, login: undefined });
  await setContext("mogi.signedIn", false);
  tree.rows = [];
  tree.repaint();
}

// ------------------------------------------------------------------ tree
async function refresh(): Promise<void> {
  await tree.refresh();
  if (tree.lastError) {
    if (/not signed in/.test(tree.lastError)) await setContext("mogi.signedIn", false);
    statusItem.text = "$(law) mogi: offline";
    return;
  }
  statusItem.text = `$(law) mogi ${tree.solved}/${tree.total}`;
  statusItem.tooltip = `mogi — ${tree.solved} of ${tree.total} solved · click to search`;
}

async function chooseGroupBy(): Promise<void> {
  const cur = tree.groupBy;
  const pick = await vscode.window.showQuickPick(
    GROUP_BYS.map(g => ({ label: g === cur ? `$(check) ${g}` : `      ${g}`, value: g })),
    { placeHolder: "Group problems by…" });
  if (pick) await vscode.workspace.getConfiguration("mogi").update("groupBy", pick.value, vscode.ConfigurationTarget.Global);
}

async function chooseSortBy(): Promise<void> {
  const cur = tree.sortBy;
  const descr: Record<string, string> = {
    importance: "your ★ priority first, then the computed score", frequency: "publications, then genre size",
    id: "corpus / id", recent: "recently worked on", attempts: "most attempts",
  };
  const pick = await vscode.window.showQuickPick(
    SORT_BYS.map(s => ({ label: s === cur ? `$(check) ${s}` : `      ${s}`, description: descr[s], value: s })),
    { placeHolder: "Sort problems by…" });
  if (pick) await vscode.workspace.getConfiguration("mogi").update("sortBy", pick.value, vscode.ConfigurationTarget.Global);
}

function problemItem(p: Problem): vscode.QuickPickItem & { pid: string } {
  const icon = p.status === "solved" ? "$(pass-filled)" : p.status === "attempted" ? "$(circle-filled)" : "$(circle-large-outline)";
  return {
    label: `${icon} ${p.id}  ${p.title}`,
    description: `${p.genre} · ${p.importance}${p.priority ? " " + stars(p.priority) : ""}${p.tags?.length ? " · #" + p.tags.join(" #") : ""}`,
    detail: `${p.corpus} · Tier ${p.tier} · seen ${p.pubs || 1}× · ${p.family_n || 0} in genre`,
    pid: p.pid,
  };
}

async function ensureRows(): Promise<Problem[]> {
  if (!tree.rows.length) await refresh();
  if (tree.lastError) throw new ApiError(/not signed in/.test(tree.lastError) ? 401 : 0, tree.lastError);
  return tree.rows;
}

async function search(): Promise<void> {
  const rows = [...await ensureRows()].sort((a, b) => (b.priority || 0) * 1000 + b.importance - ((a.priority || 0) * 1000 + a.importance));
  const pick = await vscode.window.showQuickPick(rows.map(problemItem),
    { placeHolder: "Search by id, title, genre or #tag — sorted by importance", matchOnDescription: true, matchOnDetail: true });
  if (pick) await openProblem(pick.pid);
}

async function pickOne(): Promise<void> {
  const best = pickBest(await ensureRows());
  if (!best) { void vscode.window.showInformationMessage("mogi: everything is solved 🎉"); return; }
  await openProblem(best.pid);
}

// ------------------------------------------------------------------ open
async function openProblem(pid: string, opts: { openEditor?: boolean; reveal?: boolean } = {}): Promise<ProblemDetail> {
  const detail = await api.problem(pid);
  const { solution } = materialize(config.workspaceDir(), detail);
  if (opts.openEditor !== false) {
    const doc = await vscode.workspace.openTextDocument(solution);
    await vscode.window.showTextDocument(doc, { viewColumn: vscode.ViewColumn.One, preview: false });
  }
  await StatementPanel.show(extContext, detail, (m, d) => void onPanelMessage(m, d), opts.reveal !== false);
  await setContext("mogi.problemFile", true);
  return detail;
}

async function onEditorChanged(editor: vscode.TextEditor | undefined): Promise<void> {
  const found = editor && editor.document.uri.scheme === "file" ? findMarker(editor.document.uri.fsPath) : undefined;
  await setContext("mogi.problemFile", !!found);
  // follow: when switching between problems, the panel shows the right statement
  if (found && StatementPanel.isOpen && StatementPanel.currentDetail?.pid !== found.marker.pid) {
    try { await openProblem(found.marker.pid, { openEditor: false, reveal: false }); } catch (e) { output.appendLine(`follow: ${(e as Error).message}`); }
  }
}

async function showStatementForActive(): Promise<void> {
  const ed = vscode.window.activeTextEditor;
  const found = ed ? findMarker(ed.document.uri.fsPath) : undefined;
  if (!found) { await search(); return; }
  await openProblem(found.marker.pid, { openEditor: false });
}

async function onPanelMessage(m: PanelMessage, d: ProblemDetail): Promise<void> {
  try {
    switch (m.type) {
      case "run": await judge("run", d.pid); break;
      case "submit": await judge("submit", d.pid); break;
      case "insertStub": await replaceSolution(d, d.stub, "stub"); break;
      case "loadAC": await replaceSolution(d, d.ac_code || "", "accepted solution"); break;
      case "openWeb": await openInBrowser(d.pid); break;
      case "openNext": if (d.next) await openProblem(d.next.pid); break;
      case "openLink": await vscode.env.openExternal(vscode.Uri.parse(m.url)); break;
      case "setPriority": await applyMeta(d.pid, { priority: m.value }); break;
      case "editGenre": await setGenre(d.pid); break;
      case "editTags": await setTags(d.pid); break;
    }
  } catch (e) {
    void vscode.window.showErrorMessage(`mogi: ${(e as Error).message}`);
  }
}

async function replaceSolution(d: ProblemDetail, text: string, what: string): Promise<void> {
  const dir = dirForPid(config.workspaceDir(), d.pid);
  if (!dir) return;
  const file = path.join(dir, SOLUTION);
  const doc = await vscode.workspace.openTextDocument(file);
  const current = doc.getText();
  if (current.trim() && current.trim() !== text.trim()) {
    const ok = await vscode.window.showWarningMessage(`Replace solution.py with the ${what}?`, { modal: true }, "Replace");
    if (ok !== "Replace") return;
  }
  const editor = await vscode.window.showTextDocument(doc, { viewColumn: vscode.ViewColumn.One, preview: false });
  await editor.edit(b => b.replace(new vscode.Range(doc.positionAt(0), doc.positionAt(current.length)), text.trimEnd() + "\n"));
  await doc.save();
}

// ------------------------------------------------------------------ judge
async function judge(mode: "run" | "submit", pidHint?: string): Promise<void> {
  const ed = vscode.window.activeTextEditor;
  let found = ed && ed.document.uri.scheme === "file" ? findMarker(ed.document.uri.fsPath) : undefined;
  const pid = pidHint || found?.marker.pid || StatementPanel.currentDetail?.pid;
  if (!pid) { await search(); return; }
  if (!found || found.marker.pid !== pid) {
    const dir = dirForPid(config.workspaceDir(), pid);
    if (!dir) { await openProblem(pid); return; }
    found = { dir, marker: { pid, id: pid.split("/")[1], title: "", corpus: pid.split("/")[0] } };
  }
  const file = path.join(found.dir, SOLUTION);
  const open = vscode.workspace.textDocuments.find(d => d.uri.fsPath === file);
  if (open?.isDirty) await open.save();
  const code = fs.readFileSync(file, "utf8");
  if (!code.trim()) { void vscode.window.showWarningMessage("mogi: solution.py is empty"); return; }

  const id = found.marker.id || pid;
  statusItem.text = `$(sync~spin) mogi: judging ${id}…`;
  StatementPanel.setBusy(`judging (${mode})…`);
  diagnostics.delete(vscode.Uri.file(file));
  let res;
  try {
    res = await api.judge(pid, code, mode);
  } finally {
    statusItem.text = `$(law) mogi ${tree.solved}/${tree.total}`;
    StatementPanel.setBusy("");
  }
  output.appendLine(`${mode} ${pid}: ${res.verdict} ${res.detail || ""} (${res.ms} ms)`);

  if (!StatementPanel.isOpen || StatementPanel.currentDetail?.pid !== pid) {
    const detail = await api.problem(pid);
    await StatementPanel.show(extContext, detail, (m, d) => void onPanelMessage(m, d));
  }
  StatementPanel.showVerdict(res, mode);

  const line = failingLine(res.trace) ?? (res.verdict === "CE" ? failingLine(res.detail.replace(/.*— /, "")) : undefined);
  if (res.verdict !== "AC" && line) {
    const doc = open || await vscode.workspace.openTextDocument(file);
    const ln = Math.min(Math.max(line - 1, 0), doc.lineCount - 1);
    const range = doc.lineAt(ln).range;
    const diag = new vscode.Diagnostic(range, `${VERDICT_NAMES[res.verdict] || res.verdict}: ${res.detail}`,
      res.verdict === "TLE" ? vscode.DiagnosticSeverity.Warning : vscode.DiagnosticSeverity.Error);
    diag.source = "mogi";
    diagnostics.set(vscode.Uri.file(file), [diag]);
  }

  const name = VERDICT_NAMES[res.verdict] || res.verdict;
  if (res.verdict === "AC") {
    const parts = [`${name} · ${res.passed}/${res.total} checks · ${res.ms} ms`];
    if (mode === "submit" && res.sync?.state === "done") parts.push(`synced to GitHub (${res.sync.path})`);
    if (mode === "submit" && res.sync?.state && res.sync.state !== "done" && res.sync.state !== "superseded") parts.push(`sync ${res.sync.state}: ${res.sync.why}`);
    const actions = mode === "submit" && res.sync?.url ? ["Open on GitHub"] : [];
    const pick = await vscode.window.showInformationMessage(`mogi: ${parts.join(" · ")}`, ...actions);
    if (pick === "Open on GitHub" && res.sync?.url) await vscode.env.openExternal(vscode.Uri.parse(res.sync.url));
  } else {
    vscode.window.setStatusBarMessage(`mogi: ${name} — ${res.detail}`, 6000);
  }
  if (mode === "submit") {
    await refresh();
    if (res.verdict === "AC") {
      const detail = await api.problem(pid);  // spoilers now unlocked
      await StatementPanel.show(extContext, detail, (m, d) => void onPanelMessage(m, d), false);
      StatementPanel.showVerdict(res, mode);
    }
  }
}

// ------------------------------------------------------------------ meta
function targetOf(node?: ProblemNode | GroupNode | string): string | undefined {
  if (typeof node === "string") return node;
  if (node && node.kind === "problem") return node.p.pid;
  const ed = vscode.window.activeTextEditor;
  const found = ed ? findMarker(ed.document.uri.fsPath) : undefined;
  return found?.marker.pid || StatementPanel.currentDetail?.pid;
}

async function applyMeta(pid: string, patch: { genre?: string; priority?: number; tags?: string[] }): Promise<void> {
  const res = await api.setMeta(pid, patch);
  tree.patch(pid, { genre: res.genre, genre_corpus: res.genre_corpus, priority: res.priority, tags: res.tags });
  const cur = StatementPanel.currentDetail;
  if (cur && cur.pid === pid) {
    // re-render the header in place
    const panel = await StatementPanel.show(extContext, { ...cur, genre: res.genre, genre_corpus: res.genre_corpus, priority: res.priority, tags: res.tags },
      (m, d) => void onPanelMessage(m, d), false);
    void panel;
  }
}

async function rowFor(pid: string): Promise<Problem | undefined> {
  return (await ensureRows()).find(r => r.pid === pid);
}

async function setPriority(pid?: string): Promise<void> {
  if (!pid) { await search(); return; }
  const row = await rowFor(pid);
  const cur = row?.priority || 0;
  const pick = await vscode.window.showQuickPick(
    [0, 1, 2, 3, 4, 5].map(n => ({ label: n ? stars(n) : "— none", description: n === cur ? "current" : n === 5 ? "do this first" : "", value: n })),
    { placeHolder: `Priority for ${row?.id || pid} — stars sort above the computed importance` });
  if (pick) await applyMeta(pid, { priority: pick.value });
}

async function setGenre(pid?: string): Promise<void> {
  if (!pid) { await search(); return; }
  const row = await rowFor(pid);
  const items: (vscode.QuickPickItem & { value: string | null })[] = [
    ...tree.genres.map(g => ({ label: g, description: g === row?.genre ? "current" : "", value: g as string | null })),
    { label: "$(add) New genre…", value: "__new__" },
  ];
  if (row && row.genre_corpus && row.genre !== row.genre_corpus)
    items.push({ label: `$(discard) Reset to corpus genre (${row.genre_corpus})`, value: "" });
  const pick = await vscode.window.showQuickPick(items, { placeHolder: `Genre for ${row?.id || pid}` });
  if (!pick) return;
  let genre = pick.value;
  if (genre === "__new__") {
    genre = (await vscode.window.showInputBox({ prompt: "New genre name", validateInput: v => v.trim() ? undefined : "required" }))?.trim() ?? null;
    if (!genre) return;
  }
  if (genre === null) return;
  await applyMeta(pid, { genre });
}

async function setTags(pid?: string): Promise<void> {
  if (!pid) { await search(); return; }
  const row = await rowFor(pid);
  const value = await vscode.window.showInputBox({
    prompt: `Tags for ${row?.id || pid} — comma separated (e.g. redo, weak, mock-1)`,
    value: (row?.tags || []).join(", "),
  });
  if (value === undefined) return;
  await applyMeta(pid, { tags: value.split(",").map(t => t.trim()).filter(Boolean) });
}

async function openInBrowser(pid?: string): Promise<void> {
  const url = pid ? `${config.site()}/problem.html?id=${encodeURIComponent(pid)}` : `${config.site()}/`;
  await vscode.env.openExternal(vscode.Uri.parse(url));
}

async function openWorkspaceFolder(): Promise<void> {
  const ws = config.workspaceDir();
  fs.mkdirSync(ws, { recursive: true });
  const uri = vscode.Uri.file(ws);
  if (vscode.workspace.workspaceFolders?.some(f => f.uri.fsPath === ws)) return;
  vscode.workspace.updateWorkspaceFolders(vscode.workspace.workspaceFolders?.length ?? 0, 0, { uri, name: "mogi" });
}
