// mogi shared helpers — dashboard and problem page
async function api(path, opts = {}) {
  const r = await fetch("/api" + path, {
    credentials: "same-origin",
    headers: { "x-mogi": "1", ...(opts.body ? { "content-type": "application/json" } : {}) },
    ...opts,
  });
  if (r.status === 401) { showLogin(); throw new Error("not signed in"); }
  const data = await r.json();
  if (!r.ok) throw new Error(data.error || r.status);
  return data;
}

function showLogin() {
  document.body.innerHTML = `
    <div class="login-splash">
      <div class="logo">mogi <span style="color:var(--muted);font-size:1.1rem">模擬 — the 真題 judge</span></div>
      <a class="btn primary" href="/api/auth/login">Sign in with GitHub</a>
    </div>`;
}

function esc(s) {
  return String(s ?? "").replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
}

function fmtDate(tsSec) {
  return new Date(tsSec * 1000).toISOString().slice(0, 16).replace("T", " ");
}

// Problem ids are corpus-qualified: "Amazon/A16". Both halves are plain ASCII.
function pidURL(pid) { return "/problem.html?id=" + encodeURIComponent(pid); }
function apiPath(pid) { return "/problems/" + pid.split("/").map(encodeURIComponent).join("/"); }
// Handled by the mogi VS Code extension's URI handler (vscode://<publisher>.<name>/open).
function vscodeURL(pid) { return "vscode://shiroyang.mogi/open?pid=" + encodeURIComponent(pid); }

// Your own ★ priority outranks the computed importance; ties break on the score.
function rankScore(p) { return (p.priority || 0) * 1000 + (p.importance || 0); }

const IMPORTANCE_HELP =
  "Importance 0–100 = shape rank (Amazon README “Start here”: 45…15 for ranks 1–7)\n" +
  "+ 2 × problems sharing the genre (max 12)\n" +
  "+ 8 × extra publications (Alt source, † republished twin; max 2)\n" +
  "+ 4 × confidence stars (how verbatim the published statement is)\n" +
  "+ 6 if Tier A (design & implement).\n" +
  "Your own ★ priority always sorts above it.";

function starsHTML(n, max = 5) {
  let h = "";
  for (let i = 1; i <= max; i++)
    h += `<span class="star ${i <= n ? "on" : ""}" data-star="${i}">★</span>`;
  return `<span class="stars" title="priority ${n || 0}/5 — click a star to set, click it again to clear">${h}</span>`;
}

function bindStars(container, current, onSet) {
  for (const s of container.querySelectorAll(".star")) {
    s.onclick = (e) => {
      e.preventDefault(); e.stopPropagation();
      const k = +s.dataset.star;
      onSet(k === current ? 0 : k);
    };
  }
}

function impHTML(p) {
  const v = p.importance || 0;
  return `<span class="imp" title="${esc(IMPORTANCE_HELP)}"><span class="impbar"><i style="width:${v}%"></i></span>${v}</span>` +
    (p.rank ? `<span class="chip rank" title="shape rank #${p.rank} in the Amazon README’s “Start here” table">#${p.rank}</span>` : "");
}

function freqHTML(p) {
  const pubs = p.pubs || 1, fam = p.family_n || 0;
  const title = `seen in ${pubs} publication${pubs === 1 ? "" : "s"} · ` +
    `${fam} ${esc(p.corpus)} problem${fam === 1 ? "" : "s"} share the genre “${esc(p.genre_corpus || p.genre || "")}”`;
  return `<span class="stat freq" title="${title}">${pubs}× <span class="dim">·</span> ${fam}</span>`;
}

function tagsHTML(tags) {
  return (tags || []).map(t => `<span class="chip tag">${esc(t)}</span>`).join(" ");
}

async function saveMeta(pid, patch) {
  return api(apiPath(pid) + "/meta", { method: "PUT", body: JSON.stringify(patch) });
}

