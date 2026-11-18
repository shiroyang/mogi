// The review sitting: the question cards that are due, one at a time. Built for a phone.
import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router";
import { api, AuthError, problemHref, type Grade } from "../api";
import { QuestionCard } from "../components/Cards";
import { Markdown, Spinner, toast, TopBar } from "../components/ui";
import { useAsync } from "../hooks";
import { comesBack, plural, splitStatement } from "../model";
import { Login } from "./Login";

export function Review() {
  const { data, error, loading, reload } = useAsync(() => api.review(), []);
  const [index, setIndex] = useState(0);
  const [known, setKnown] = useState(0);
  const [busy, setBusy] = useState(false);
  const [last, setLast] = useState<Grade | null>(null);
  const [statements, setStatements] = useState<Record<string, string>>({});
  useEffect(() => { setIndex(0); setKnown(0); setLast(null); }, [data]);   // a new sitting starts from its first card
  useEffect(() => { document.title = "mogi — review"; }, []);

  const cards = data?.cards || [];
  const card = cards[index];
  const grade = useCallback(async (isKnown: boolean) => {
    if (!card || busy) return;
    setBusy(true);
    try {
      setLast(await api.grade(card.pid, card.key, isKnown));
      if (isKnown) setKnown(n => n + 1);
      setIndex(i => i + 1);
    } catch (e) { toast((e as Error).message); } finally { setBusy(false); }
  }, [card, busy]);
  const loadStatement = (pid: string) => {
    if (statements[pid] !== undefined) return;
    setStatements(s => ({ ...s, [pid]: "" }));
    api.problem(pid).then(p => setStatements(s => ({ ...s, [pid]: splitStatement(p.statement || "").body })))
      .catch(e => toast((e as Error).message));
  };

  if (error instanceof AuthError) return <Login />;
  const missed = cards.length - known;
  const more = data ? data.due - cards.length : 0;
  return (
    <>
      <TopBar title="Review" right={card && <span className="faint" style={{ fontSize: 13.5 }}>{index + 1} of {cards.length}</span>} />
      <main className="page review">
        {loading && !data && <Spinner label="Loading…" />}
        {error && !data && <p style={{ color: "var(--bad)" }}>{error.message}</p>}

        {data && !cards.length && (
          <section className="review-done">
            <h1>Nothing is due.</h1>
            <p className="muted">Questions show up here a few days after you solve a problem.</p>
            <Link className="btn primary" to="/">Back to home</Link>
          </section>
        )}

        {card && (
          <article className="review-card">
            <Link className="review-problem" to={problemHref(card.pid)} title="Open the problem"><span className="id">{card.id}</span>{card.title}</Link>
            <details className="spoiler statement" onToggle={e => { if ((e.target as HTMLDetailsElement).open) loadStatement(card.pid); }}>
              <summary>Read the statement</summary>
              {statements[card.pid] ? <Markdown source={statements[card.pid]} /> : <Spinner label="Loading…" />}
            </details>
            {last && <p className="rung-lead after">{last.known ? "Knew it." : "Not yet."} {comesBack(last.ivl)}</p>}
            <QuestionCard key={`${card.pid}#${card.key}`} card={card} shortcuts busy={busy} onGrade={k => void grade(k)} />
          </article>
        )}

        {data && cards.length > 0 && !card && (
          <section className="review-done">
            <h1>Done. {known} of {cards.length} known.</h1>
            <p className="muted">
              {missed ? `${missed === 1 ? "The one you missed comes" : `The ${missed} you missed come`} back tomorrow.` : "Nothing missed."}
              {more > 0 && ` ${plural(more, "more is", "more are")} due.`}
            </p>
            <div className="row wrap">
              {more > 0 && <button type="button" className="btn primary" onClick={reload}>Keep going</button>}
              <Link className={`btn${more > 0 ? "" : " primary"}`} to="/">Back to home</Link>
            </div>
          </section>
        )}
      </main>
    </>
  );
}
