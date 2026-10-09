import * as vscode from "vscode";
import type { Api, Problem } from "./api";
import { ApiError } from "./api";
import { GroupBy, groupProblems, IMPORTANCE_HELP, SortBy, stars, statusLabel } from "./model";

export class GroupNode {
  readonly kind = "group" as const;
  constructor(readonly label: string, readonly rows: Problem[], readonly solved: number, readonly top: number) {}
}
export class ProblemNode {
  readonly kind = "problem" as const;
  constructor(readonly p: Problem) {}
}
export type Node = GroupNode | ProblemNode;

export class ProblemTreeProvider implements vscode.TreeDataProvider<Node> {
  private readonly emitter = new vscode.EventEmitter<Node | undefined>();
  readonly onDidChangeTreeData = this.emitter.event;
  rows: Problem[] = [];
  genres: string[] = [];
  solved = 0;
  total = 0;
  lastError?: string;

  constructor(private readonly api: Api, private readonly output: vscode.OutputChannel) {}

  private cfg<T>(key: string, dflt: T): T {
    return vscode.workspace.getConfiguration("mogi").get<T>(key, dflt);
  }
  get groupBy(): GroupBy { return this.cfg<GroupBy>("groupBy", "genre"); }
  get sortBy(): SortBy { return this.cfg<SortBy>("sortBy", "importance"); }
  get hideSolved(): boolean { return this.cfg<boolean>("hideSolved", false); }

  async refresh(): Promise<void> {
    try {
      const data = await this.api.problems();
      this.rows = data.problems;
      this.genres = data.genres || [];
      this.solved = data.solved;
      this.total = data.total;
      this.lastError = undefined;
    } catch (e) {
      this.lastError = (e as Error).message;
      if (!(e instanceof ApiError && e.status === 401)) {
        this.output.appendLine(`refresh failed: ${this.lastError}`);
      }
    }
    this.emitter.fire(undefined);
  }

  repaint(): void { this.emitter.fire(undefined); }

  /** Update one row in place after a meta change, without a round trip. */
  patch(pid: string, fields: Partial<Problem>): void {
    const row = this.rows.find(r => r.pid === pid);
    if (row) Object.assign(row, fields);
    if (fields.genre && !this.genres.includes(fields.genre)) this.genres = [...this.genres, fields.genre].sort();
    this.emitter.fire(undefined);
  }

  getChildren(node?: Node): Node[] {
    if (!node) {
      const groups = groupProblems(this.rows, this.groupBy, this.sortBy, this.hideSolved);
      if (this.groupBy === "none") return (groups[0]?.rows || []).map(p => new ProblemNode(p));
      return groups.map(g => new GroupNode(g.label, g.rows, g.solved, g.top));
    }
    if (node.kind === "group") return node.rows.map(p => new ProblemNode(p));
    return [];
  }

  getTreeItem(node: Node): vscode.TreeItem {
    if (node.kind === "group") {
      const item = new vscode.TreeItem(node.label, vscode.TreeItemCollapsibleState.Collapsed);
      item.description = `${node.solved}/${node.rows.length}` + (this.sortBy === "importance" ? ` · top ${node.top}` : "");
      item.contextValue = "group";
      item.iconPath = new vscode.ThemeIcon("folder");
      item.tooltip = `${node.label}: ${node.solved} of ${node.rows.length} solved`;
      return item;
    }
    const p = node.p;
    const item = new vscode.TreeItem(`${p.id}  ${p.title}`, vscode.TreeItemCollapsibleState.None);
    item.id = p.pid;
    item.description = `${p.importance || 0}${p.priority ? " " + stars(p.priority) : ""}` +
      (p.tags?.length ? `  #${p.tags.join(" #")}` : "");
    item.contextValue = "problem";
    item.command = { command: "mogi.openProblem", title: "Open problem", arguments: [p.pid] };
    item.iconPath = p.status === "solved"
      ? new vscode.ThemeIcon("pass-filled", new vscode.ThemeColor("charts.green"))
      : p.status === "attempted"
        ? new vscode.ThemeIcon("circle-filled", new vscode.ThemeColor("charts.yellow"))
        : new vscode.ThemeIcon("circle-large-outline");
    const md = new vscode.MarkdownString(undefined, true);
    md.appendMarkdown(`**${p.id} — ${p.title}**\n\n`);
    md.appendMarkdown(`${p.corpus} · Tier ${p.tier} · ${p.genre}` +
      (p.genre_corpus && p.genre_corpus !== p.genre ? ` _(corpus: ${p.genre_corpus})_` : "") + `\n\n`);
    md.appendMarkdown(`importance **${p.importance || 0}**${p.rank ? ` · shape rank #${p.rank}` : ""}` +
      ` · seen ${p.pubs || 1}× · ${p.family_n || 0} in genre · ${statusLabel(p)}` +
      (p.attempts ? ` (${p.attempts} attempts)` : "") + `\n\n`);
    if (p.priority) md.appendMarkdown(`priority ${stars(p.priority)}\n\n`);
    if (p.practice_url) md.appendMarkdown(`practice: [${"⭐".repeat(p.practice_stars || 0) || "link"}](${p.practice_url})\n\n`);
    md.appendMarkdown(`_${IMPORTANCE_HELP}_`);
    item.tooltip = md;
    return item;
  }
}
