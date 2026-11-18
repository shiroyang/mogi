// One problem: statement, required API, hints, editor, verdicts. Split view on desktop;
// Statement / Code / Result segments with a bottom action bar on phones.
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router";
import { api, AuthError, problemHref, vscodeHref, type MetaResult, type ProblemDetail, type Rating, type Verdict } from "../api";
import { Categorise, type MetaTarget } from "../components/Categorise";
import { Debrief } from "../components/Debrief";
import { CodeView, Editor, type EditorHandle } from "../components/Editor";
import { Hints } from "../components/Hints";
import { MockClock } from "../components/MockClock";
import { readSolveSeconds, resetSolveSeconds, SolveClock } from "../components/SolveClock";
import { Difficulty, Importance, Markdown, Minutes, Segmented, Spinner, Stars, toast, TopBar } from "../components/ui";
import { VerdictView } from "../components/Verdict";
import { rememberLast, useAsync, useIsMobile } from "../hooks";
import { dateText, dayText, redoReason, redoText, splitStatement } from "../model";
import { Login } from "./Login";

type LeftTab = "statement" | "api" | "hints" | "debrief" | "analysis" | "reference" | "tests";
type MobileTab = "statement" | "code" | "result";
const SPOILER_TABS: LeftTab[] = ["debrief", "analysis", "reference", "tests"];
const IS_MAC = typeof navigator !== "undefined" && /Mac|iPhone|iPad/.test(navigator.platform);
const fmtDate = (s: number) => new Date(s * 1000).toISOString().slice(0, 16).replace("T", " ");

/** What the editor starts with: your draft, or the starter stub.
 * On a redo day it starts from the stub once, whatever was typed before, and the clock starts over. */
function editorSeed(P: ProblemDetail, draftKey: string): string {
  const stub = P.stub || "";
  try {
    if (P.redo_due && P.redo_at) {
      const mark = `mogi-redo-${P.pid}`;
      if (localStorage.getItem(mark) !== String(P.redo_at)) {
        localStorage.setItem(mark, String(P.redo_at));
        localStorage.setItem(draftKey, stub);
        resetSolveSeconds(P.pid);
        return stub;
      }
    }
    const draft = localStorage.getItem(draftKey) ?? "";
    return draft.trim() ? draft : stub;
  } catch {
    return stub;
  }
}

