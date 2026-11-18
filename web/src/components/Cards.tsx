// One question card: the question, your answer out loud, then the written answer and a grade.
// The debrief and the review page both use it.
import { useEffect, useState } from "react";
import type { Card } from "../api";
import { cardLabel, cardQuestion } from "../model";
import { Markdown } from "./ui";

interface Props {
  card: Card;
  onGrade: (known: boolean) => void;
  busy?: boolean;
  /** Space or Enter shows the answer, 1 is "not yet", 2 is "knew it". Only where no editor is on the page. */
  shortcuts?: boolean;
}

export function QuestionCard({ card, onGrade, busy, shortcuts }: Props) {
  const [open, setOpen] = useState(false);
  useEffect(() => {
    if (!shortcuts) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.metaKey || e.ctrlKey || e.altKey || (e.target as HTMLElement | null)?.closest("input, textarea, select")) return;
      if (!open && (e.key === " " || e.key === "Enter")) { e.preventDefault(); setOpen(true); }
      else if (open && !busy && e.key === "1") onGrade(false);
      else if (open && !busy && e.key === "2") onGrade(true);
    };
    addEventListener("keydown", onKey);
    return () => removeEventListener("keydown", onKey);
  }, [shortcuts, open, busy, onGrade]);

  return (
    <div className="qcard">
      <div className="qcard-kind">{cardLabel(card.kind)}</div>
      <Markdown source={cardQuestion(card)} className="qcard-q" />
      {!open ? (
        <div className="row wrap">
          <button type="button" className="btn sm" onClick={() => setOpen(true)}>Show the answer{shortcuts && <kbd>space</kbd>}</button>
          <span className="faint rung-note">Say yours out loud first.</span>
        </div>
      ) : (
        <>
          <Markdown source={card.a} className="rung-body" />
          <div className="row wrap qcard-grade">
            <button type="button" className="btn sm" disabled={busy} onClick={() => onGrade(false)}>Not yet{shortcuts && <kbd>1</kbd>}</button>
            <button type="button" className="btn sm primary" disabled={busy} onClick={() => onGrade(true)}>Knew it{shortcuts && <kbd>2</kbd>}</button>
          </div>
        </>
      )}
    </div>
  );
}
