// All problems: search, genre chips, sort, filters sheet, grouping, categorise.
// One markup for every width — CSS turns the row into a card on phones.
import { useEffect, useMemo, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router";
import { api, AuthError, problemHref, vscodeHref, type MetaResult, type Problem } from "../api";
import { Categorise, type MetaTarget } from "../components/Categorise";
import { Sheet } from "../components/Sheet";
import { Importance, Stars, toast, TopBar } from "../components/ui";
import { useAsync, useIsMobile, useLocalStorage } from "../hooks";
import { applyFilters, DEFAULT_FILTERS, groupByGenre, pickBest, resolveId, SORT_LABELS, type Filters, type SortBy } from "../model";
import { Login } from "./Login";

export function Problems() {
  const mobile = useIsMobile();
  const nav = useNavigate();
  const [params, setParams] = useSearchParams();
  const { data, error, loading, setData } = useAsync(() => api.problems(), []);
  const [f, setF] = useLocalStorage<Filters>("mogi-dash", DEFAULT_FILTERS);
  const [collapsed, setCollapsed] = useLocalStorage<string[]>("mogi-collapsed", []);
  const [filtersOpen, setFiltersOpen] = useState(false);
  const [target, setTarget] = useState<MetaTarget | null>(null);

  const rows = useMemo(() => (data ? applyFilters(data.problems, f) : []), [data, f]);
  const groups = useMemo(() => (f.group ? groupByGenre(rows) : null), [rows, f.group]);
  const genres = data?.genres || [];

  // /problems?open=A16 — a bare id from an old link or the CLI
  useEffect(() => {
    const open = params.get("open");
    if (!open || !data) return;
    const r = resolveId(data.problems, open);
    if (r && "pid" in r) nav(problemHref(r.pid), { replace: true });
    else {
      toast(r && "ambiguous" in r ? `${open} exists in both corpora — pick one` : `unknown problem ${open}`);
      setF(p => ({ ...p, q: open }));
      setParams({}, { replace: true });
    }
  }, [params, data]); // eslint-disable-line react-hooks/exhaustive-deps

  if (error instanceof AuthError) return <Login />;

  const set = (patch: Partial<Filters>) => setF(p => ({ ...p, ...patch }));
  const active = [f.corpus, f.status, f.tier].filter(Boolean).length + (f.group ? 1 : 0);
  const patchRow = (pid: string, res: Partial<Problem>) =>
    setData(d => ({ ...d, problems: d.problems.map(p => (p.pid === pid ? { ...p, ...res } : p)),
                    genres: [...new Set([...d.genres, ...(res.genre ? [res.genre] : [])])].sort((a, b) => a.toLowerCase().localeCompare(b.toLowerCase())) }));
  async function setPriority(p: Problem, n: number) {
    patchRow(p.pid, { priority: n });  // optimistic
    try { const res = await api.setMeta(p.pid, { priority: n }); patchRow(p.pid, res); }
    catch (e) { patchRow(p.pid, { priority: p.priority }); toast((e as Error).message); }
  }
  const onSaved = (res: MetaResult) => patchRow(res.pid, { genre: res.genre, genre_corpus: res.genre_corpus, priority: res.priority, tags: res.tags });
  const pick = () => {
    const best = pickBest(rows);
    if (best) nav(problemHref(best.pid)); else toast("Everything in this filter is solved 🎉");
  };

  const Row = ({ p }: { p: Problem }) => (
    <li className="prow">
      <Link to={problemHref(p.pid)} className="prow-main">
        <span className={`dot ${p.status}`} />
        <span className="pid">{p.id}</span>
        <span className="ptitle">{p.title}</span>
      </Link>
      <div className="pmeta">
        <button type="button" className={`chip genre ${f.genre === p.genre ? "on" : ""}`} title="filter by this genre"
          onClick={() => set({ genre: f.genre === p.genre ? "" : p.genre })}>{p.genre || "—"}</button>
        <Importance value={p.importance} rank={p.rank} />
        <span className="faint freq" title={`seen in ${p.pubs} publication(s) · ${p.family_n} problems share the genre`}>{p.pubs}× · {p.family_n}</span>
        <span className="faint corpus">{p.corpus} · {p.tier}{p.attempts ? ` · ${p.attempts} att.` : ""}</span>
        {p.tags.map(t => <span key={t} className="chip tag">{t}</span>)}
      </div>
      <div className="pact">
        <Stars value={p.priority} onChange={n => void setPriority(p, n)} size={mobile ? "lg" : "sm"} />
        <button type="button" className="btn ghost sm" aria-label={`categorise ${p.id}`} title="categorise: genre · priority · tags"
          onClick={() => setTarget({ pid: p.pid, id: p.id, genre: p.genre, genre_corpus: p.genre_corpus, priority: p.priority, tags: p.tags })}>✎</button>
        {!mobile && <a className="chip vsc" href={vscodeHref(p.pid)} title="Open in VS Code (mogi extension)">VS Code</a>}
      </div>
    </li>
  );

  return (
    <>
      <TopBar title="All problems" right={data && <span className="faint" style={{ fontSize: 13.5 }}><b style={{ color: "var(--ok)" }}>{data.solved}</b> / {data.total} solved</span>} />
      <main className="page problems">
        <div className="controls">
          <input className="field search" type="search" placeholder="Search title, id, genre or tag" value={f.q}
            onChange={e => set({ q: e.target.value })} autoCapitalize="none" autoCorrect="off" />
          <div className="chiprow" role="listbox" aria-label="genre">
            <button type="button" className={`chip ${!f.genre ? "on" : ""}`} onClick={() => set({ genre: "" })}>All genres</button>
            {genres.map(g => (
              <button key={g} type="button" className={`chip ${f.genre === g ? "on" : ""}`} onClick={() => set({ genre: f.genre === g ? "" : g })}>{g}</button>
            ))}
          </div>
          <div className="toolrow">
            <select className="field sort" value={f.sort} onChange={e => set({ sort: e.target.value as SortBy })} aria-label="sort">
              {(Object.keys(SORT_LABELS) as SortBy[]).map(k => <option key={k} value={k}>Sort: {SORT_LABELS[k]}</option>)}
            </select>
            <button type="button" className={`btn ${active ? "primary" : ""}`} onClick={() => setFiltersOpen(true)}>Filters{active ? ` · ${active}` : ""}</button>
            {!mobile && (
              <label className="toggle"><input type="checkbox" checked={f.group} onChange={e => set({ group: e.target.checked })} /> Group by genre</label>
            )}
            <span className="spacer" />
            <button type="button" className="btn primary" onClick={pick} title="open the most important unsolved problem in this filter">Pick one</button>
          </div>
          <div className="faint count">{loading && !data ? "Loading…" : `${rows.length} shown`}</div>
        </div>

        {error && !data && <p style={{ color: "var(--bad)" }}>{error.message}</p>}
        {groups ? groups.map(g => {
          const closed = collapsed.includes(g.key);
          return (
            <section key={g.key} className="group">
              <button type="button" className="ghead" aria-expanded={!closed}
                onClick={() => setCollapsed(c => (closed ? c.filter(x => x !== g.key) : [...c, g.key]))}>
                <span className="caret">{closed ? "▸" : "▾"}</span><b>{g.key}</b>
                <span className="faint">{g.solved}/{g.rows.length} solved · top importance {g.top}</span>
              </button>
              {!closed && <ul className="plist">{g.rows.map(p => <Row key={p.pid} p={p} />)}</ul>}
            </section>
          );
        }) : <ul className="plist">{rows.map(p => <Row key={p.pid} p={p} />)}</ul>}
      </main>

      <Sheet open={filtersOpen} onClose={() => setFiltersOpen(false)} title="Filters">
        <div className="form">
          <label>Corpus</label>
          <select className="field" value={f.corpus} onChange={e => set({ corpus: e.target.value })}>
            <option value="">All corpora</option><option>Amazon</option><option>Google</option>
          </select>
          <label>Status</label>
          <select className="field" value={f.status} onChange={e => set({ status: e.target.value })}>
            <option value="">Any status</option><option value="solved">Solved</option><option value="attempted">Attempted</option><option value="fresh">Untouched</option>
          </select>
          <label>Tier</label>
          <select className="field" value={f.tier} onChange={e => set({ tier: e.target.value })}>
            <option value="">Any tier</option><option value="A">A — design &amp; implement</option><option value="B">B — algorithm</option>
          </select>
          <label className="toggle" style={{ marginTop: 16 }}><input type="checkbox" checked={f.group} onChange={e => set({ group: e.target.checked })} /> Group by genre</label>
          <div className="row" style={{ marginTop: 18 }}>
            <button type="button" className="btn primary" onClick={() => setFiltersOpen(false)}>Done</button>
            <button type="button" className="btn" onClick={() => set({ corpus: "", status: "", tier: "", genre: "", q: "", group: false })}>Reset</button>
          </div>
        </div>
      </Sheet>
      <Categorise target={target} genres={genres} onClose={() => setTarget(null)} onSaved={onSaved} />
    </>
  );
}
