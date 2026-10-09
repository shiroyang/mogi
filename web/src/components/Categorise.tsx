// The categorise form: your genre, 0–5 priority stars, free-form tags.
import { useEffect, useState } from "react";
import { api, type MetaResult } from "../api";
import { Sheet } from "./Sheet";
import { Stars, toast } from "./ui";

export interface MetaTarget { pid: string; id: string; genre: string; genre_corpus: string; priority: number; tags: string[] }

export function Categorise({ target, genres, onClose, onSaved }:
  { target: MetaTarget | null; genres: string[]; onClose: () => void; onSaved: (res: MetaResult) => void }) {
  const [genre, setGenre] = useState("");
  const [prio, setPrio] = useState(0);
  const [tags, setTags] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  useEffect(() => {
    if (!target) return;
    setGenre(target.genre || ""); setPrio(target.priority || 0); setTags((target.tags || []).join(", ")); setErr("");
  }, [target?.pid]); // eslint-disable-line react-hooks/exhaustive-deps

  async function save() {
    if (!target) return;
    setBusy(true); setErr("");
    try {
      const g = genre.trim();
      const res = await api.setMeta(target.pid, {
        genre: g === (target.genre_corpus || "") ? "" : g,  // same as the corpus genre ⇒ clear the override
        priority: prio,
        tags: tags.split(",").map(t => t.trim()).filter(Boolean),
      });
      onSaved(res);
      toast(`${target.id} updated`);
      onClose();
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <Sheet open={!!target} onClose={onClose} title={target ? `${target.id} · categorise` : undefined}>
      {target && (
        <form className="form" onSubmit={e => { e.preventDefault(); void save(); }}>
          <label htmlFor="cat-genre">Genre</label>
          <input id="cat-genre" className="field" list="mogi-genres" value={genre} onChange={e => setGenre(e.target.value)}
            placeholder="pick one or type a new genre" autoComplete="off" autoCapitalize="none" />
          <datalist id="mogi-genres">{genres.map(g => <option key={g} value={g} />)}</datalist>
          <div className="faint" style={{ fontSize: 13, marginTop: 6 }}>
            corpus genre: <b className="muted">{target.genre_corpus || "—"}</b>
            {genre !== target.genre_corpus && (
              <button type="button" className="btn ghost sm" style={{ marginLeft: 6 }} onClick={() => setGenre(target.genre_corpus || "")}>reset to it</button>
            )}
          </div>
          <label>Priority</label>
          <Stars value={prio} onChange={setPrio} size="lg" />
          <label htmlFor="cat-tags">Tags</label>
          <input id="cat-tags" className="field" value={tags} onChange={e => setTags(e.target.value)}
            placeholder="comma separated — redo, weak, mock-1" autoCapitalize="none" />
          <div className="row" style={{ marginTop: 18 }}>
            <button type="submit" className="btn primary" disabled={busy}>{busy ? "Saving…" : "Save"}</button>
            <button type="button" className="btn" onClick={onClose}>Cancel</button>
            {err && <span style={{ color: "var(--bad)", fontSize: 13 }}>{err}</span>}
          </div>
        </form>
      )}
    </Sheet>
  );
}
