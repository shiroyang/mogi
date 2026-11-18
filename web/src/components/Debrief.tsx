// The debrief: what you do after an accepted solve, in the order an interview would.
// How it went, your code next to the reference, the follow-up questions, a note for next time.
import { useEffect, useState } from "react";
import { Link } from "react-router";
import { problemHref, type Grade, type ProblemDetail, type Rating } from "../api";
import { comesBack, dateText, dayText, debriefCards, debriefFacts, debriefHeadline, petLook, plural, RATINGS, xpLine } from "../model";
import { QuestionCard } from "./Cards";
import { Porthole } from "./Creature";
import { toast } from "./ui";

interface Props {
  P: ProblemDetail;
  onDebrief: (patch: { rating?: Rating; note?: string }) => Promise<void>;
  onGrade: (key: string, known: boolean) => Promise<Grade>;
  onOpenReference: () => void;
}

/** What the chosen rating leads to, in one sentence. */
function ratingOutcome(P: ProblemDetail): string {
  if (!P.rating) return "";
  if (P.assisted && P.redo_at) return `It already comes back ${dayText(P.redo_at)}, because you read the solution.`;
  if (P.redo_at) return `It comes back ${dayText(P.redo_at)}, on ${dateText(P.redo_at)}, for a redo from a blank editor.`;
  return "No redo. The questions below keep it fresh.";
}

export function Debrief({ P, onDebrief, onGrade, onOpenReference }: Props) {
  const [busy, setBusy] = useState<string | null>(null);
  const [note, setNote] = useState(P.note || "");
  const [last, setLast] = useState<Grade | null>(null);
  useEffect(() => { setNote(P.note || ""); setLast(null); }, [P.pid]); // eslint-disable-line react-hooks/exhaustive-deps

  const cards = debriefCards(P.cards);
  const todo = cards.filter(c => !c.reps);
  const current = todo[0];
  const answered = cards.length - todo.length;
  const noteChanged = note.trim() !== (P.note || "");

  async function rate(rating: Rating) {
    if (busy) return;
    setBusy(rating);
    try { await onDebrief({ rating }); } catch (e) { toast((e as Error).message); } finally { setBusy(null); }
  }
  async function saveNote() {
    if (busy) return;
    setBusy("note");
    try { await onDebrief({ note }); toast(note.trim() ? "Note saved" : "Note removed"); }
    catch (e) { toast((e as Error).message); } finally { setBusy(null); }
  }
  async function grade(known: boolean) {
    if (busy || !current) return;
    setBusy("card");
    try { setLast(await onGrade(current.key, known)); } catch (e) { toast((e as Error).message); } finally { setBusy(null); }
  }

  return (
    <div className="debrief">
      <h2 className="debrief-head">{debriefHeadline(P)}</h2>
      <p className="hints-intro">{debriefFacts(P)}</p>
      {P.pet && P.xp && (
        <Link className="debrief-pet" to="/companion">
          <Porthole look={petLook(P.pet)} size={46} label={P.pet.name} />
          <span>{xpLine(P.pet.name, P.xp, P.genre)}</span>
        </Link>
      )}
      <ol className="ladder">
        <li className={`rung${P.rating ? " open" : ""}`}>
          <div className="rung-head"><h3>How did it go?</h3></div>
          <div className="row wrap choices">
            {RATINGS.map(r => (
              <button key={r.key} type="button" className={`btn sm${P.rating === r.key ? " on" : ""}`} aria-pressed={P.rating === r.key}
                disabled={!!busy} onClick={() => void rate(r.key)}>{r.label}</button>
            ))}
          </div>
          {P.rating && <p className="rung-lead after">{ratingOutcome(P)}</p>}
        </li>

        <li className="rung">
          <div className="rung-head"><h3>Compare with the reference</h3></div>
          <p className="rung-lead">Your code is in the editor. Open the reference next to it and look for what you would write differently.</p>
          <button type="button" className="btn sm" onClick={onOpenReference}>Open the reference</button>
        </li>

        {cards.length > 0 && (
          <li className={`rung${!current ? " open" : ""}`}>
            <div className="rung-head">
              <h3>What the interviewer asks next</h3>
              <span className="rung-n">{answered} of {cards.length} answered</span>
            </div>
            {last && <p className="rung-lead after">{last.known ? "Knew it." : "Not yet."} {comesBack(last.ivl)}</p>}
            {current
              ? <QuestionCard key={current.key} card={current} busy={busy === "card"} onGrade={known => void grade(known)} />
              : <p className="rung-lead">All {plural(cards.length, "question", "questions")} answered. They come back on the home page when they are due.</p>}
          </li>
        )}

        <li className={`rung last${P.note ? " open" : ""}`}>
          <div className="rung-head"><h3>A note for next time</h3></div>
          <textarea className="field note" rows={3} value={note} onChange={e => setNote(e.target.value)} maxLength={1000}
            placeholder="One thing to remember. A trap, a trick, a name." aria-label="note for next time" />
          <div className="row wrap">
            <button type="button" className="btn sm" disabled={!noteChanged || !!busy} onClick={() => void saveNote()}>
              {busy === "note" ? "Saving…" : "Save the note"}
            </button>
          </div>
        </li>
      </ol>
      {P.next && (
        <Link className="btn primary debrief-next" to={problemHref(P.next.pid)} title={P.next.title}>
          Next{P.next.same_genre ? " in this genre" : ""}: {P.next.id}
        </Link>
      )}
    </div>
  );
}
