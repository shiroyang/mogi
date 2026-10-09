// Shared config file (~/.config/mogi/config.json) — the same one the CLI writes.
import * as fs from "fs";
import * as os from "os";
import * as path from "path";
import * as vscode from "vscode";

export const DEFAULT_SITE = "https://mogi-judge.vercel.app";
export const DEFAULT_WORKSPACE = "~/mogi";

export interface FileConfig {
  site?: string;
  token?: string;
  login?: string;
  workspace?: string;
}

export function expandHome(p: string): string {
  return p.startsWith("~") ? path.join(os.homedir(), p.slice(1)) : p;
}

export function configPath(): string {
  if (process.env.MOGI_CONFIG) return expandHome(process.env.MOGI_CONFIG);
  const base = process.env.XDG_CONFIG_HOME || path.join(os.homedir(), ".config");
  return path.join(base, "mogi", "config.json");
}

export function readFileConfig(): FileConfig {
  try {
    const data = JSON.parse(fs.readFileSync(configPath(), "utf8"));
    return data && typeof data === "object" ? (data as FileConfig) : {};
  } catch {
    return {};
  }
}

export function writeFileConfig(patch: FileConfig): void {
  const next: Record<string, unknown> = { ...readFileConfig(), ...patch };
  for (const k of Object.keys(next)) if (next[k] === undefined) delete next[k];
  const p = configPath();
  fs.mkdirSync(path.dirname(p), { recursive: true });
  fs.writeFileSync(p, JSON.stringify(next, null, 2) + "\n", { mode: 0o600 });
  try { fs.chmodSync(p, 0o600); } catch { /* best effort */ }
}

function setting(key: "site" | "workspace"): string | undefined {
  const v = vscode.workspace.getConfiguration("mogi").get<string>(key);
  return v && v.trim() ? v.trim() : undefined;
}

export function site(): string {
  return (setting("site") || readFileConfig().site || DEFAULT_SITE).replace(/\/+$/, "");
}

export function workspaceDir(): string {
  return expandHome(setting("workspace") || readFileConfig().workspace || DEFAULT_WORKSPACE);
}

export function token(): string | undefined {
  return readFileConfig().token;
}
