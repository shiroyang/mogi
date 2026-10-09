// One problem: statement, required API, editor, verdicts. Split view on desktop;
// Statement / Code / Result segments with a bottom action bar on phones.
import { useCallback, useEffect, useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router";
import { api, AuthError, problemHref, vscodeHref, type MetaResult, type ProblemDetail, type Verdict } from "../api";
import { Categorise, type MetaTarget } from "../components/Categorise";
import { Editor, type EditorHandle } from "../components/Editor";
import { Importance, Markdown, Segmented, Spinner, Stars, toast, TopBar } from "../components/ui";
import { VerdictView } from "../components/Verdict";
import { rememberLast, useAsync, useIsMobile } from "../hooks";
import { Login } from "./Login";

type LeftTab = "statement" | "api" | "analysis" | "reference" | "tests";
type MobileTab = "statement" | "code" | "result";
const IS_MAC = typeof navigator !== "undefined" && /Mac|iPhone|iPad/.test(navigator.platform);
const fmtDate = (s: number) => new Date(s * 1000).toISOString().slice(0, 16).replace("T", " ");

/** The corpus statement opens with its own `# ID — title` and front-matter table.
 * The page header already shows the title, genre and links, so the body starts at
 * the first section and the table becomes a collapsible "details" block. */
function splitStatement(md: string): { details: string; body: string } {
  const i = md.search(/^## /m);
  if (i < 0) return { details: "", body: md };
  const table = md.slice(0, i).split("\n").filter(l => l.startsWith("|")).join("\n");
  return { details: table, body: md.slice(i) };
}

export function Problem() {
  const { corpus = "", id = "" } = useParams();
  const pid = `${corpus}/${id}`;
  const mobile = useIsMobile();
  const nav = useNavigate();
  const { data: P, error, loading, reload, setData } = useAsync(() => api.problem(pid), [pid]);
  const editor = useRef<EditorHandle>(null);
  const [left, setLeft] = useState<LeftTab>("statement");
  const [mtab, setMtab] = useState<MobileTab>("statement");
  const [busy, setBusy] = useState<"run" | "submit" | null>(null);
  const [verdict, setVerdict] = useState<{ res: Verdict; mode: string } | null>(null);
  const [target, setTarget] = useState<MetaTarget | null>(null);
  const [split, setSplit] = useState<number>(() => +(localStorage.getItem("mogi-split-px") || 0));
  const draftKey = `mogi-draft-${pid}`;

  useEffect(() => { setVerdict(null); setLeft("statement"); setMtab("statement"); }, [pid]);
  useEffect(() => {
    if (!P) return;
    document.title = `mogi — ${P.id}`;
    rememberLast({ pid, id: P.id, title: P.title, genre: P.genre });
  }, [P, pid]);

  const onDraft = useCallback((v: string) => {
    try { localStorage.setItem(draftKey, v); } catch { /* ignore */ }
    if (P) rememberLast({ pid, id: P.id, title: P.title, genre: P.genre });
  }, [draftKey, P, pid]);

  async function judge(mode: "run" | "submit") {
    if (!P || busy) return;
    const code = editor.current?.getValue() || "";
    if (!code.trim()) { toast("Nothing to judge — the editor is empty"); return; }
    setBusy(mode);
    if (mobile) setMtab("result");
    try {
      const res = await api.judge(pid, code, mode);
      setVerdict({ res, mode });
      if (mode === "submit") {
        if (res.verdict === "AC" && !P.solved) toast("Accepted — analysis, reference and tests are unlocked");
        reload();  // submissions list, status, spoilers
      } else {
        setData(d => d);  // keep
      }
    } catch (e) {
      toast((e as Error).message);
    } finally {
      setBusy(null);
    }
  }
  const replaceCode = (text: string, what: string) => {
    const cur = editor.current?.getValue() || "";
    if (cur.trim() && cur.trim() !== text.trim() && !confirm(`Replace the editor contents with the ${what}?`)) return;
    editor.current?.setValue(text);
    onDraft(text);
    if (mobile) setMtab("code");
  };
  const onSaved = (res: MetaResult) => setData(d => ({ ...d, genre: res.genre, genre_corpus: res.genre_corpus, priority: res.priority, tags: res.tags }));
  async function setPriority(n: number) {
    if (!P) return;
    const prev = P.priority;
    setData(d => ({ ...d, priority: n }));
    try { onSaved(await api.setMeta(pid, { priority: n })); } catch (e) { setData(d => ({ ...d, priority: prev })); toast((e as Error).message); }
  }

  // desktop split gutter
  const onGutter = (e: React.PointerEvent) => {
    e.preventDefault();
    const start = e.clientX, base = (e.currentTarget.previousElementSibling as HTMLElement).getBoundingClientRect().width;
    const move = (ev: PointerEvent) => { const px = Math.min(Math.max(base + ev.clientX - start, 320), innerWidth - 420); setSplit(px); localStorage.setItem("mogi-split-px", String(px)); };
    const up = () => { removeEventListener("pointermove", move); removeEventListener("pointerup", up); document.body.classList.remove("resizing"); };
    document.body.classList.add("resizing");
    addEventListener("pointermove", move); addEventListener("pointerup", up);
  };

  if (error instanceof AuthError) return <Login />;
  if (error && !P) return (
    <><TopBar crumbs={[{ label: "problems", to: "/problems" }]} title={id} />
      <main className="page"><p style={{ color: "var(--bad)" }}>{error.message}</p><Link to="/problems">All problems</Link></main></>
  );
  if (!P) return (<><TopBar crumbs={[{ label: "problems", to: "/problems" }]} title={id} /><main className="page"><Spinner label="Loading…" /></main></>);

  const draft = localStorage.getItem(draftKey) ?? "";
  const initial = draft.trim() ? draft : (P.stub || "");
  const statusChip = P.solved ? <span className="chip ok">solved</span> : P.status === "attempted" ? <span className="chip">attempted</span> : null;
  const nextLink = P.next && (
    <Link className="chip" to={problemHref(P.next.pid)} title={P.next.title}>next{P.next.same_genre ? " in genre" : ""}: {P.next.id} →</Link>
  );
  const pr = P.practice || ({} as ProblemDetail["practice"]);
  const stmt = splitStatement(P.statement || "");
  const statementBlock = (
    <>
      <Markdown source={stmt.body} />
      {stmt.details && (
        <details className="spoiler"><summary>Details from the corpus (source, round, confidence, tier)</summary><Markdown source={stmt.details} className="facts" /></details>
      )}
    </>
  );
  const meta = (
    <div className="pmeta-head">
      <h1 className="ptitle-h">{P.title}</h1>
      <div className="row wrap">
        <button type="button" className="chip genre" title={`genre${P.genre_corpus && P.genre_corpus !== P.genre ? ` (corpus: ${P.genre_corpus})` : ""} — tap to change`}
          onClick={() => setTarget({ pid, id: P.id, genre: P.genre, genre_corpus: P.genre_corpus, priority: P.priority, tags: P.tags })}>{P.genre || "—"}</button>
        <Stars value={P.priority} onChange={n => void setPriority(n)} size={mobile ? "lg" : "sm"} />
        <Importance value={P.importance} rank={P.rank} />
        {P.tags.map(t => <span key={t} className="chip tag">{t}</span>)}
        <button type="button" className="btn ghost sm" onClick={() => setTarget({ pid, id: P.id, genre: P.genre, genre_corpus: P.genre_corpus, priority: P.priority, tags: P.tags })} aria-label="categorise">✎</button>
      </div>
      <div className="row wrap faint links">
        {P.link && <a href={P.link} target="_blank" rel="noopener">source ↗</a>}
        {P.alt_link && <a href={P.alt_link} target="_blank" rel="noopener">alt source ↗</a>}
        {pr.url ? <a href={pr.url} target="_blank" rel="noopener" title={pr.note || ""}>practice: {pr.label} {"⭐".repeat(pr.stars || 0)} ↗</a>
                : pr.note ? <span title={pr.note}>no judge hosts this one</span> : null}
        <span>{P.corpus} · Tier {P.tier}{P.round ? ` · ${P.round}` : ""}{P.published ? ` · ${P.published}` : ""} · seen {P.pubs}× · {P.family_n} in genre</span>
        {mobile && nextLink}
      </div>
    </div>
  );
  const apiTab = (
    <div>
      <p className="muted" style={{ marginTop: 0 }}>The tests call these top-level names — your code must define them. Your own
        <code> if __name__ == "__main__":</code> block is stripped before judging, so scratch tests there are safe.</p>
      <div className="row wrap">{P.required.map(r => <code key={r} className="chip">{r}</code>)}</div>
      <div className="row wrap" style={{ margin: "12px 0" }}>
        <button type="button" className="btn sm" onClick={() => replaceCode(P.stub || "", "starter stub")}>Load starter stub</button>
        {P.ac_code && <button type="button" className="btn sm" onClick={() => replaceCode(P.ac_code || "", "accepted solution")}>Load my accepted solution</button>}
      </div>
      <pre className="iobox">{P.stub}</pre>
    </div>
  );
  const spoilers = P.solved && (
    <>
      {P.analysis && <details className="spoiler"><summary>🔓 Analysis</summary><Markdown source={P.analysis} /></details>}
      {P.reference && <details className="spoiler"><summary>🔓 Reference solution</summary><pre className="iobox">{P.reference}</pre></details>}
      {P.tests && <details className="spoiler"><summary>🔓 Tests</summary><pre className="iobox">{P.tests}</pre></details>}
    </>
  );
  const submissions = P.submissions?.length ? (
    <ul className="subs">
      {P.submissions.map(s => (
        <li key={s.sk}><span className={`v-${s.verdict}`} style={{ fontWeight: 700, minWidth: 34 }}>{s.verdict}</span>
          <span style={{ minWidth: 48 }}>{s.mode}</span><span style={{ minWidth: 44 }}>{s.passed ?? ""}{s.total ? `/${s.total}` : ""}</span>
          <span style={{ minWidth: 60 }}>{s.ms} ms</span><span className="faint">{fmtDate(s.created)}</span>
          <span className="faint detail">{(s.detail || "").slice(0, 90)}</span></li>
      ))}
    </ul>
  ) : null;
  const results = (
    <>
      {busy && <div className="verdict PENDING"><Spinner label={`Judging (${busy})… running the problem’s own tests against your code`} /></div>}
      {!busy && verdict && <VerdictView res={verdict.res} mode={verdict.mode} />}
      {!busy && !verdict && <p className="faint" style={{ margin: "6px 2px" }}>Run the tests to see results here. Submitting counts; a run doesn’t.</p>}
      {submissions}
    </>
  );
  const vscodeBtn = !mobile && <a className="btn sm" href={vscodeHref(pid)} title="Open in VS Code (needs the mogi extension)">Open in VS Code</a>;

  if (mobile) {
    return (
      <>
        <TopBar crumbs={[{ label: "problems", to: "/problems" }]} title={P.id} right={statusChip} />
        <div className="pwrap mobile">
          <div className="segwrap">
            <Segmented options={[{ key: "statement", label: "Statement" }, { key: "code", label: "Code" }, { key: "result", label: busy ? "Judging…" : "Result" }]}
              value={mtab} onChange={setMtab} />
          </div>
          <div className="mbody" hidden={mtab !== "statement"}>
            {meta}
            {statementBlock}
            <h2 className="h2">Required API</h2>
            {apiTab}
            {spoilers}
          </div>
          <div className="mcode" hidden={mtab !== "code"}>
            <Editor ref={editor} initial={initial} onChange={onDraft} onRun={() => void judge("run")} onSubmit={() => void judge("submit")} />
          </div>
          <div className="mbody" hidden={mtab !== "result"}>{results}</div>
          <div className="actionbar">
            <button type="button" className="btn" disabled={!!busy} onClick={() => void judge("run")}>▶ Run tests</button>
            <button type="button" className="btn primary" disabled={!!busy} onClick={() => void judge("submit")}>Submit</button>
          </div>
        </div>
        <Categorise target={target} genres={P.genres || []} onClose={() => setTarget(null)} onSaved={onSaved} />
      </>
    );
  }

  return (
    <>
      <TopBar crumbs={[{ label: "problems", to: "/problems" }]} title={`${P.id} — ${P.title}`}
        right={<div className="row" style={{ gap: 10 }}>{statusChip}{nextLink}{vscodeBtn}</div>} />
      <div className="pwrap desktop" style={split ? { gridTemplateColumns: `${split}px 6px 1fr` } : undefined}>
        <section className="pane">
          <nav className="tabs" role="tablist">
            {([["statement", "Statement"], ["api", "Required API"]] as [LeftTab, string][]).concat(
              P.solved ? [["analysis", "Analysis 🔓"], ["reference", "Reference 🔓"], ["tests", "Tests 🔓"]] as [LeftTab, string][] : [])
              .map(([k, label]) => <button key={k} role="tab" aria-selected={left === k} className={left === k ? "on" : ""} onClick={() => setLeft(k)}>{label}</button>)}
          </nav>
          <div className="pane-body">
            {left === "statement" && <>{meta}{statementBlock}</>}
            {left === "api" && apiTab}
            {left === "analysis" && <Markdown source={P.analysis || ""} />}
            {left === "reference" && <pre className="iobox">{P.reference}</pre>}
            {left === "tests" && <pre className="iobox">{P.tests}</pre>}
          </div>
        </section>
        <div className="gutter" onPointerDown={onGutter} onDoubleClick={() => { setSplit(0); localStorage.removeItem("mogi-split-px"); }} title="drag to resize · double-click to reset" />
        <section className="pane">
          <div className="editor-wrap"><Editor ref={editor} initial={initial} onChange={onDraft} onRun={() => void judge("run")} onSubmit={() => void judge("submit")} /></div>
          <div className="toolbar">
            <button type="button" className="btn" disabled={!!busy} onClick={() => void judge("run")}>▶ Run tests<kbd>{IS_MAC ? "⌘↩" : "Ctrl+↩"}</kbd></button>
            <button type="button" className="btn primary" disabled={!!busy} onClick={() => void judge("submit")}>Submit<kbd>{IS_MAC ? "⇧⌘↩" : "Ctrl+Shift+↩"}</kbd></button>
            <span className="spacer" />
            <span className="faint" style={{ fontSize: 13 }}>draft autosaves in this browser</span>
          </div>
          <div className="results">{results}</div>
        </section>
      </div>
      <Categorise target={target} genres={P.genres || []} onClose={() => setTarget(null)} onSaved={onSaved} />
      {loading && <span className="sr-only">refreshing</span>}
      <button type="button" hidden onClick={() => nav("/problems")} />
    </>
  );
}
