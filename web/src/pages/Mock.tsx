// Mock rounds: pick one and start it, watch the clock while it runs, read the result when it ends.
import { useEffect, useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router";
import { api, AuthError, problemHref, type Mock as MockRound, type MockHome } from "../api";
import { MockClock } from "../components/MockClock";
import { Sheet } from "../components/Sheet";
import { Segmented, Spinner, toast, TopBar } from "../components/ui";
import { useAsync, useLocalStorage } from "../hooks";
import { dateText, MOCK_FORMATS, mockHeadline, mockHistoryLine, mockName, mockProblemLine, plural, sizeSentence } from "../model";
import { Login } from "./Login";

/** Choose a round and start it. */
function Setup({ home, onStarted }: { home: MockHome; onStarted: (m: MockRound) => void }) {
  const corpora = Object.keys(home.pools);
  const [saved, setSaved] = useLocalStorage<{ corpus: string; format: string }>("mogi-mock", { corpus: corpora[0] || "", format: "coding" });
  const corpus = corpora.includes(saved.corpus) ? saved.corpus : corpora[0] || "";
  const format = home.formats[saved.format] ? saved.format : "coding";
  const spec = home.formats[format];
  const [minutes, setMinutes] = useState(spec?.minutes || 45);
  const [busy, setBusy] = useState(false);
  useEffect(() => { setMinutes(spec?.minutes || 45); }, [format]); // eslint-disable-line react-hooks/exhaustive-deps
  const pool = (key: string) => home.pools[corpus]?.[key] || 0;
  const enough = !!spec && pool(format) >= spec.count;

  async function start() {
    if (busy || !enough) return;
    setBusy(true);
    try { onStarted(await api.mockStart(corpus, format, minutes)); }
    catch (e) { toast((e as Error).message); setBusy(false); }
  }
  return (
    <>
      <h1 className="mock-h">A mock round.</h1>
      <p className="mock-sub">Problems you have not solved, on a clock, with no hints. You can still ask the interviewer.</p>
      {corpora.length > 1 && (
        <div className="mock-corpus"><Segmented id="mock-corpus" options={corpora.map(c => ({ key: c, label: c }))} value={corpus}
          onChange={c => setSaved(s => ({ ...s, corpus: c }))} /></div>
      )}
      <div className="formats" role="radiogroup" aria-label="round">
        {MOCK_FORMATS.filter(f => home.formats[f.key]).map(f => {
          const short = pool(f.key) < home.formats[f.key].count;
          return (
            <button key={f.key} type="button" role="radio" aria-checked={format === f.key} disabled={short}
              className={`format${format === f.key ? " on" : ""}`} onClick={() => setSaved(s => ({ ...s, format: f.key }))}>
              <span className="format-name">{f.label}</span>
              <span className="format-what">{f.what} {home.formats[f.key].minutes} minutes.</span>
              <span className="format-pool">{short ? "not enough left" : `${pool(f.key)} to draw from`}</span>
            </button>
          );
        })}
      </div>
      {spec && (
        <div className="mock-length">
          <span className="muted">Length</span>
          <Segmented id="mock-length" options={spec.choices.map(c => ({ key: String(c), label: `${c} min` }))} value={String(minutes)}
            onChange={c => setMinutes(+c)} />
        </div>
      )}
      <button type="button" className="btn primary mock-go" disabled={busy || !enough} onClick={() => void start()}>
        {busy ? "Drawing…" : "Start the mock"}
      </button>
      {home.history.length > 0 && (
        <section className="mock-history">
          <h2 className="h2">Earlier mocks</h2>
          <ul>
            {home.history.map(m => (
              <li key={m.id}><Link to={`/mock/${m.id}`}>
                <span className="when">{dateText(m.started_at)}</span>
                <span className="what">{mockName(m)}</span>
                <span className="how">{mockHistoryLine(m)}</span>
              </Link></li>
            ))}
          </ul>
        </section>
      )}
    </>
  );
}

/** The round that is running: the clock, its problems, and a way out. */
function Running({ mock, onTimeUp, onEnded }: { mock: MockRound; onTimeUp: () => void; onEnded: (m: MockRound) => void }) {
  const [asking, setAsking] = useState(false);
  const [busy, setBusy] = useState(false);
  async function end() {
    setBusy(true);
    try { onEnded(await api.mockEnd()); } catch (e) { toast((e as Error).message); setBusy(false); setAsking(false); }
  }
  return (
    <>
      <div className="mock-clock"><MockClock endsAt={mock.ends_at} onDone={onTimeUp} /></div>
      <p className="mock-sub">left of {mock.minutes} minutes. {mockName(mock)}, {mock.solved} of {mock.total} solved.</p>
      <ol className="mock-problems">
        {mock.problems.map((p, i) => (
          <li key={p.pid}>
            <Link to={problemHref(p.pid)}>
              <span className="n">{i + 1}</span>
              <span className="t"><span className="id">{p.id}</span>{p.title}</span>
              <span className={`s${p.ac_s !== null ? " ok" : ""}`}>{p.ac_s !== null ? "accepted" : "open it"}</span>
            </Link>
          </li>
        ))}
      </ol>
      <button type="button" className="btn" onClick={() => setAsking(true)}>End the mock</button>
      <Sheet open={asking} onClose={() => setAsking(false)} title="End the mock now?">
        <p className="muted" style={{ margin: "0 0 18px", lineHeight: 1.5 }}>The clock stops and you get the result. What you solved so far counts.</p>
        <div className="row">
          <button type="button" className="btn primary" disabled={busy} onClick={() => void end()}>End the mock</button>
          <button type="button" className="btn" onClick={() => setAsking(false)}>Keep going</button>
        </div>
      </Sheet>
    </>
  );
}

/** How a finished round went. Now it says what kind of problem each one was. */
function Result({ mock }: { mock: MockRound }) {
  return (
    <>
      <h1 className="mock-h">{mockHeadline(mock)}</h1>
      <p className="mock-sub">{mockName(mock)}, {plural(mock.minutes, "minute", "minutes")}. {dateText(mock.started_at)}.</p>
      <ol className="mock-results">
        {mock.problems.map(p => (
          <li key={p.pid}>
            <h2><span className="id">{p.id}</span>{p.title}</h2>
            <p className={p.ac_s !== null ? "ok" : ""}>{mockProblemLine(p)}</p>
            {p.genre && <p className="faint">{sizeSentence({ difficulty: p.difficulty || "", genre: p.genre, minutes: p.minutes || 0 })}</p>}
            <Link className="btn sm" to={problemHref(p.pid)}>{p.ac_s !== null ? "Open the debrief" : "Open the problem"}</Link>
          </li>
        ))}
      </ol>
      <div className="row wrap">
        <Link className="btn primary" to="/mock">Start another mock</Link>
        <Link className="btn" to="/">Back to home</Link>
      </div>
    </>
  );
}

export function Mock() {
  const { id } = useParams();
  const nav = useNavigate();
  const { data, error, loading, reload, setData } = useAsync<{ home?: MockHome; one?: MockRound }>(
    () => (id ? api.mockOne(id).then(one => ({ one })) : api.mock().then(home => ({ home }))), [id]);
  const running = useRef<string | null>(null);
  useEffect(() => { document.title = "mogi — mock"; }, []);
  // A round that was running and no longer is has ended: show its result.
  useEffect(() => {
    if (!data?.home) return;
    if (data.home.active) running.current = data.home.active.id;
    else if (running.current) { const done = running.current; running.current = null; nav(`/mock/${done}`); }
  }, [data, nav]);
  // Coming back to this tab: the round may have moved on elsewhere.
  useEffect(() => {
    const onShow = () => { if (document.visibilityState === "visible" && running.current) reload(); };
    document.addEventListener("visibilitychange", onShow);
    return () => document.removeEventListener("visibilitychange", onShow);
  }, [reload]);

  if (error instanceof AuthError) return <Login />;
  const active = data?.home?.active;
  return (
    <>
      <TopBar title="Mock" />
      <main className="page mock">
        {loading && !data && <Spinner label="Loading…" />}
        {error && !data && <p style={{ color: "var(--bad)" }}>{error.message}</p>}
        {data?.one && (data.one.active ? <p className="muted">This mock is still running. <Link to="/mock">Go to it</Link></p> : <Result mock={data.one} />)}
        {data?.home && active && (
          <Running mock={active} onTimeUp={() => setTimeout(reload, 1200)}
            onEnded={m => { running.current = null; nav(`/mock/${m.id}`); }} />
        )}
        {data?.home && !active && (
          <Setup home={data.home} onStarted={m => { setData(d => ({ ...d, home: d.home && { ...d.home, active: m } })); nav(problemHref(m.problems[0].pid)); }} />
        )}
      </main>
    </>
  );
}
