// The companion's page: pick an egg, then watch how it is doing and where its XP came from.
import { useEffect, useState } from "react";
import { Link } from "react-router";
import { api, AuthError, problemHref, type CompanionPage, type Pet } from "../api";
import { Porthole } from "../components/Creature";
import { Sheet } from "../components/Sheet";
import { Segmented, Spinner, toast, TopBar } from "../components/ui";
import { useAsync } from "../hooks";
import { dateText, EGG_KIND, paidNote, petLook, petMoodLine, petProgress, petStatus, PLAN_COPY, plural } from "../model";
import { Login } from "./Login";

type Patch = { egg?: string; plan?: string; name?: string };

/** No egg yet: the three to choose from. */
function Choose({ page, onSet, busy }: { page: CompanionPage; onSet: (p: Patch) => void; busy: boolean }) {
  const total = (plan: string) => page.plans.find(p => p.key === plan)?.total || 0;
  return (
    <>
      <h1 className="mock-h">Pick an egg.</h1>
      <p className="mock-sub">
        It hatches when you have solved {page.hatch_at === 3 ? "three" : page.hatch_at} problems, and grows as you solve more.
        Problems are judged exactly as before.{page.solved > 0 && ` The ${plural(page.solved, "problem", "problems")} you already solved ${page.solved === 1 ? "counts" : "count"}.`}
      </p>
      <ul className="eggs">
        {page.eggs.map(e => (
          <li key={e.key}>
            <Porthole size={108} look={{ egg: e.key, stage: 0, cracks: Math.min(page.solved, page.hatch_at - 1) }} label={`${e.name}'s egg`} />
            <div>
              <h2>{e.name}, {EGG_KIND[e.key]}</h2>
              <p>Comes with {PLAN_COPY[e.plan]?.what}: {plural(total(e.plan), "problem", "problems")}.</p>
              <button type="button" className="btn sm primary" disabled={busy} onClick={() => onSet({ egg: e.key })}>Pick {e.name}</button>
            </div>
          </li>
        ))}
      </ul>
      <p className="faint" style={{ fontSize: 14 }}>You can change its path and its name later, or put it away again.</p>
    </>
  );
}

