// mogi home: where you left off, what to do next, and the state of the campaign.
(function () {
  const card = document.getElementById("card");
  const content = document.getElementById("content");
  const who = document.getElementById("who");
  const reduced = matchMedia("(prefers-reduced-motion: reduce)").matches;
  if (reduced) for (const a of document.querySelectorAll("animate")) a.remove();

  // --- copy helpers ---------------------------------------------------
  const WORDS = ["", "One", "Two", "Three", "Four", "Five", "Six", "Seven", "Eight", "Nine", "Ten"];
  const count = n => WORDS[n] || String(n);
  const plural = (n, one, many) => `${n} ${n === 1 ? one : many}`;
  function agoFromSeconds(sec) {
    if (!sec) return "";
    const d = Math.floor((Date.now() / 1000 - sec) / 86400);
    if (d <= 0) return "today";
    if (d === 1) return "yesterday";
    if (d < 30) return `${d} days ago`;
    if (d < 365) return `${Math.round(d / 30)} months ago`;
    return "over a year ago";
  }
  function agoFromDay(iso) {
    const d = Math.round((Date.now() - Date.parse(iso + "T12:00:00Z")) / 86400000);
    return d <= 0 ? "today" : d === 1 ? "yesterday" : d < 30 ? `${d} days ago` : `${Math.round(d / 30)} months ago`;
  }
  function progressText(p) {
    const n = p.attempts || 0;
    const when = p.last_at ? ` ${agoFromSeconds(p.last_at)}` : "";
    const parts = [p.genre];
    if (n > 0) parts.push(`submitted ${n === 1 ? "once" : n === 2 ? "twice" : n + " times"}${when}`);
    else if (p.last_at) parts.push(`tests run${when}, nothing submitted yet`);
    if (p.local) parts.push("draft saved in this browser");
    else if (n === 0 && !p.last_at) parts.push("not started");
    return parts.join(", ");
  }
  const tile = (href, label, p, sub, cls = "") => `
    <a class="tile ${cls}" href="${href}">
      <span class="label">${esc(label)}</span>
      <span class="title">${p ? `<span class="id">${esc(p.id)}</span>${esc(p.title)}` : esc(sub)}</span>
      ${p ? `<span class="sub">${esc(sub)}</span>` : ""}
    </a>`;

  // --- states ---------------------------------------------------------
  function renderLogin() {
    content.innerHTML = `
      <h1 class="headline">Your judge for the 真題 corpus.</h1>
      <p class="support">250 real interview questions, each carrying its own tests. Sign in to pick up where you left off.</p>
      <div class="tiles"><a class="tile primary" href="/api/auth/login"><span class="title">Sign in with GitHub</span></a></div>`;
  }
  function renderError(msg) {
    content.innerHTML = `
      <h1 class="headline">Couldn’t reach the judge.</h1>
      <p class="support err">${esc(msg)}</p>
      <div class="tiles"><a class="tile" href="/"><span class="title">Try again</span></a></div>`;
  }
  function render(h, local) {
    who.innerHTML = `@${esc(h.login)}<a href="/api/auth/logout">Sign out</a>`;

    // Continue = the unsolved problem you touched most recently, on any device —
    // or the one this browser last had open, if that is newer.
    let cont = h.last;
    if (local && h.hint && h.hint.status !== "solved" && local.ts > (h.last ? h.last.last_at * 1000 : 0))
      cont = { ...h.hint, local: true };
    let next = h.next;
    if (cont && next && next.pid === cont.pid) next = h.next2;

    const headline = h.solved
      ? `${h.solved} of ${h.total} solved.`
      : `${h.total} problems, none solved yet.`;
    const bits = [];
    if (h.streak >= 2) bits.push(`<span class="fresh">${count(h.streak)}-day streak.</span>`);
    else if (h.streak === 1) bits.push(`<span class="fresh">Accepted today.</span>`);
    else if (h.last_ac_day) bits.push(`Last accepted ${agoFromDay(h.last_ac_day)}.`);
    // only call a genre "close to done" when it is: ≤3 left, or at least half solved
    const near = h.near && (h.near.left <= 3 || h.near.solved >= h.near.left) ? h.near : null;
    if (near) bits.push(`${esc(near.genre)} is ${plural(near.left, "problem", "problems")} from done.`);
    else if (h.top_genre) bits.push(`${esc(h.top_genre.genre)} holds the highest-ranked problems, ${h.top_genre.left} still open.`);

    let tiles = "";
    if (cont) {
      tiles += tile(pidURL(cont.pid), "Continue", cont, progressText(cont), "primary");
    } else if (next) {
      tiles += tile(pidURL(next.pid), "Start here", next, `${next.genre}, importance ${next.importance}`, "primary");
      next = h.next2;
    }
    tiles += `<div class="row">`;
    if (next) tiles += tile(pidURL(next.pid), "Next up", next,
      `${next.genre}, importance ${next.importance}${next.priority ? ", starred by you" : ""}`);
    tiles += tile("/problems.html", "All problems", null,
      `${h.total} problems, ${plural(h.genres_left, "genre", "genres")} still open`);
    tiles += `</div>`;

    content.innerHTML = `
      <h1 class="headline">${esc(headline)}</h1>
      <p class="support">${bits.join(" ")}</p>
      <div class="tiles">${tiles}</div>
      <div class="pulse"><div class="heatmap" id="heat"></div><span class="cap">the last 26 weeks</span></div>`;
    renderHeatmap(document.getElementById("heat"), h.events || []);
  }

  // --- liquid glass refraction (Chromium: backdrop-filter accepts an SVG filter) ---
  function displacementMap(w, h, radius, bezel) {
    const c = document.createElement("canvas");
    c.width = w; c.height = h;
    const ctx = c.getContext("2d");
    const img = ctx.createImageData(w, h), d = img.data;
    const cx = w / 2, cy = h / 2, hx = w / 2 - radius, hy = h / 2 - radius;
    for (let y = 0; y < h; y++) {
      for (let x = 0; x < w; x++) {
        const i = (y * w + x) * 4;
        let r = 128, g = 128;
        const px = x + .5 - cx, py = y + .5 - cy;
        const qx = Math.abs(px) - hx, qy = Math.abs(py) - hy;
        let dist, nx, ny;
        if (qx > 0 && qy > 0) {            // corner: distance to the arc
          const len = Math.hypot(qx, qy) || 1;
          dist = radius - len; nx = Math.sign(px) * qx / len; ny = Math.sign(py) * qy / len;
        } else if (qx > qy) { dist = radius - qx; nx = Math.sign(px); ny = 0; }
        else { dist = radius - qy; nx = 0; ny = Math.sign(py); }
        if (dist >= 0 && dist < bezel) {    // inside the bezel band: bend toward the centre
          const t = 1 - dist / bezel, k = t * t;
          r = Math.round(128 - nx * k * 127); g = Math.round(128 - ny * k * 127);
        }
        d[i] = r; d[i + 1] = g; d[i + 2] = 0; d[i + 3] = 255;
      }
    }
    ctx.putImageData(img, 0, 0);
    return c.toDataURL();
  }
  function setupRefraction() {
    const ok = window.CSS && CSS.supports &&
      (CSS.supports("backdrop-filter", "url(#glassRefract)") || CSS.supports("-webkit-backdrop-filter", "url(#glassRefract)"));
    if (!ok) return;
    const filter = document.getElementById("glassRefract");
    let w = 0, h = 0;
    const build = () => {
      const nw = card.offsetWidth, nh = card.offsetHeight;
      if (nw < 2 || nh < 2 || (nw === w && nh === h)) return;
      w = nw; h = nh;
      const map = displacementMap(w, h, 28, 30);
      filter.setAttribute("width", w); filter.setAttribute("height", h);
      filter.innerHTML =
        `<feGaussianBlur in="SourceGraphic" stdDeviation="22" result="blurred"/>` +
        `<feImage href="${map}" x="0" y="0" width="${w}" height="${h}" preserveAspectRatio="none" result="map"/>` +
        `<feDisplacementMap in="blurred" in2="map" scale="34" xChannelSelector="R" yChannelSelector="G" result="bent"/>` +
        `<feColorMatrix in="bent" type="saturate" values="1.5"/>`;
      card.classList.add("refract");
    };
    build();
    let t;
    new ResizeObserver(() => { clearTimeout(t); t = setTimeout(build, 150); }).observe(card);
  }

  // --- go -------------------------------------------------------------
  (async () => {
    let local = null;
    try { local = JSON.parse(localStorage.getItem("mogi-last") || "null"); } catch { /* ignore */ }
    try {
      const q = local && local.pid ? "?hint=" + encodeURIComponent(local.pid) : "";
      const r = await fetch("/api/home" + q, { credentials: "same-origin", headers: { "x-mogi": "1" } });
      if (r.status === 401) { renderLogin(); return; }
      const h = await r.json();
      if (!r.ok) throw new Error(h.error || r.status);
      render(h, local);
    } catch (e) {
      renderError(e.message || String(e));
    } finally {
      card.removeAttribute("aria-busy");
      setupRefraction();
    }
  })();
})();
