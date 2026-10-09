// LeetCode-style verdict console: header, case chips, the failing case's
// input / output / expected, where it failed, your stdout, GitHub sync.
import { useEffect, useState } from "react";
import type { Verdict } from "../api";
import { VERDICT_NAMES } from "../model";

function Io({ label, text, cls = "" }: { label: string; text?: string | null; cls?: string }) {
  if (text == null || text === "") return null;
  return (<><div className="iolabel">{label}</div><pre className={`iobox ${cls}`}>{text}</pre></>);
}

export function VerdictView({ res, mode }: { res: Verdict; mode: string }) {
  const cases = res.cases || [];
  const firstFail = cases.findIndex(c => c.status === "fail");
  const [sel, setSel] = useState(firstFail >= 0 ? firstFail : cases.length - 1);
  useEffect(() => { setSel(firstFail >= 0 ? firstFail : cases.length - 1); }, [res.sk, firstFail, cases.length]);
  const v = res.verdict;
  let meta = `${res.ms} ms`;
  if (v === "AC") meta += ` · ${res.passed}${res.total ? "/" + res.total : ""} checks`;
  else if (res.passed != null && v !== "CE") meta += ` · ${res.passed} check${res.passed === 1 ? "" : "s"} passed before failure`;
  const c = cases[sel];
  return (
    <section className={`verdict ${v}`} aria-live="polite">
      <div className="head">
        <span className={`name v-${v}`}>{VERDICT_NAMES[v] || v}</span>
        <span className="faint" style={{ fontSize: 13.5 }}>{meta} · {mode}</span>
      </div>
      {v !== "AC" && res.detail && <div className="muted" style={{ fontSize: 14, marginBottom: 6 }}>{res.detail}</div>}
      {cases.length > 0 && (
        <div className="cases" role="tablist">
          {cases.map((cs, i) => (
            <button key={i} role="tab" aria-selected={i === sel} className={`case ${cs.status} ${i === sel ? "on" : ""}`} onClick={() => setSel(i)}>
              <span className="ic">{cs.status === "pass" ? "✓" : "✕"}</span>Case {i + 1}
            </button>
          ))}
        </div>
      )}
      {c && c.status === "pass" && (<><Io label="Check" text={c.label} /><div className="iolabel" style={{ color: "var(--ok)" }}>✓ passed</div></>)}
      {c && c.status === "fail" && (
        <>
          <Io label="Input (the failing test call)" text={c.call || c.label} />
          <Io label="Stdout (your prints)" text={res.stdout_tail} />
          <Io label="Output" text={c.got} cls="bad" />
          <Io label="Expected" text={c.want} cls="good" />
          <Io label="Where it failed" text={res.trace} />
        </>
      )}
      {!cases.length && v === "CE" && <Io label="Where" text={res.trace || res.detail} />}
      {res.sync?.state === "done" && <div className="iolabel" style={{ color: "var(--ok)" }}>↑ synced to GitHub: {res.sync.path}</div>}
      {res.sync && (res.sync.state === "error" || res.sync.state === "skipped") && (
        <div className="iolabel" style={{ color: "var(--warn)" }}>⚠ GitHub sync {res.sync.state}: {res.sync.why}</div>
      )}
    </section>
  );
}
