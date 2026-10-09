// Home: one glass card on the water — where you left off, what to do next.
import { motion, useReducedMotion } from "motion/react";
import { useMemo } from "react";
import { Link } from "react-router";
import { api, AuthError, problemHref, type Home as HomeData, type Slim } from "../api";
import { Heatmap } from "../components/ui";
import { Water } from "../components/Water";
import { readLast, useAsync } from "../hooks";
import { homeCopy, plural, progressText } from "../model";
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

function Body({ h, local }: { h: HomeData; local: ReturnType<typeof readLast> }) {
  // Continue = the unsolved problem touched most recently on any device — or the
  // one this browser last had open, if that is newer.
  let cont: (Slim & { local?: boolean }) | null = h.last;
  if (local && h.hint && h.hint.status !== "solved" && local.ts > (h.last ? (h.last.last_at || 0) * 1000 : 0))
    cont = { ...h.hint, local: true };
  let next = h.next;
  if (cont && next && next.pid === cont.pid) next = h.next2;
  const { headline, support } = homeCopy(h);
  const start = !cont && next ? next : null;
  if (start) next = h.next2;
  return (
    <>
      <h1 className="headline">{headline}</h1>
      <p className="support">{support.join(" ")}</p>
      <div className="tiles">
        <Tile to="/problems" label="All problems" primary title={`${h.total} problems, sorted by importance`}
          sub={`${plural(h.genres_left, "genre", "genres")} still open — search, filter, group, star`} />
        <div className="row">
          {cont && <Tile to={problemHref(cont.pid)} label="Continue" p={cont} sub={progressText(cont)} />}
          {start && <Tile to={problemHref(start.pid)} label="Start here" p={start} sub={`${start.genre}, importance ${start.importance}`} />}
          {next && <Tile to={problemHref(next.pid)} label="Next up" p={next}
            sub={`${next.genre}, importance ${next.importance}${next.priority ? ", starred by you" : ""}`} />}
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
