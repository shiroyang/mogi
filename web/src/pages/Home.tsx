// Home: one glass card on the water — today's problem first, then where you left off.
import { motion, useReducedMotion } from "motion/react";
import { useMemo, useState } from "react";
import { Link } from "react-router";
import { api, AuthError, problemHref, type Home as HomeData, type Slim } from "../api";
import { Porthole } from "../components/Creature";
import { MockClock } from "../components/MockClock";
import { Heatmap } from "../components/ui";
import { Water } from "../components/Water";
import { readLast, useAsync } from "../hooks";
import { dailyCopy, homeCopy, minutesText, petCaption, petLook, plural, progressText, reviewCopy } from "../model";
import { Login } from "./Login";

function Tile({ to, label, p, title, sub, primary }:
  { to: string; label: string; p?: Slim | null; title?: string; sub: string; primary?: boolean }) {
  const heading = p ? <><span className="id">{p.id}</span>{p.title}</> : (title ?? sub);
  return (
    <motion.div whileTap={{ scale: .985 }} transition={{ type: "spring", stiffness: 500, damping: 30 }}>
      <Link className={`tile ${primary ? "primary" : ""}`} to={to}>
        <span className="label">{label}</span>
        <span className="title">{heading}</span>
        {(p || title) && <span className="sub">{sub}</span>}
      </Link>
    </motion.div>
  );
}

/** Which of today's alternates is showing. Remembered for the day, so a reload keeps your choice. */
function useTodayIndex(day: string): [number, (n: number) => void] {
  const [index, setIndex] = useState(() => {
    try {
      const saved = JSON.parse(localStorage.getItem("mogi-today") || "null");
      return saved && saved.day === day ? Number(saved.index) || 0 : 0;
    } catch { return 0; }
  });
  return [index, n => {
    setIndex(n);
    try { localStorage.setItem("mogi-today", JSON.stringify({ day, index: n })); } catch { /* ignore */ }
  }];
}

function Body({ h, local }: { h: HomeData; local: ReturnType<typeof readLast> }) {
  const [index, setIndex] = useTodayIndex(h.today);
  const items = h.daily?.items || [];
  const copy = dailyCopy(h.daily, index);
  const today = items.length ? items[index % items.length] : null;

  // Continue = the unsolved problem touched most recently on any device — or the
  // one this browser last had open, if that is newer.
  let cont: (Slim & { local?: boolean }) | null = h.last;
  if (local && h.hint && h.hint.status !== "solved" && !h.hint.redo_at && local.ts > (h.last ? (h.last.last_at || 0) * 1000 : 0))
    cont = { ...h.hint, local: true };
  if (cont && today && cont.pid === today.pid) cont = null;  // Today already offers it
  if (h.mock) cont = null;  // a running mock is what to continue, and its problem's genre stays unsaid

  // Highest ranked = the most important open problem, whatever its size.
  const taken = [today?.pid, cont?.pid];
  const big = [h.next, h.next2].find(p => p && !taken.includes(p.pid)) || null;
  const { headline, support } = homeCopy(h);
  const review = reviewCopy(h.review);
  return (
    <>
      {h.pet && (
        // the companion lives in a round window beside the headline; the text flows around it
        <Link className="pet" to="/companion" title={`${h.pet.name}, your companion`}>
          <Porthole look={petLook(h.pet)} size={112} label={h.pet.name} />
          <span className="pet-name">{h.pet.name}</span>
          <span className="pet-state">{petCaption(h.pet)}</span>
        </Link>
      )}
      <h1 className="headline">{headline}</h1>
      <p className="support">{support.join(" ")}</p>
      <div className="tiles">
        {h.mock ? (
          // a mock is running: it comes first, and today's pick waits
          <motion.div whileTap={{ scale: .985 }} transition={{ type: "spring", stiffness: 500, damping: 30 }}>
            <Link className="tile primary" to="/mock">
              <span className="label">Mock in progress</span>
              <span className="title"><MockClock endsAt={h.mock.ends_at} /> left</span>
              <span className="sub">{h.mock.solved} of {h.mock.total} solved. Open it to carry on.</span>
            </Link>
          </motion.div>
        ) : today && copy
          ? <Tile to={problemHref(today.pid)} label="Today" primary p={today} sub={copy.sub} />
          : <div className="tile primary"><span className="label">Today</span><span className="title">Every problem is solved.</span></div>}
        {!h.mock && copy?.another && (
          <button type="button" className="another" onClick={() => setIndex((index + 1) % items.length)}>Not this one? Show another.</button>
        )}
        {/* two to a row; an odd one out takes the full width (see .tiles .row in pages.css) */}
        <div className="row">
          {review && <Tile to="/review" label="Review" title={review.title} sub={review.sub} />}
          {cont && <Tile to={problemHref(cont.pid)} label="Continue" p={cont} sub={progressText(cont)} />}
          {big && <Tile to={problemHref(big.pid)} label="Highest ranked" p={big}
            sub={`${big.genre}, importance ${big.importance}.${big.minutes ? ` ${big.difficulty || "Unrated"}, ${minutesText(big.minutes)}.` : ""}`} />}
          {!h.mock && <Tile to="/mock" label="Mock" title="A timed round" sub="Problems you have not solved, on a clock, with no hints." />}
          {!h.pet && <Tile to="/companion" label="Companion" title="Pick an egg" sub="It hatches after three solved problems and grows as you go." />}
          <Tile to="/problems" label="All problems" title={`${h.total} problems`}
            sub={`${plural(h.genres_left, "genre", "genres")} still open`} />
        </div>
      </div>
      <Heatmap events={h.events || []} caption="the last 26 weeks" />
    </>
  );
}

export function Home() {
  const reduce = useReducedMotion();
  const local = useMemo(readLast, []);
  const { data, error, loading, reload } = useAsync(() => api.home(local?.pid), []);
  if (error instanceof AuthError) return <Login />;
  return (
    <>
      <Water still={!!reduce} />
      <main className="stage">
        <motion.section className="glass card home" initial={reduce ? false : { opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }}
          transition={{ duration: .7, ease: [.2, .7, .2, 1] }} aria-busy={loading}>
          <div className="etch" aria-hidden="true">模擬</div>
          <header className="top">
            <span className="wordmark">mogi</span>
            {data && <span className="who">@{data.login}<a href="/api/auth/logout">Sign out</a></span>}
          </header>
          {!data && loading && <h1 className="headline muted">Loading your judge…</h1>}
          {error && !data && (
            <>
              <h1 className="headline">Couldn’t reach the judge.</h1>
              <p className="support" style={{ color: "var(--bad)" }}>{error.message}</p>
              <div className="tiles"><button className="tile" onClick={reload}><span className="title">Try again</span></button></div>
            </>
          )}
          {data && <Body h={data} local={local} />}
        </motion.section>
      </main>
    </>
  );
}