export function Problem() {
  const { corpus = "", id = "" } = useParams();
  const pid = `${corpus}/${id}`;
  const mobile = useIsMobile();
  const nav = useNavigate();
  const { data, error, loading, setData } = useAsync(() => api.problem(pid), [pid]);
  // While the next problem loads, `data` still holds the previous one.
  // Showing it would leave the old code in the editor, so treat it as not loaded yet.
  const P = data && data.pid === pid ? data : undefined;
  const editor = useRef<EditorHandle>(null);
  const [left, setLeft] = useState<LeftTab>("statement");
  const [mtab, setMtab] = useState<MobileTab>("statement");
  const [busy, setBusy] = useState<"run" | "submit" | null>(null);
  const [helpBusy, setHelpBusy] = useState<string | null>(null);
  const [verdict, setVerdict] = useState<{ res: Verdict; mode: string } | null>(null);
  const [target, setTarget] = useState<MetaTarget | null>(null);
  const [split, setSplit] = useState<number>(() => +(localStorage.getItem("mogi-split-px") || 0));
  const draftKey = `mogi-draft-${pid}`;
  const loaded = !!P;
  // eslint-disable-next-line react-hooks/exhaustive-deps
  const initial = useMemo(() => (P ? editorSeed(P, draftKey) : ""), [pid, loaded]);

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
      // the clock only runs on a first solve or a redo, so only those send a time
      const timed = mode === "submit" && (!P.solved || P.redo_due);
      const res = await api.judge(pid, code, mode, timed ? readSolveSeconds(pid) : undefined);
      setVerdict({ res, mode });
      if (mode === "submit") {
        if (res.verdict === "AC") {
          if (timed) resetSolveSeconds(pid);
          if (P.redo_due) toast("Accepted from a blank editor. The redo is done.");
          else if (P.redo_at) toast(`Accepted. It still comes back ${dayText(P.redo_at)} for a redo from a blank editor.`, 5200);
        }
        const next = await api.problem(pid);  // submissions list, status, spoilers, the debrief
        setData(() => next);
        if (res.verdict === "AC" && P.pet && next.pet) {   // the companion may have hatched or grown with this solve
          if (!P.pet.hatched && next.pet.hatched) toast(`${next.pet.name} hatched.`, 7000);
          else if (next.pet.stage > P.pet.stage) toast(`${next.pet.name} grew.`, 7000);
        }
        if (res.verdict === "AC" && P.mock) {
          // In a mock the debrief waits: go on to the next problem, or to the result when that was the last one.
          if (!next.mock) { toast("Accepted. The mock is done."); nav(`/mock/${P.mock.id}`); }
          else if (next.mock.next) toast(`Accepted. ${next.mock.next.id} is next.`, 5200);
        } else if (res.verdict === "AC" && next.solved && next.unlocked && !mobile) setLeft("debrief");
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
  async function openHint(key: string) {
    if (helpBusy) return;
    setHelpBusy(key);
    try { const next = await api.hint(pid, key); setData(() => next); }
    catch (e) { toast((e as Error).message); }
    finally { setHelpBusy(null); }
  }
  async function saveDebrief(patch: { rating?: Rating; note?: string }) {
    const next = await api.debrief(pid, patch);
    setData(() => next);
  }
  async function gradeCard(key: string, known: boolean) {
    const g = await api.grade(pid, key, known);
    setData(d => ({ ...d, cards: (d.cards || []).map(c => (c.key === key ? { ...c, reps: g.reps, ivl: g.ivl, due: g.due } : c)) }));
    return g;
  }
  const openReference = () => {
    if (!mobile) { setLeft("reference"); return; }
    setMtab("statement");   // on a phone the reference sits under the statement
    setTimeout(() => {
      const el = document.getElementById("mogi-reference");
      el?.setAttribute("open", "");
      el?.scrollIntoView({ block: "start", behavior: "smooth" });
    }, 60);
  };
  // The mock's clock reached zero: give the server a moment to close it, then show the result.
  const mockId = P?.mock?.id;
  const onMockOver = useCallback(() => {
    if (!mockId) return;
    setTimeout(() => { toast("Time is up."); nav(`/mock/${mockId}`); }, 1200);
  }, [mockId, nav]);
  async function openSolution() {
    if (helpBusy) return;
    setHelpBusy("solution");
    try {
      const next = await api.solution(pid);
      setData(() => next);
      if (next.redo_at) toast(`The solution is open. ${next.id} comes back on ${dateText(next.redo_at)}.`, 5200);
      if (!mobile && next.unlocked) setLeft("analysis");
    } catch (e) { toast((e as Error).message); }
    finally { setHelpBusy(null); }
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

  // redo_due comes from the server, which decides when the day has come
  const redoChip = P.redo_at && (
    <span className={`chip redo${P.redo_due ? " due" : ""}`} title="You read the solution. It comes back so you can write it again from a blank editor.">
      {P.redo_due ? "redo due" : redoText(P.redo_at)}
    </span>
  );
  const statusChip = (
    <>
      {P.solved ? <span className="chip ok">solved</span> : P.status === "attempted" ? <span className="chip">attempted</span> : null}
      {redoChip}
    </>
  );
  // In a mock the top bar shows the countdown and the way to the mock's other problem,
  // and nothing that says what kind of problem this is.
  const M = P.mock;
  const mockChips = M && (
    <>
      <Link className="chip mock" to="/mock" title="The mock that is running">
        mock{M.total > 1 ? ` ${M.index + 1} of ${M.total}` : ""} <MockClock endsAt={M.ends_at} onDone={onMockOver} />
      </Link>
      {M.next && <Link className="chip" to={problemHref(M.next.pid)} title={M.next.title}>next: {M.next.id} →</Link>}
    </>
  );
  const nextLink = !M && P.next && (
    <Link className="chip" to={problemHref(P.next.pid)} title={P.next.title}>next{P.next.same_genre ? " in genre" : ""}: {P.next.id} →</Link>
  );
  const pr = P.practice || ({} as ProblemDetail["practice"]);
  const stmt = splitStatement(P.statement || "");
  const tab: LeftTab = SPOILER_TABS.includes(left) && !P.unlocked ? "statement" : left;
  const paidHints = (P.ladder || []).filter(r => !r.free).length;
  const statementBlock = (
    <>
      {P.redo_due && (
        <p className="notice redo">
          <b>Redo day.</b> {redoReason(P.redo_why)}. Write it again from a blank editor. The editor is back to the starter stub.
        </p>
      )}
      <Markdown source={stmt.body} />
      {stmt.details && !M && (
        <details className="spoiler"><summary>Details from the corpus (source, round, confidence, tier)</summary><Markdown source={stmt.details} className="facts" /></details>
      )}
    </>
  );
  const meta = M ? (
    <div className="pmeta-head">
      <h1 className="ptitle-h">{P.title}</h1>
      <p className="faint" style={{ margin: 0, fontSize: 13.5 }}>Mock round. Its genre, difficulty and sources come back when the mock ends.</p>
    </div>
  ) : (
    <div className="pmeta-head">
      <h1 className="ptitle-h">{P.title}</h1>
      <div className="row wrap">
        <button type="button" className="chip genre" title={`genre${P.genre_corpus && P.genre_corpus !== P.genre ? ` (corpus: ${P.genre_corpus})` : ""} — tap to change`}
          onClick={() => setTarget({ pid, id: P.id, genre: P.genre, genre_corpus: P.genre_corpus, priority: P.priority, tags: P.tags })}>{P.genre || "—"}</button>
        <Difficulty value={P.difficulty} src={P.difficulty_src} />
        <Minutes value={P.minutes} loc={P.loc} />
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
  const hints = <Hints P={P} busy={helpBusy} onHint={k => void openHint(k)} onSolution={() => void openSolution()} />;
  const spoilers = P.unlocked && (
    <>
      {P.analysis && <details className="spoiler"><summary>🔓 Analysis</summary><Markdown source={P.analysis} /></details>}
      {P.reference && <details className="spoiler" id="mogi-reference"><summary>🔓 Reference solution</summary><CodeView code={P.reference} /></details>}
      {P.tests && <details className="spoiler"><summary>🔓 Tests</summary><CodeView code={P.tests} /></details>}
    </>
  );
  // The debrief belongs to a solve. It closes with the other spoilers on a redo day.
  const debrief = P.solved && P.unlocked && !M && (
    <Debrief P={P} onDebrief={saveDebrief} onGrade={gradeCard} onOpenReference={openReference} />
  );
  const clock = <SolveClock pid={pid} running={!P.solved || P.redo_due} />;
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
  const vscodeBtn = !mobile && !M && <a className="btn sm" href={vscodeHref(pid)} title="Open in VS Code (needs the mogi extension)">Open in VS Code</a>;
  // Keyed by problem: a new problem gets a new editor, seeded with its own draft or stub.
  const editorEl = <Editor key={pid} ref={editor} initial={initial} onChange={onDraft} onRun={() => void judge("run")} onSubmit={() => void judge("submit")} />;

  if (mobile) {
    return (
      <>
        <TopBar crumbs={[{ label: "problems", to: "/problems" }]} title={P.id}
          right={<div className="row" style={{ gap: 10 }}>{M ? mockChips : <>{clock}{redoChip || statusChip}</>}</div>} />
        <div className="pwrap mobile">
          <div className="segwrap">
            <Segmented options={[{ key: "statement", label: "Statement" }, { key: "code", label: "Code" }, { key: "result", label: busy ? "Judging…" : "Result" }]}
              value={mtab} onChange={setMtab} />
          </div>
          <div className="mbody" hidden={mtab !== "statement"}>
            {meta}
            {statementBlock}
            <h2 className="h2">Hints</h2>
            {hints}
            <h2 className="h2">Required API</h2>
            {apiTab}
            {spoilers}
          </div>
          <div className="mcode" hidden={mtab !== "code"}>{editorEl}</div>
          <div className="mbody" hidden={mtab !== "result"}>
            {results}
            {debrief && <><h2 className="h2">Debrief</h2>{debrief}</>}
          </div>
          <div className="actionbar">
            <button type="button" className="btn" disabled={!!busy} onClick={() => void judge("run")}>▶ Run tests</button>
            <button type="button" className="btn primary" disabled={!!busy} onClick={() => void judge("submit")}>Submit</button>
          </div>
        </div>
        <Categorise target={target} genres={P.genres || []} onClose={() => setTarget(null)} onSaved={onSaved} />
      </>
    );
  }

  const tabs: [LeftTab, string][] = [
    ["statement", "Statement"], ["api", "Required API"],
    ["hints", P.hints ? `Hints ${P.hints}/${paidHints}` : "Hints"],
    ...(debrief ? [["debrief", "Debrief"]] as [LeftTab, string][] : []),
    ...(P.unlocked ? [["analysis", "Analysis 🔓"], ["reference", "Reference 🔓"], ["tests", "Tests 🔓"]] as [LeftTab, string][] : []),
  ];
  return (
    <>
      <TopBar crumbs={[{ label: "problems", to: "/problems" }]} title={`${P.id} — ${P.title}`}
        right={<div className="row" style={{ gap: 10 }}>{statusChip}{mockChips}{nextLink}{vscodeBtn}</div>} />
      <div className="pwrap desktop" style={split ? { gridTemplateColumns: `${split}px 6px 1fr` } : undefined}>
        <section className="pane">
          <nav className="tabs" role="tablist">
            {tabs.map(([k, label]) => <button key={k} role="tab" aria-selected={tab === k} className={tab === k ? "on" : ""} onClick={() => setLeft(k)}>{label}</button>)}
          </nav>
          <div className="pane-body">
            {tab === "statement" && <>{meta}{statementBlock}</>}
            {tab === "api" && apiTab}
            {tab === "hints" && hints}
            {tab === "debrief" && debrief}
            {tab === "analysis" && <Markdown source={P.analysis || ""} />}
            {tab === "reference" && <CodeView code={P.reference || ""} />}
            {tab === "tests" && <CodeView code={P.tests || ""} />}
          </div>
        </section>
        <div className="gutter" onPointerDown={onGutter} onDoubleClick={() => { setSplit(0); localStorage.removeItem("mogi-split-px"); }} title="drag to resize · double-click to reset" />
        <section className="pane">
          <div className="editor-wrap">{editorEl}</div>
          <div className="toolbar">
            <button type="button" className="btn" disabled={!!busy} onClick={() => void judge("run")}>▶ Run tests<kbd>{IS_MAC ? "⌘↩" : "Ctrl+↩"}</kbd></button>
            <button type="button" className="btn primary" disabled={!!busy} onClick={() => void judge("submit")}>Submit<kbd>{IS_MAC ? "⇧⌘↩" : "Ctrl+Shift+↩"}</kbd></button>
            <span className="spacer" />
            {clock}
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
