// The hint ladder: ask the interviewer (free), then the hints in order, then the solution.
// Each closed step shows what to think about first. Opening one is saved on the server.
import { useState } from "react";
import type { ProblemDetail } from "../api";
import { dateText, dayText, ladderSteps, plural } from "../model";
import { Sheet } from "./Sheet";
import { Markdown, Spinner } from "./ui";

interface Props {
  P: ProblemDetail;
  /** The step being opened right now: a hint key, or "solution". */
  busy: string | null;
  onHint: (key: string) => void;
  onSolution: () => void;
}

export function Hints({ P, busy, onHint, onSolution }: Props) {
  const [asking, setAsking] = useState(false);
  // During a mock only the free step is offered: you may still ask the interviewer.
  const steps = ladderSteps(P.ladder || []).filter(r => !P.mock || r.free);
  const days = P.redo_days || 3;
  const comesBack = `in ${plural(days, "day", "days")}`;
  const confirm = () => { setAsking(false); onSolution(); };

  return (
    <div className="hints">
      <p className="hints-intro">
        {P.mock ? "This is a mock: hints and the solution are off until it ends. You can still ask the interviewer."
                : "Stuck? Take one step at a time. Hints are counted, asking the interviewer is not."}
      </p>
      <ol className="ladder">
        {steps.map(r => (
          <li key={r.key} className={`rung${r.open ? " open" : ""}`}>
            <div className="rung-head">
              <h3>{r.copy?.title || r.title}</h3>
              <span className="rung-n">{r.free ? "free" : `hint ${r.step} of ${r.total}`}</span>
            </div>
            {r.copy?.lead && <p className="rung-lead">{r.copy.lead}</p>}
            {r.open ? <Markdown source={r.body || ""} className="rung-body" />
              : busy === r.key ? <Spinner label="Opening…" />
              : (
                <div className="row wrap">
                  <button type="button" className="btn sm" disabled={!r.canOpen || !!busy} onClick={() => onHint(r.key)}>
                    {r.free ? "Show the questions" : `Show hint ${r.step}`}
                  </button>
                  {!r.canOpen && <span className="faint rung-note">Open hint {r.step - 1} first.</span>}
                </div>
              )}
          </li>
        ))}

        {!P.mock && <li className={`rung last${P.unlocked ? " open" : ""}`}>
          <div className="rung-head"><h3>The solution</h3></div>
          {P.redo_due ? (
            <>
              <p className="rung-lead">Redo day. The solution is closed again, so you can write it from a blank editor.</p>
              <div className="row wrap">
                <button type="button" className="btn sm" disabled={!!busy} onClick={() => setAsking(true)}>Peek at the solution</button>
                <span className="faint rung-note">Peeking starts the {plural(days, "day", "days")} over.</span>
              </div>
            </>
          ) : P.unlocked && P.redo_at ? (
            <p className="rung-lead">
              Open in the Analysis, Reference and Tests tabs. {P.id} comes back {dayText(P.redo_at)} ({dateText(P.redo_at)}),
              so you can write it again from a blank editor.
            </p>
          ) : P.unlocked ? (
            <p className="rung-lead">Solved. The analysis, the reference solution and the tests are open.</p>
          ) : busy === "solution" ? <Spinner label="Opening…" /> : (
            <>
              <p className="rung-lead">
                Opens the analysis, the reference solution and the tests. {P.id} is marked as assisted and comes back {comesBack},
                so you can write it again from a blank editor.
              </p>
              <button type="button" className="btn sm" disabled={!!busy} onClick={() => setAsking(true)}>Show the solution</button>
            </>
          )}
        </li>}
      </ol>

      <Sheet open={asking} onClose={() => setAsking(false)} title={P.redo_due ? "Peek at the solution?" : "Show the solution?"}>
        <p className="muted" style={{ margin: "0 0 18px", lineHeight: 1.5 }}>
          {P.redo_due
            ? `The redo starts over. ${P.id} comes back ${comesBack} from now.`
            : `${P.id} will be marked as assisted. It comes back ${comesBack}, so you can write it again from a blank editor.`}
        </p>
        <div className="row">
          <button type="button" className="btn primary" onClick={confirm}>{P.redo_due ? "Peek at the solution" : "Show the solution"}</button>
          <button type="button" className="btn" onClick={() => setAsking(false)}>{P.redo_due ? "Keep going" : "Keep trying"}</button>
        </div>
      </Sheet>
    </div>
  );
}