// The categorise popover: genre override, 0–5 priority stars, free-form tags.
function openMetaEditor(anchor, p, genres, onSaved) {
  closeMetaEditor();
  let dl = document.getElementById("mogiGenres");
  if (!dl) { dl = document.createElement("datalist"); dl.id = "mogiGenres"; document.body.appendChild(dl); }
  dl.innerHTML = (genres || []).map(g => `<option value="${esc(g)}">`).join("");

  const pop = document.createElement("div");
  pop.className = "popover"; pop.id = "metaPop";
  pop.innerHTML = `
    <div class="poptitle">${esc(p.id)} <span class="stat">· categorise</span></div>
    <label>Genre
      <input id="mpGenre" list="mogiGenres" value="${esc(p.genre || "")}" placeholder="pick one or type a new genre" autocomplete="off">
    </label>
    <div class="stat">corpus genre: <b>${esc(p.genre_corpus || "—")}</b>
      <button class="link" id="mpReset" type="button">reset to it</button></div>
    <label>Priority <span id="mpStars"></span></label>
    <label>Tags
      <input id="mpTags" value="${esc((p.tags || []).join(", "))}" placeholder="comma separated — redo, weak, mock-1">
    </label>
    <div class="poprow">
      <button class="btn primary" id="mpSave" type="button">Save</button>
      <button class="btn" id="mpCancel" type="button">Cancel</button>
      <span class="stat" id="mpMsg"></span>
    </div>`;
  document.body.appendChild(pop);

  const r = anchor.getBoundingClientRect();
  const top = Math.min(r.bottom + 6 + scrollY, scrollY + innerHeight - pop.offsetHeight - 12);
  const left = Math.max(8, Math.min(r.left + scrollX, scrollX + innerWidth - pop.offsetWidth - 12));
  pop.style.top = `${top}px`; pop.style.left = `${left}px`;

  let prio = p.priority || 0;
  const starsEl = pop.querySelector("#mpStars");
  const paint = () => {
    starsEl.innerHTML = starsHTML(prio);
    bindStars(starsEl, prio, k => { prio = k; paint(); });
  };
  paint();
  pop.querySelector("#mpReset").onclick = () => { pop.querySelector("#mpGenre").value = p.genre_corpus || ""; };
  pop.querySelector("#mpCancel").onclick = closeMetaEditor;
  pop.querySelector("#mpSave").onclick = async () => {
    const msg = pop.querySelector("#mpMsg");
    msg.textContent = "saving…";
    try {
      const genre = pop.querySelector("#mpGenre").value.trim();
      const res = await saveMeta(p.pid, {
        genre: genre === (p.genre_corpus || "") ? "" : genre,  // same as corpus ⇒ clear the override
        priority: prio,
        tags: pop.querySelector("#mpTags").value,
      });
      closeMetaEditor();
      onSaved(res);
    } catch (e) { msg.textContent = e.message; }
  };
  pop.onkeydown = (e) => {
    if (e.key === "Escape") closeMetaEditor();
    if (e.key === "Enter" && e.target.tagName === "INPUT") pop.querySelector("#mpSave").click();
  };
  const outside = (e) => { if (!pop.contains(e.target) && e.target !== anchor) closeMetaEditor(); };
  pop._outside = outside;
  setTimeout(() => document.addEventListener("mousedown", outside), 0);
  pop.querySelector("#mpGenre").focus();
}

function closeMetaEditor() {
  const pop = document.getElementById("metaPop");
  if (!pop) return;
  document.removeEventListener("mousedown", pop._outside);
  pop.remove();
}

// GitHub-style heatmap: events = [{ts(ms), verdict}], weeks columns × 7 rows
function renderHeatmap(el, events, weeks = 26) {
  const byDay = {};
  for (const e of events) {
    const d = new Date(e.ts).toISOString().slice(0, 10);
    byDay[d] = (byDay[d] || 0) + (e.verdict === "AC" ? 1 : 0.25);
  }
  const cells = [];
  const today = new Date();
  const start = new Date(today); start.setDate(today.getDate() - (weeks * 7 - 1) - today.getDay());
  for (let i = 0; i < weeks * 7 + today.getDay() + 1; i++) {
    const d = new Date(start); d.setDate(start.getDate() + i);
    if (d > today) break;
    const key = d.toISOString().slice(0, 10);
    const n = byDay[key] || 0;
    const lvl = n === 0 ? "" : n < 1 ? "l1" : n < 3 ? "l2" : n < 6 ? "l3" : "l4";
    cells.push(`<div class="${lvl}" title="${key}: ${n} "></div>`);
  }
  el.innerHTML = cells.join("");
}