/** An egg was picked: how it is doing. */
function Den({ page, pet, onSet, busy }: { page: CompanionPage; pet: Pet; onSet: (p: Patch) => void; busy: boolean }) {
  const [renaming, setRenaming] = useState(false);
  const [name, setName] = useState(pet.name);
  const [leaving, setLeaving] = useState(false);
  useEffect(() => { setName(pet.name); }, [pet.name]);
  const progress = petProgress(pet, page.stage_xp, page.hatch_at);
  const mood = petMoodLine(pet, page.reviews_due, page.rules.sleep_days);
  const path = page.plans.find(p => p.key === page.plan);
  return (
    <>
      <section className="den">
        <Porthole size={208} look={petLook(pet, page.hatch_at)} label={`${pet.name}, ${EGG_KIND[pet.egg]}`} />
        <div className="den-text">
          {renaming ? (
            <form className="row wrap" onSubmit={e => { e.preventDefault(); onSet({ name }); setRenaming(false); }}>
              <input className="field" style={{ maxWidth: 240 }} value={name} maxLength={24} onChange={e => setName(e.target.value)} autoFocus aria-label="name" />
              <button type="submit" className="btn sm primary" disabled={busy}>Save</button>
              <button type="button" className="btn sm" onClick={() => { setName(pet.name); setRenaming(false); }}>Cancel</button>
            </form>
          ) : (
            <h1 className="mock-h">{pet.name} <button type="button" className="btn ghost sm rename" onClick={() => setRenaming(true)}>Rename</button></h1>
          )}
          <p className="den-status">{petStatus(pet)}</p>
          {mood && <p className="den-status">{mood} {pet.mood === "hungry" && <Link to="/review">Review now</Link>}</p>}
          <div className="bar" role="progressbar" aria-valuenow={Math.round(progress.value * 100)} aria-valuemin={0} aria-valuemax={100} aria-label={progress.label}>
            <i style={{ width: `${Math.round(progress.value * 100)}%` }} />
          </div>
          <p className="faint bar-label">{progress.label}</p>
        </div>
      </section>

      <dl className="den-stats">
        <div><dt>XP</dt><dd>{page.xp.total}</dd></div>
        <div><dt>Problems that count</dt><dd>{page.solved}</dd></div>
        <div><dt>Genres</dt><dd>{page.genres.solved} of {page.genres.total}</dd></div>
        <div><dt>Review answers</dt><dd>{page.xp.reviews}</dd></div>
      </dl>

      <h2 className="h2">How it grows</h2>
      <ul className="den-rules">
        <li>A solved problem gives its size in XP: 15, 30, 45 or 60.</li>
        <li>Each hint you opened takes a fifth off.</li>
        <li>The first solve in a genre adds {page.rules.genre_xp}.</li>
        <li>A solution you read pays after its redo. A redo adds {page.rules.redo_xp}, a review answer {page.rules.review_xp}.</li>
      </ul>

      {(page.recent.length > 0 || page.waiting.length > 0) && (
        <>
          <h2 className="h2">Lately</h2>
          <ul className="den-recent">
            {page.waiting.map(w => (
              <li key={w.pid}><Link to={problemHref(w.pid)}>
                <span className="t"><span className="id">{w.id}</span>{w.title}</span>
                <span className="n faint">pays after its redo on {dateText(w.redo_at)}</span>
              </Link></li>
            ))}
            {page.recent.map(r => (
              <li key={r.pid}><Link to={problemHref(r.pid)}>
                <span className="t"><span className="id">{r.id}</span>{r.title}</span>
                <span className="n faint">{paidNote(r)}</span>
                <span className="x">+{r.xp}</span>
              </Link></li>
            ))}
          </ul>
        </>
      )}

      <h2 className="h2">Its path</h2>
      <p className="muted den-path">
        Today and Highest ranked draw from the path while it has open problems.
        {path && ` ${path.solved} of ${path.total} solved on this one.`}
      </p>
      <div className="den-plans">
        <Segmented id="plan" options={page.plans.map(p => ({ key: p.key, label: PLAN_COPY[p.key]?.label || p.key }))} value={page.plan}
          onChange={plan => { if (plan !== page.plan && !busy) onSet({ plan }); }} />
      </div>

      <button type="button" className="btn ghost sm den-away" onClick={() => setLeaving(true)}>Put {pet.name} away</button>
      <Sheet open={leaving} onClose={() => setLeaving(false)} title={`Put ${pet.name} away?`}>
        <p className="muted" style={{ margin: "0 0 18px", lineHeight: 1.5 }}>
          The home page goes back to how it was. Nothing is lost: its XP comes from what you solved, so it is all there if you pick an egg again.
        </p>
        <div className="row">
          <button type="button" className="btn primary" disabled={busy} onClick={() => { setLeaving(false); onSet({ egg: "" }); }}>Put it away</button>
          <button type="button" className="btn" onClick={() => setLeaving(false)}>Keep it</button>
        </div>
      </Sheet>
    </>
  );
}

export function Companion() {
  const { data, error, loading, setData } = useAsync(() => api.companion(), []);
  const [busy, setBusy] = useState(false);
  useEffect(() => { document.title = "mogi — companion"; }, []);
  async function set(patch: Patch) {
    if (busy) return;
    setBusy(true);
    try {
      const next = await api.companionSet(patch);
      setData(() => next);
      if (patch.egg) toast(`${next.pet?.name} is yours.`);
    } catch (e) { toast((e as Error).message); } finally { setBusy(false); }
  }
  if (error instanceof AuthError) return <Login />;
  return (
    <>
      <TopBar title="Companion" />
      <main className="page companion">
        {loading && !data && <Spinner label="Loading…" />}
        {error && !data && <p style={{ color: "var(--bad)" }}>{error.message}</p>}
        {data && (data.pet ? <Den page={data} pet={data.pet} onSet={p => void set(p)} busy={busy} /> : <Choose page={data} onSet={p => void set(p)} busy={busy} />)}
      </main>
    </>
  );
}
