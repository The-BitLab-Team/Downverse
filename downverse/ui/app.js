/* Downverse — interface. Sem framework: DOM direto, sempre com textContent (os títulos vêm da internet). */
"use strict";
(() => {
  // ───────────────────────── utilidades ─────────────────────────
  const SVGNS = "http://www.w3.org/2000/svg";
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  const debounce = (fn, ms) => { let t; return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); }; };

  function append(el, kids) {
    for (const k of kids.flat(Infinity)) {
      if (k == null || k === false) continue;
      el.append(k.nodeType ? k : document.createTextNode(String(k)));
    }
  }
  function h(tag, props, ...kids) {
    const el = document.createElement(tag);
    for (const [k, v] of Object.entries(props || {})) {
      if (v == null || v === false) continue;
      if (k === "class") el.className = v;
      else if (k === "text") el.textContent = v;
      else if (k.startsWith("on")) el.addEventListener(k.slice(2).toLowerCase(), v);
      else if (k === "dataset") Object.assign(el.dataset, v);
      else if (k in el && !k.includes("-") && typeof v !== "object") el[k] = v;
      else el.setAttribute(k, v === true ? "" : v);
    }
    append(el, kids);
    return el;
  }
  function s(tag, attrs, ...kids) {
    const el = document.createElementNS(SVGNS, tag);
    for (const [k, v] of Object.entries(attrs || {})) el.setAttribute(k, v);
    append(el, kids);
    return el;
  }
  const icon = (name, cls = "") => s("svg", { class: `ic ${cls}`.trim(), "aria-hidden": "true" }, s("use", { href: `#i-${name}` }));

  const fmtBytes = (n) => {
    if (!n && n !== 0) return "";
    const u = ["B", "KB", "MB", "GB", "TB"]; let i = 0, v = n;
    while (v >= 1024 && i < u.length - 1) { v /= 1024; i++; }
    return `${v.toLocaleString("pt-BR", { maximumFractionDigits: i >= 2 ? 1 : 0 })} ${u[i]}`;
  };
  const fmtDuration = (sec) => {
    if (!sec) return "";
    sec = Math.round(sec); const hh = Math.floor(sec / 3600), mm = Math.floor((sec % 3600) / 60), ss = sec % 60;
    return hh ? `${hh}:${String(mm).padStart(2, "0")}:${String(ss).padStart(2, "0")}` : `${mm}:${String(ss).padStart(2, "0")}`;
  };
  const fmtEta = (sec) => {
    if (sec == null) return "";
    sec = Math.round(sec);
    if (sec < 60) return `${sec} s`;
    if (sec < 3600) return `${Math.round(sec / 60)} min`;
    return `${Math.floor(sec / 3600)} h ${Math.round((sec % 3600) / 60)} min`;
  };
  const fmtDay = (iso) => {
    const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(iso || "");
    if (!m) return iso || "";
    return new Date(+m[1], +m[2] - 1, +m[3]).toLocaleDateString("pt-BR", { day: "2-digit", month: "short", year: "numeric" }).replace(/\./g, "");
  };
  const fmtTs = (ts) => ts ? new Date(ts * 1000).toLocaleDateString("pt-BR", { day: "2-digit", month: "short", year: "numeric" }).replace(/\./g, "") : "";
  const plural = (n, one, many) => `${n} ${n === 1 ? one : many}`;
  const qLabel = (q) => ({ best: "Melhor", worst: "Menor" }[q] || (q ? `${q}p` : ""));

  function toast(msg, err = false) {
    const el = h("div", { class: `toast${err ? " err" : ""}` }, icon(err ? "triangle-alert" : "circle-check", "sm"), h("span", { text: msg }));
    $("#toasts").append(el);
    setTimeout(() => el.remove(), err ? 6000 : 3200);
  }
  const $ = (sel, root = document) => root.querySelector(sel);

  // ───────────────────────── API ─────────────────────────
  let TOKEN = new URLSearchParams(location.search).get("t");
  try {
    if (TOKEN) sessionStorage.setItem("dv-token", TOKEN); else TOKEN = sessionStorage.getItem("dv-token");
  } catch { /* sem sessionStorage: segue com o token da URL */ }
  if (location.search) history.replaceState(null, "", location.pathname);

  async function request(method, path, body) {
    const res = await fetch(path, {
      method,
      headers: { "X-Downverse-Token": TOKEN || "", ...(body !== undefined ? { "Content-Type": "application/json" } : {}) },
      body: body !== undefined ? JSON.stringify(body) : undefined,
    });
    let data = null;
    try { data = await res.json(); } catch { /* resposta sem JSON */ }
    if (!res.ok) throw new Error((data && data.error) || `Erro ${res.status}`);
    return data;
  }
  const api = { get: (p) => request("GET", p), post: (p, b = {}) => request("POST", p, b) };

  // ───────────────────────── estado ─────────────────────────
  const S = {
    view: "download", st: null, err: false,
    parse: { state: "idle" },
    an: null, sel: new Set(), touched: false, limit: 100,
    f: { q: "", member: "", from: "", to: "", hideDone: false },
    libCount: -1, lib: [], libQ: "",
  };
  const LANGS = [["pt", "Português"], ["en", "Inglês"], ["ko", "Coreano"], ["ja", "Japonês"], ["zh", "Chinês"], ["es", "Espanhol"], ["id", "Indonésio"], ["th", "Tailandês"], ["vi", "Vietnamita"]];
  const QUALITIES = [["best", "Melhor disponível"], ["1080", "Até 1080p"], ["720", "Até 720p"], ["480", "Até 480p"], ["360", "Até 360p"], ["worst", "Menor tamanho"]];
  const settings = () => S.st.settings;

  async function save(patch) {
    try {
      const r = await api.post("/api/settings", patch);
      S.st.settings = r.settings; S.st.output_dir = r.output_dir;
      if (patch.theme) applyTheme();
      current && current.update();
    } catch (e) { toast(e.message, true); }
  }
  const applyTheme = () => { document.documentElement.dataset.theme = settings().theme; $("#theme-toggle").checked = settings().theme === "dark"; };

  // ───────────────────────── componentes compartilhados ─────────────────────────
  function toggleField(label, onChange) {
    const input = h("input", { type: "checkbox", onChange: () => onChange(input.checked), "aria-label": label });
    return { input, el: h("label", { class: "toggle-field" }, h("span", { text: label }), h("span", { class: "switch" }, input, h("i"))) };
  }
  function selectField(label, options, onChange) {
    const select = h("select", { class: "select", onChange: () => onChange(select.value) }, options.map(([v, t]) => h("option", { value: v, text: t })));
    return { select, el: h("label", { class: "field" }, h("span", { text: label }), select) };
  }
  function langChips() {
    const wrap = h("div", { class: "langs", role: "group", "aria-label": "Idiomas das legendas" });
    const all = h("button", { class: "lang", type: "button", onClick: () => save({ subtitle_langs: [] }), text: "Todos" });
    const btns = LANGS.map(([code, name]) => h("button", {
      class: "lang", type: "button", dataset: { code }, text: name,
      onClick: () => {
        const cur = new Set(settings().subtitle_langs.map((c) => c.split("_")[0]));
        cur.has(code) ? cur.delete(code) : cur.add(code);
        save({ subtitle_langs: [...cur] });
      },
    }));
    append(wrap, [all, btns]);
    return {
      el: wrap,
      update() {
        const cur = new Set(settings().subtitle_langs.map((c) => c.split("_")[0]));
        all.setAttribute("aria-pressed", String(cur.size === 0));
        btns.forEach((b) => b.setAttribute("aria-pressed", String(cur.has(b.dataset.code))));
      },
    };
  }
  function setValue(el, value) { if (document.activeElement !== el && el.value !== value) el.value = value; }
  function setChecked(el, v) { if (el.checked !== !!v) el.checked = !!v; }

  // ───────────────────────── tela: Baixar ─────────────────────────
  function mountDownload(root) {
    const R = {};
    const jobEls = new Map();

    // --- coluna da esquerda
    R.bars = h("div");
    R.gauge = h("div");
    R.legend = h("div", { class: "legend" });
    R.acctTitle = h("h4"); R.acctText = h("p");
    const left = h("div", { class: "col" },
      h("section", { class: "card" }, h("div", { class: "card-head" }, h("div", {}, h("h3", { text: "Atividade" }), h("p", { class: "sub", text: "Lives baixadas nos últimos 7 dias" }))), R.bars),
      h("section", { class: "card" }, h("div", { class: "card-head" }, h("div", {}, h("h3", { text: "Status da fila" }), h("p", { class: "sub", text: "Andamento desta sessão" }))), R.gauge, R.legend),
      h("section", { class: "card acct" }, accountArt(), R.acctTitle, R.acctText,
        h("button", { class: "btn soft sm", type: "button", onClick: () => go("account") }, icon("plug", "sm"), "Configurar conta")),
    );

    // --- novo download
    R.url = h("input", { class: "input", type: "text", placeholder: "Cole aqui o link da live ou do canal no Weverse", spellcheck: false, autocomplete: "off", "aria-label": "Link do Weverse",
      onInput: () => parseNow(), onKeydown: (e) => { if (e.key === "Enter") submit(); } });
    R.paste = h("button", { class: "btn ghost", type: "button", onClick: pasteLink }, icon("clipboard-paste", "sm"), "Colar");
    R.detect = h("div", { class: "detect", "aria-live": "polite" });
    const quality = selectField("Qualidade", QUALITIES, (v) => save({ quality: v }));
    const subs = toggleField("Legendas", (v) => save({ subtitles: v }));
    const thumb = toggleField("Thumbnail", (v) => save({ thumbnail: v }));
    const mode = selectField("Pasta do membro", [["auto", "Automática"], ["solo", "Nunca (artista solo)"]], (v) => save({ artist_mode: v }));
    R.q = quality.select; R.subs = subs.input; R.thumb = thumb.input; R.mode = mode.select;
    R.langs = langChips();
    R.langBox = h("div", { class: "field" }, h("span", { class: "lbl", text: "Idiomas das legendas (sem seleção = todos os disponíveis)" }), R.langs.el);
    R.dest = h("b"); R.go = h("button", { class: "btn primary", type: "button", disabled: true, onClick: submit });
    const newdl = h("section", { class: "card newdl" },
      h("div", { class: "card-head", style: "margin:0" }, h("div", {}, h("h3", { text: "Novo download" }), h("p", { class: "sub", text: "Cole o link de uma live ou do canal inteiro do artista/grupo." }))),
      h("div", { class: "urlbox" }, h("div", { class: "wrap" }, icon("link-2"), R.url), R.paste),
      R.detect,
      h("div", { class: "opts" }, quality.el, subs.el, thumb.el, mode.el),
      R.langBox,
      h("div", { class: "newdl-foot" },
        h("div", { class: "dest" }, icon("folder-open", "sm"), R.dest, h("button", { class: "btn link", type: "button", onClick: () => go("settings"), text: "Alterar" })),
        R.go),
    );

    R.banners = h("div", { class: "col", style: "gap:12px" });
    R.chan = h("div");

    // --- resumo e fila
    R.sQueue = h("b"); R.sQueueSub = h("small"); R.sDone = h("b"); R.sSize = h("b"); R.sSizeSub = h("small");
    const stats = h("div", { class: "stats" },
      h("div", { class: "stat s-blue" }, h("div", { class: "top" }, h("span", { text: "Na fila" }), icon("layers")), R.sQueue, R.sQueueSub),
      h("div", { class: "stat s-purple" }, h("div", { class: "top" }, h("span", { text: "Na biblioteca" }), icon("circle-check")), R.sDone, h("small", { text: "lives baixadas" })),
      h("div", { class: "stat s-coral" }, h("div", { class: "top" }, h("span", { text: "Espaço usado" }), icon("hard-drive")), R.sSize, R.sSizeSub),
    );
    R.lanes = {}; R.counts = {}; R.empty = {};
    const laneEl = (key, title, msg) => {
      R.counts[key] = h("span", { text: "0" });
      R.lanes[key] = h("div", { class: "lane-body" });
      R.empty[key] = h("div", { class: "empty" }, icon("film"), h("span", { text: msg }));
      return h("div", { class: `lane ${key}` }, h("div", { class: "lane-head" }, title, R.counts[key]), R.lanes[key]);
    };
    R.board = h("div", { class: "board" },
      laneEl("queued", "Na fila", "Nada esperando. Cole um link acima."),
      laneEl("active", "Baixando", "Nenhum download em andamento."),
      laneEl("done", "Finalizados", "Os downloads concluídos aparecem aqui."));
    R.clear = h("button", { class: "btn ghost sm", type: "button", onClick: async () => { await api.post("/api/queue/clear"); refresh(); }, text: "Limpar finalizados" });
    R.cancelAll = h("button", { class: "btn danger sm", type: "button", onClick: async () => { await api.post("/api/queue/cancel-all"); refresh(); }, text: "Cancelar tudo" });

    const right = h("div", { class: "col" }, R.banners, newdl, R.chan,
      h("div", { class: "sec-head" }, h("h3", { text: "Resumo" }),
        h("button", { class: "btn soft sm", type: "button", onClick: () => openPath({ target: "root" }) }, icon("folder-open", "sm"), "Abrir pasta Weverse")),
      stats,
      h("div", { class: "sec-head" }, h("h3", { text: "Fila de downloads" }), h("div", { class: "row-gap" }, R.clear, R.cancelAll)),
      h("section", { class: "card" }, R.board));

    root.append(h("div", { class: "page" },
      h("div", { class: "page-head" }, h("div", {}, h("h2", { text: "Baixar" }), h("p", { text: "VODs do Weverse com legendas e thumbnails, salvos por artista e data." }))),
      h("div", { class: "dash" }, left, right)));

    if (S.an) buildChannel(R);
    renderDetect();

    // --- comportamento
    async function pasteLink() {
      try { R.url.value = await navigator.clipboard.readText(); parseNow(); R.url.focus(); }
      catch { toast("Não consegui ler a área de transferência. Cole com Ctrl+V.", true); R.url.focus(); }
    }
    const parseNow = debounce(async () => {
      const text = R.url.value.trim();
      if (!text) { S.parse = { state: "idle" }; return renderDetect(); }
      try {
        const r = await api.post("/api/parse", { text });
        if (R.url.value.trim() !== text) return;
        S.parse = r.ok ? { state: "ok", link: r.link } : { state: "bad", error: r.error };
      } catch (e) { S.parse = { state: "bad", error: e.message }; }
      renderDetect();
    }, 220);

    function renderDetect() {
      const p = S.parse; R.detect.replaceChildren(); R.go.replaceChildren();
      if (p.state === "ok") {
        const live = p.link.kind === "live";
        R.detect.append(
          h("span", { class: `chip ${live ? "blue" : "purple"}` }, icon(live ? "square-play" : "list-checks", "sm"),
            h("span", { text: live ? `Live específica: ${p.link.community} (${p.link.post_id})` : `Canal inteiro: ${p.link.community}` })),
          p.link.note ? h("span", { class: "hint", text: p.link.note }) : null);
        R.go.disabled = false;
        append(R.go, [icon(live ? "download" : "search", "sm"), live ? "Baixar live" : "Buscar lives"]);
      } else {
        R.go.disabled = true; append(R.go, [icon("download", "sm"), "Baixar"]);
        if (p.state === "bad") R.detect.append(h("span", { class: "chip red wrap" }, icon("triangle-alert", "sm"), h("span", { text: p.error })));
        else R.detect.append(h("span", { class: "hint", text: "Vale o link da live, da página de lives ou da página inicial do artista/grupo." }));
      }
    }

    async function submit() {
      const p = S.parse; if (p.state !== "ok") return;
      try {
        if (p.link.kind === "live") {
          await api.post("/api/downloads", { url: R.url.value });
          toast("Live adicionada à fila"); R.url.value = ""; S.parse = { state: "idle" }; renderDetect();
          await refresh(); flash(R.board);
        } else { await startAnalysis(R.url.value); }
      } catch (e) { toast(e.message, true); }
    }

    // --- atualização periódica
    function update() {
      const st = S.st, cfg = st.settings, q = st.queue, c = q.counts;
      setValue(R.q, cfg.quality); setChecked(R.subs, cfg.subtitles); setChecked(R.thumb, cfg.thumbnail); setValue(R.mode, cfg.artist_mode);
      R.langBox.classList.toggle("hidden", !cfg.subtitles); R.langs.update();
      R.dest.textContent = abbrevPath(st.output_dir); R.dest.title = st.output_dir;

      // avisos
      R.banners.replaceChildren(); R.banners.classList.toggle("hidden", st.ffmpeg && cfg.auth.method !== "none");
      if (!st.ffmpeg) R.banners.append(h("div", { class: "banner" }, icon("triangle-alert"), h("p", { text: "FFmpeg não encontrado. Sem ele não dá para juntar áudio e vídeo nem converter legendas e thumbnails. Instale o FFmpeg ou rode: pip install imageio-ffmpeg." })));
      if (cfg.auth.method === "none") R.banners.append(h("div", { class: "banner blue" }, icon("info"), h("p", { text: "Quase todos os VODs do Weverse exigem login. Conecte sua conta na aba Conta antes de baixar." })));

      // conta
      const method = { none: "Sem conta conectada", browser: `Sessão do ${cfg.auth.browser}`, file: "Arquivo cookies.txt", token: "Token de acesso" }[cfg.auth.method];
      R.acctTitle.textContent = method;
      R.acctText.textContent = cfg.auth.method === "none" ? "Conecte sua conta para baixar VODs de membros e fãs." : "Use “Testar conexão” na aba Conta para conferir a sessão.";

      // resumo
      const active = c.queued + c.downloading;
      R.sQueue.textContent = active; R.sQueueSub.textContent = c.downloading ? `${plural(c.downloading, "baixando agora", "baixando agora")}` : "nenhum download ativo";
      R.sDone.textContent = st.library.count; R.sSize.textContent = fmtBytes(st.library.size) || "0 B";
      R.sSizeSub.textContent = q.session_bytes ? `${fmtBytes(q.session_bytes)} nesta sessão` : "no total";
      R.cancelAll.classList.toggle("hidden", active === 0);
      R.clear.classList.toggle("hidden", c.done + c.error + c.canceled + c.skipped === 0);

      drawBars(R.bars, st.library.activity);
      drawGauge(R, c);
      updateBoard(R, jobEls, q.items);
    }
    return { update, R };
  }

  const abbrevPath = (p, max = 56) => (p.length > max ? `…${p.slice(p.length - max + 1)}` : p);
  const laneOf = (it) => (it.status === "queued" ? "queued" : it.status === "downloading" ? "active" : "done");

  function updateBoard(R, jobEls, items) {
    const lanes = { queued: [], active: [], done: [] };
    for (const it of items) lanes[laneOf(it)].push(it);
    lanes.done.reverse();
    const all = new Set(items.map((i) => i.id));
    for (const [lane, list] of Object.entries(lanes)) {
      const body = R.lanes[lane];
      R.counts[lane].textContent = list.length;
      for (const el of [...body.children]) {
        if (el === R.empty[lane]) continue;
        if (!all.has(el.dataset.id)) { el.remove(); jobEls.delete(el.dataset.id); }
      }
      if (R.empty[lane].parentNode) R.empty[lane].remove();
      list.forEach((it, idx) => {
        let el = jobEls.get(it.id);
        if (!el) { el = createJob(it); jobEls.set(it.id, el); }
        updateJob(el, it);
        if (body.children[idx] !== el) body.insertBefore(el, body.children[idx] || null);
      });
      if (!list.length) body.append(R.empty[lane]);
    }
  }

  function createJob(it) {
    const r = {
      tag: h("span", { class: "tag" }), ic: h("span", { class: "status-ic" }),
      title: h("div", { class: "job-title" }), meta: h("div", { class: "job-meta" }),
      fill: h("i"), bar: h("div", { class: "bar", role: "progressbar", "aria-valuemin": 0, "aria-valuemax": 100 }),
      phase: h("span"), rate: h("span"), line: h("div", { class: "job-line" }),
      err: h("div", { class: "job-err" }), warn: h("div", { class: "job-warn" }), acts: h("div", { class: "job-actions" }),
    };
    r.bar.append(r.fill); r.line.append(r.phase, r.rate);
    const el = h("article", { class: "job", dataset: { id: it.id } }, h("div", { class: "job-top" }, r.tag, r.ic), r.title, r.meta, r.bar, r.line, r.err, r.warn, r.acts);
    el._r = r; el._status = null; return el;
  }

  function updateJob(el, it) {
    const r = el._r, active = it.status === "downloading", queued = it.status === "queued";
    el.className = `job ${it.status}`;
    const who = (it.uploader || it.community || "Weverse").trim();
    r.tag.textContent = who; r.title.textContent = it.title; r.title.title = it.title;
    r.meta.replaceChildren(...[it.date && fmtDay(it.date), qLabel(it.quality), it.size && fmtBytes(it.size)].filter(Boolean).map((t) => h("span", { text: t })));
    r.bar.classList.toggle("hidden", !active); r.line.classList.toggle("hidden", !(active || queued));
    r.fill.style.width = `${it.progress}%`; r.bar.setAttribute("aria-valuenow", Math.round(it.progress));
    r.phase.textContent = active ? `${it.phase} ${Math.round(it.progress)}%` : it.phase;
    r.rate.textContent = active ? [it.speed ? `${fmtBytes(it.speed)}/s` : "", fmtEta(it.eta)].filter(Boolean).join("  ") : "";
    r.err.textContent = it.error || ""; r.err.classList.toggle("hidden", !it.error || it.status === "skipped");
    if (it.status === "skipped") { r.warn.textContent = it.error; r.warn.classList.remove("hidden"); }
    else { r.warn.textContent = (it.warnings || []).join(" "); r.warn.classList.toggle("hidden", !(it.warnings || []).length); }
    const iconName = { queued: "clock", downloading: "loader-circle", done: "circle-check", error: "circle-x", canceled: "ban", skipped: "badge-check" }[it.status];
    if (el._status !== it.status) {
      el._status = it.status;
      r.ic.replaceChildren(icon(iconName, it.status === "downloading" ? "sm spin" : "sm"));
      r.acts.replaceChildren(...jobActions(it));
    }
  }

  function jobActions(it) {
    const act = (label, cls, fn, ic) => h("button", { class: `btn xs ${cls}`, type: "button", onClick: async () => { try { await fn(); } catch (e) { toast(e.message, true); } refresh(); } }, ic ? icon(ic, "sm") : null, label);
    const id = it.id, out = [];
    if (it.status === "queued" || it.status === "downloading") out.push(act("Cancelar", "danger", () => api.post(`/api/queue/${id}/cancel`), "x"));
    if (it.status === "error" || it.status === "canceled") out.push(act("Tentar de novo", "soft", () => api.post(`/api/queue/${id}/retry`, {}), "rotate-cw"));
    if (it.status === "skipped") out.push(act("Baixar de novo", "soft", () => api.post(`/api/queue/${id}/retry`, { force: true }), "rotate-cw"));
    if ((it.status === "done" || it.status === "skipped") && it.dir) out.push(act("Abrir pasta", "ghost", () => api.post("/api/open", { target: "item", id }), "folder-open"));
    return out;
  }

  function flash(el) { el.classList.remove("flash"); void el.offsetWidth; el.classList.add("flash"); el.scrollIntoView({ behavior: "smooth", block: "center" }); }
  async function openPath(body) { try { await api.post("/api/open", body); } catch (e) { toast(e.message, true); } }

  // ---------- gráficos ----------
  function drawBars(box, days) {
    const W = 252, base = 100, maxH = 78, max = Math.max(4, ...days.map((d) => d.count));
    const svg = s("svg", { class: "bars", viewBox: `0 0 ${W} 128`, role: "img", "aria-label": "Downloads concluídos por dia nos últimos 7 dias" });
    days.forEach((d, i) => {
      const x = i * 36 + 10, today = i === days.length - 1;
      const hgt = d.count ? Math.max(12, (d.count / max) * maxH) : 8;
      const fill = d.count ? (today ? "var(--blue)" : "color-mix(in srgb, var(--blue) 42%, var(--surface))") : "var(--blue-soft)";
      svg.append(s("rect", { x, y: base - hgt, width: 16, height: hgt, rx: 8, fill }, s("title", {}, `${d.label}: ${plural(d.count, "live", "lives")}`)));
      if (d.count) svg.append(s("text", { x: x + 8, y: base - hgt - 7, "text-anchor": "middle", class: "val" }, String(d.count)));
      svg.append(s("text", { x: x + 8, y: 120, "text-anchor": "middle", style: today ? "fill:var(--ink);font-weight:800" : "" }, d.label));
    });
    box.replaceChildren(svg);
  }

  function drawGauge(R, c) {
    const total = c.queued + c.downloading + c.done + c.error + c.canceled + c.skipped;
    const finished = c.done + c.skipped, running = c.queued + c.downloading, failed = c.error + c.canceled;
    const pct = (n) => (total ? (n / total) * 100 : 0);
    const arc = "M18 100 A82 82 0 0 1 182 100";
    const svg = s("svg", { viewBox: "0 0 200 108", role: "img", "aria-label": `${Math.round(pct(finished))}% concluído` },
      s("defs", {}, s("linearGradient", { id: "gg", x1: "0", x2: "1", y1: "0", y2: "0" },
        s("stop", { offset: "0", style: "stop-color:var(--blue)" }), s("stop", { offset: ".55", style: "stop-color:var(--purple-2)" }), s("stop", { offset: "1", style: "stop-color:var(--coral)" }))),
      s("path", { d: arc, pathLength: 100, fill: "none", stroke: "var(--blue-soft)", "stroke-width": 16, "stroke-linecap": "round" }));
    if (pct(finished) > 0.5) svg.append(s("path", { d: arc, pathLength: 100, fill: "none", stroke: "url(#gg)", "stroke-width": 16, "stroke-linecap": "round", "stroke-dasharray": `${pct(finished)} 100` }));
    R.gauge.replaceChildren(h("div", { class: "gauge" }, svg,
      h("div", { class: "gauge-mid" }, h("div", { class: "badge" }, icon("arrow-down-to-line", "sm")), h("b", { text: String(total) }), h("span", { text: "itens nesta sessão" }))));
    const row = (color, label, n) => h("div", {}, h("i", { style: `background:${color}` }), label, h("em", { text: `${pct(n).toLocaleString("pt-BR", { maximumFractionDigits: 1 })}%` }));
    R.legend.replaceChildren(row("var(--blue)", "Concluídos", finished), row("var(--coral)", "Na fila ou baixando", running), row("var(--purple-2)", "Com erro ou cancelados", failed));
  }

  function accountArt() {
    const svg = s("svg", { class: "art", viewBox: "0 0 240 96", "aria-hidden": "true" },
      s("rect", { x: 0, y: 0, width: 240, height: 96, rx: 18, fill: "var(--blue-soft)" }),
      s("rect", { x: 22, y: 20, width: 118, height: 56, rx: 12, fill: "var(--surface)" }),
      s("rect", { x: 34, y: 33, width: 60, height: 7, rx: 3.5, fill: "var(--blue)" }),
      s("rect", { x: 34, y: 47, width: 84, height: 6, rx: 3, fill: "var(--line)" }),
      s("rect", { x: 34, y: 59, width: 48, height: 6, rx: 3, fill: "var(--line)" }),
      s("rect", { x: 128, y: 34, width: 90, height: 46, rx: 12, fill: "var(--coral)" }),
      s("circle", { cx: 173, cy: 57, r: 14, fill: "rgba(255,255,255,.25)" }),
      s("path", { d: "M168 50l14 7-14 7z", fill: "#fff" }));
    return svg;
  }

  // ---------- lives do canal ----------
  async function startAnalysis(url) {
    const r = await api.post("/api/analyze", { url });
    S.an = { id: r.id, link: r.link, status: "running", channel: { slug: r.link.community, name: "", thumbnail: "" }, entries: [], error: "" };
    S.sel = new Set(); S.touched = false; S.limit = 100; S.f = { q: "", member: "", from: "", to: "", hideDone: false };
    buildChannel(current.R);
    pollAnalysis(r.id);
  }

  async function pollAnalysis(id) {
    while (S.an && S.an.id === id && S.an.status === "running") {
      try {
        const d = await api.get(`/api/analysis/${id}?since=${S.an.entries.length}`);
        if (!S.an || S.an.id !== id) return;
        S.an.channel = d.channel; S.an.status = d.status; S.an.error = d.error;
        for (const e of d.entries) { S.an.entries.push(e); if (!S.touched && e.downloadable && !e.in_library) S.sel.add(e.id); }
      } catch (e) { S.an.status = "error"; S.an.error = e.message; }
      updateChannel(true);
      if (S.an.status === "running") await sleep(700);
    }
  }

  function closeChannel() {
    if (S.an) api.post(`/api/analysis/${S.an.id}/cancel`).catch(() => {});
    S.an = null; S.sel = new Set();
    if (current && current.R) current.R.chan.replaceChildren();
  }

  function buildChannel(R) {
    const C = (R.C = {});
    const an = S.an;
    C.id = an.id;
    C.avatar = h("div", { class: "ph" }); C.title = h("h3"); C.sub = h("p", { class: "sub" });
    C.avatarBox = h("div", {}, C.avatar);
    C.status = h("span", { class: "chip blue" });
    C.q = h("input", { class: "input sm", type: "search", placeholder: "Buscar por título ou membro", "aria-label": "Buscar lives", onInput: () => { S.f.q = C.q.value; S.limit = 100; renderRows(); } });
    C.member = h("select", { class: "select sm", "aria-label": "Filtrar por membro", onChange: () => { S.f.member = C.member.value; S.limit = 100; renderRows(); } });
    C.from = h("input", { class: "input sm", type: "date", "aria-label": "A partir de", onChange: () => { S.f.from = C.from.value; S.limit = 100; renderRows(); } });
    C.to = h("input", { class: "input sm", type: "date", "aria-label": "Até", onChange: () => { S.f.to = C.to.value; S.limit = 100; renderRows(); } });
    C.all = h("input", { type: "checkbox", onChange: toggleAll, "aria-label": "Selecionar todas" });
    C.hide = h("input", { type: "checkbox", onChange: () => { S.f.hideDone = C.hide.checked; renderRows(); } });
    C.count = h("span", { class: "hint" });
    C.cta = h("button", { class: "btn primary", type: "button", onClick: enqueueSelection });
    C.rows = h("div", { class: "rows" });
    C.err = h("div", { class: "banner red hidden" });

    R.chan.replaceChildren(h("section", { class: "card" },
      h("div", { class: "chan-head" }, C.avatarBox, h("div", { style: "flex:1;min-width:0" }, C.title, C.sub), C.status,
        h("button", { class: "btn ghost xs", type: "button", "aria-label": "Fechar lista", onClick: closeChannel }, icon("x", "sm"))),
      C.err,
      h("div", { class: "filters" }, C.q, C.member, C.from, C.to),
      h("div", { class: "selbar" },
        h("div", { class: "row-gap", style: "gap:22px" },
          h("label", { class: "check" }, C.all, "Selecionar todas"),
          h("label", { class: "check" }, C.hide, "Ocultar já baixadas"), C.count),
        C.cta),
      C.rows));
    C.sig = ""; C.members = "";
    updateChannel(true);
  }

  const filtered = () => {
    const f = S.f, q = f.q.trim().toLowerCase();
    return S.an.entries.filter((e) =>
      (!q || `${e.title} ${e.uploader}`.toLowerCase().includes(q)) && (!f.member || e.uploader === f.member) &&
      (!f.from || (e.date && e.date >= f.from)) && (!f.to || (e.date && e.date <= f.to)) && !(f.hideDone && e.in_library))
      .sort((a, b) => (b.timestamp || 0) - (a.timestamp || 0));
  };

  function updateChannel(rowsChanged) {
    const R = current && current.R, C = R && R.C;
    if (!C || !S.an || C.id !== S.an.id) return;
    const an = S.an, name = an.channel.name || an.channel.slug;
    C.title.textContent = name;
    if (an.channel.thumbnail && !C.avatarBox.dataset.img) {
      C.avatarBox.dataset.img = "1";
      C.avatarBox.replaceChildren(h("img", { src: an.channel.thumbnail, alt: "", referrerpolicy: "no-referrer", onError: (e) => e.target.replaceWith(h("div", { class: "ph" })) }));
    }
    const dl = an.entries.filter((e) => e.downloadable).length;
    C.sub.textContent = `${plural(an.entries.length, "live encontrada", "lives encontradas")}, ${plural(dl, "pronta para baixar", "prontas para baixar")}`;
    C.status.replaceChildren(...(an.status === "running"
      ? [icon("loader-circle", "sm spin"), h("span", { text: "Buscando…" })]
      : an.status === "done" ? [icon("check", "sm"), h("span", { text: "Lista completa" })] : []));
    C.status.classList.toggle("hidden", an.status === "error" || an.status === "canceled");
    C.err.classList.toggle("hidden", an.status !== "error");
    if (an.status === "error") C.err.replaceChildren(icon("triangle-alert"), h("p", { text: an.error }));

    const members = [...new Set(an.entries.map((e) => e.uploader).filter(Boolean))].sort((a, b) => a.localeCompare(b, "pt-BR"));
    const msig = members.join("|");
    if (msig !== C.members) {
      C.members = msig; const cur = C.member.value;
      C.member.replaceChildren(h("option", { value: "", text: "Todos os perfis" }), ...members.map((m) => h("option", { value: m, text: m })));
      C.member.value = members.includes(cur) ? cur : "";
    }
    if (rowsChanged) renderRows(); else updateSelBar();
  }

  function renderRows() {
    const C = current.R.C, list = filtered(), shown = list.slice(0, S.limit), top = C.rows.scrollTop;
    C.rows.replaceChildren(...shown.map(liveRow));
    if (list.length > shown.length) C.rows.append(h("div", { class: "more" }, h("button", { class: "btn ghost sm", type: "button", onClick: () => { S.limit += 150; renderRows(); }, text: `Mostrar mais (${list.length - shown.length})` })));
    else if (!list.length) C.rows.append(h("div", { class: "empty" }, icon("search"), h("span", { text: S.an.status === "running" ? "Buscando lives…" : "Nenhuma live com esses filtros." })));
    C.rows.scrollTop = top; updateSelBar();
  }

  function liveRow(e) {
    const box = h("input", { type: "checkbox", disabled: !e.downloadable, checked: S.sel.has(e.id), "aria-label": `Selecionar ${e.title}`,
      onClick: (ev) => ev.stopPropagation(), onChange: () => { toggle(e.id, box.checked); } });
    const tags = [];
    if (e.status === "live") tags.push(h("span", { class: "chip red" }, icon("radio", "sm"), "Ao vivo"));
    if (e.status === "upcoming") tags.push(h("span", { class: "chip amber" }, icon("clock", "sm"), "Agendada"));
    if (e.status === "processing") tags.push(h("span", { class: "chip amber" }, icon("timer", "sm"), "Processando"));
    if (e.in_library) tags.push(h("span", { class: "chip green" }, icon("check", "sm"), "Já baixada"));
    if (e.availability === "subscriber_only") tags.push(h("span", { class: "chip purple" }, icon("lock", "sm"), "Membros"));
    if (e.availability === "premium_only") tags.push(h("span", { class: "chip purple" }, icon("lock", "sm"), "Pago"));
    const row = h("div", { class: `live${e.downloadable ? "" : " off"}`, onClick: () => { if (e.downloadable) { box.checked = !box.checked; toggle(e.id, box.checked); } } },
      box,
      e.thumbnail ? h("img", { class: "thumb", src: e.thumbnail, alt: "", loading: "lazy", referrerpolicy: "no-referrer", onError: (ev) => ev.target.replaceWith(h("div", { class: "thumb" })) }) : h("div", { class: "thumb" }),
      h("div", { style: "min-width:0" }, h("div", { class: "t", text: e.title, title: e.title }),
        h("div", { class: "m" }, e.uploader ? h("span", { text: e.uploader }) : null, e.date ? h("span", { text: fmtDay(e.date) }) : null, e.duration ? h("span", { text: fmtDuration(e.duration) }) : null)),
      h("div", { class: "tags" }, tags));
    return row;
  }

  function toggle(id, on) { S.touched = true; on ? S.sel.add(id) : S.sel.delete(id); updateSelBar(); }
  function toggleAll() {
    S.touched = true;
    const ids = filtered().filter((e) => e.downloadable).map((e) => e.id);
    const allOn = ids.length && ids.every((i) => S.sel.has(i));
    ids.forEach((i) => (allOn ? S.sel.delete(i) : S.sel.add(i)));
    renderRows();
  }
  function updateSelBar() {
    const C = current.R.C, ids = filtered().filter((e) => e.downloadable).map((e) => e.id), on = ids.filter((i) => S.sel.has(i)).length;
    C.all.checked = ids.length > 0 && on === ids.length; C.all.indeterminate = on > 0 && on < ids.length; C.all.disabled = !ids.length;
    C.hide.checked = S.f.hideDone;
    C.count.textContent = plural(S.sel.size, "selecionada", "selecionadas");
    C.cta.disabled = S.sel.size === 0;
    C.cta.replaceChildren(icon("download", "sm"), S.sel.size ? `Baixar ${plural(S.sel.size, "live", "lives")}` : "Baixar");
    for (const row of C.rows.querySelectorAll(".live")) { /* checkboxes já refletem o estado local */ }
  }
  async function enqueueSelection() {
    try {
      const r = await api.post("/api/downloads", { analysis_id: S.an.id, ids: [...S.sel] });
      toast(`${plural(r.added, "live adicionada", "lives adicionadas")} à fila`);
      closeChannel(); await refresh(); flash(current.R.board);
    } catch (e) { toast(e.message, true); }
  }

  // ───────────────────────── tela: Biblioteca ─────────────────────────
  function mountLibrary(root) {
    const grid = h("div", { class: "lib" });
    const q = h("input", { class: "input sm", type: "search", placeholder: "Buscar na biblioteca", "aria-label": "Buscar na biblioteca", style: "max-width:320px", onInput: () => { S.libQ = q.value; render(); } });
    const info = h("p");
    root.append(h("div", { class: "page" },
      h("div", { class: "page-head" }, h("div", {}, h("h2", { text: "Biblioteca" }), info), q), grid));
    q.value = S.libQ;

    async function load() {
      try { S.lib = (await api.get("/api/library")).items; S.libCount = S.st.library.count; render(); } catch (e) { toast(e.message, true); }
    }
    function render() {
      const term = S.libQ.trim().toLowerCase();
      const items = S.lib.filter((i) => !term || `${i.title} ${i.community} ${i.uploader}`.toLowerCase().includes(term));
      info.textContent = S.lib.length ? `${plural(S.lib.length, "live baixada", "lives baixadas")}, ${fmtBytes(S.lib.reduce((a, i) => a + (i.size || 0), 0))} no total.` : "";
      info.className = "sub";
      grid.replaceChildren(...(items.length ? items.map(libCard) : [h("div", { class: "card empty", style: "grid-column:1/-1;padding:48px" }, icon("film", "lg"),
        h("b", { text: S.lib.length ? "Nada encontrado" : "Sua biblioteca está vazia" }),
        h("span", { text: S.lib.length ? "Tente outro termo de busca." : "Baixe uma live na aba Baixar e ela aparece aqui." }))]));
    }
    function libCard(i) {
      const poster = h("div", { class: "poster" }, i.has_thumb ? h("img", { src: `/api/library/${i.id}/thumb?t=${encodeURIComponent(TOKEN || "")}`, alt: "", loading: "lazy" }) : icon("film", "lg"),
        i.duration ? h("span", { class: "dur", text: fmtDuration(i.duration) }) : null);
      const act = async (target) => { await openPath({ target, id: i.id }); };
      return h("article", { class: "card libcard" }, poster, h("h4", { text: i.title, title: i.title }),
        h("div", { class: "meta" },
          h("span", { class: "chip purple" }, h("span", { text: (i.uploader || i.community || "Weverse").trim() })),
          i.timestamp ? h("span", { class: "chip", text: fmtTs(i.timestamp) }) : null,
          i.height ? h("span", { class: "chip", text: `${i.height}p` }) : null,
          i.size ? h("span", { class: "chip", text: fmtBytes(i.size) }) : null,
          i.subtitles ? h("span", { class: "chip blue" }, icon("captions", "sm"), String(i.subtitles)) : null,
          !i.exists ? h("span", { class: "chip red" }, "Arquivo não encontrado") : null),
        h("div", { class: "acts" },
          h("button", { class: "btn soft xs", type: "button", disabled: !i.exists, onClick: () => act("library") }, icon("folder-open", "sm"), "Abrir pasta"),
          h("button", { class: "btn ghost xs", type: "button", disabled: !i.exists, onClick: () => act("library-video") }, icon("play", "sm"), "Reproduzir"),
          h("button", { class: "btn ghost xs", type: "button", style: "margin-left:auto", title: "Remove só do histórico; os arquivos continuam na pasta", "aria-label": "Remover do histórico",
            onClick: async () => { await api.post(`/api/library/${i.id}/remove`); toast("Removida do histórico. Os arquivos continuam na pasta."); load(); } }, icon("trash-2", "sm"))));
    }
    load();
    return { update() { if (S.st.library.count !== S.libCount) load(); } };
  }

  // ───────────────────────── tela: Conta ─────────────────────────
  function mountAccount(root) {
    const M = {};
    let result = null;
    const resultBox = h("div");
    const methodCard = (key, ic, title, text, body) => {
      const el = h("div", { class: "method", role: "radio", tabindex: 0, "aria-checked": "false", dataset: { key },
        onClick: (e) => { if (!e.target.closest(".body")) save({ auth: { method: key } }); },
        onKeydown: (e) => { if ((e.key === "Enter" || e.key === " ") && e.target === el) { e.preventDefault(); save({ auth: { method: key } }); } } },
        h("div", { class: "mh" }, icon(ic), title), h("p", { text }), body ? h("div", { class: "body" }, body) : null);
      M[key] = el; return el;
    };
    M.browser = h("select", { class: "select sm", "aria-label": "Navegador", onChange: () => save({ auth: { browser: M.browser.value } }) },
      ["firefox", "chrome", "edge", "brave", "chromium", "opera", "vivaldi", "safari"].map((b) => h("option", { value: b, text: { firefox: "Firefox", chrome: "Google Chrome", edge: "Microsoft Edge", brave: "Brave", chromium: "Chromium", opera: "Opera", vivaldi: "Vivaldi", safari: "Safari" }[b] })));
    M.profile = h("input", { class: "input sm", placeholder: "Perfil do navegador (opcional)", "aria-label": "Perfil do navegador", onChange: () => save({ auth: { profile: M.profile.value } }) });
    M.file = h("input", { class: "input sm", placeholder: "Caminho do cookies.txt", "aria-label": "Arquivo cookies.txt", onChange: () => save({ auth: { cookie_file: M.file.value } }) });
    M.token = h("input", { class: "input sm", type: "password", autocomplete: "off", "aria-label": "Token de atualização", placeholder: "Cole o valor do cookie we2_refresh_token",
      onChange: () => { if (M.token.value.trim()) { save({ auth: { refresh_token: M.token.value.trim() } }); M.token.value = ""; toast("Token salvo neste computador"); } } });
    M.rmToken = h("button", { class: "btn ghost xs", type: "button", onClick: () => save({ auth: { refresh_token: "" } }), text: "Remover token salvo" });

    const test = h("button", { class: "btn primary", type: "button", onClick: async () => {
      test.disabled = true; test.replaceChildren(icon("loader-circle", "sm spin"), "Testando…");
      try { result = await api.post("/api/login/check"); } catch (e) { result = { ok: false, message: e.message }; }
      test.disabled = false; test.replaceChildren(icon("shield-check", "sm"), "Testar conexão"); drawResult();
    } }, icon("shield-check", "sm"), "Testar conexão");
    function drawResult() {
      resultBox.replaceChildren(result ? h("div", { class: `banner ${result.ok ? "blue" : "red"}` }, icon(result.ok ? "circle-check" : "triangle-alert"), h("p", { text: result.message })) : "");
    }

    root.append(h("div", { class: "page narrow" },
      h("div", { class: "page-head" }, h("div", {}, h("h2", { text: "Conta Weverse" }), h("p", { text: "O Weverse pede login para a maior parte dos VODs. A sua senha nunca passa pelo Downverse." }))),
      h("section", { class: "card" },
        h("div", { class: "card-head" }, h("div", {}, h("h3", { text: "Como conectar" }), h("p", { class: "sub", text: "Use a sessão que você já tem no navegador." }))),
        h("ol", { class: "steps" },
          h("li", {}, h("span", { text: "Entre na sua conta em weverse.io no navegador (vale login com Google, Apple, e-mail…)." })),
          h("li", {}, h("span", { text: "Escolha abaixo o mesmo navegador e deixe o método “Cookies do navegador” marcado." })),
          h("li", {}, h("span", { text: "Clique em Testar conexão e volte para a aba Baixar.", })))),
      h("section", { class: "card" },
        h("div", { class: "card-head" }, h("div", {}, h("h3", { text: "Método de login" }), h("p", { class: "sub", text: "O conteúdo exclusivo para membros só baixa se a sua conta tiver acesso a ele." }))),
        h("div", { class: "methods", role: "radiogroup", "aria-label": "Método de login" },
          methodCard("browser", "cookie", "Cookies do navegador", "Recomendado. Lê só os cookies do weverse.io. No Chrome e no Edge recentes isso pode falhar no Windows; nesse caso use o Firefox.", h("div", { class: "field" }, M.browser, M.profile)),
          methodCard("file", "file-text", "Arquivo cookies.txt", "Exporte os cookies do weverse.io com uma extensão do navegador e indique o arquivo.", M.file),
          methodCard("token", "key-round", "Token de atualização", "Avançado. No navegador: Ferramentas do desenvolvedor, Armazenamento, Cookies, weverse.io, valor de we2_refresh_token.", h("div", { class: "field" }, M.token, M.rmToken)),
          methodCard("none", "users", "Sem conta", "Só o que o Weverse libera sem login (quase nunca inclui VODs).")),
        h("div", { class: "row-gap", style: "margin-top:18px" }, test), resultBox)));

    function update() {
      const a = settings().auth;
      for (const key of ["browser", "file", "token", "none"]) M[key].setAttribute("aria-checked", String(a.method === key));
      setValue(M.browser, a.browser); setValue(M.profile, a.profile); setValue(M.file, a.cookie_file);
      M.token.placeholder = a.has_token ? "Token salvo. Cole outro para substituir" : "Cole o valor do cookie we2_refresh_token";
      M.rmToken.classList.toggle("hidden", !a.has_token);
    }
    return { update };
  }

  // ───────────────────────── tela: Configurações ─────────────────────────
  function mountSettings(root) {
    const C = {};
    const row = (title, desc, ctl, wide) => h("div", { class: "setrow" }, h("div", {}, h("div", { class: "t", text: title }), desc ? h("div", { class: "d", text: desc }) : null), h("div", { class: `ctl${wide ? " wide" : ""}` }, ctl));
    const sel = (key, options, cast = (v) => v) => { const el = h("select", { class: "select sm", onChange: () => save({ [key]: cast(el.value) }) }, options.map(([v, t]) => h("option", { value: v, text: t }))); C[key] = el; return el; };
    const sw = (key) => { const input = h("input", { type: "checkbox", onChange: () => save({ [key]: input.checked }), "aria-label": key }); C[key] = input; return h("span", { class: "switch" }, input, h("i")); };

    C.output_dir = h("input", { class: "input sm", spellcheck: false, "aria-label": "Pasta de destino", onChange: () => save({ output_dir: C.output_dir.value.trim() }) });
    C.pick = h("button", { class: "btn soft sm", type: "button", onClick: async () => { try { const r = await api.post("/api/pick-folder"); S.st.settings = r.settings; S.st.output_dir = r.output_dir; current.update(); } catch (e) { toast(e.message, true); } } }, icon("folder-open", "sm"), "Escolher");
    C.reset = h("button", { class: "btn ghost sm", type: "button", onClick: () => save({ output_dir: "" }), text: "Usar pasta Vídeos" });
    C.subdir = h("input", { class: "input sm", "aria-label": "Nome da pasta de legendas", onChange: () => save({ subtitles_dir_name: C.subdir.value }) });
    C.tree = h("pre", { class: "tree" });
    const langs = langChips();

    root.append(h("div", { class: "page" },
      h("div", { class: "page-head" }, h("div", {}, h("h2", { text: "Configurações" }), h("p", { text: "As alterações são salvas na hora." }))),
      h("div", { class: "settings" },
        h("div", { class: "col" },
          h("section", { class: "card" }, h("div", { class: "card-head" }, h("div", {}, h("h3", { text: "Destino" }), h("p", { class: "sub", text: "Onde a pasta Weverse é criada." }))),
            h("div", { class: "field" }, C.output_dir), h("div", { class: "row-gap", style: "margin:10px 0 16px" }, C.pick, C.reset),
            C.tree),
          h("section", { class: "card" }, h("div", { class: "card-head" }, h("div", {}, h("h3", { text: "Estrutura das pastas" }))),
            row("Pasta do membro", "Automática cria a pasta do membro só quando ele não é o próprio canal. Em artista solo, escolha “Nunca”.", sel("artist_mode", [["auto", "Automática"], ["solo", "Nunca (artista solo)"]]), true),
            row("Fuso da data da live", "Define em qual dia a live cai quando ela passa da meia-noite.", sel("date_timezone", [["local", "Deste computador"], ["utc", "UTC"], ["kst", "Seul (KST)"]]), true),
            row("Nome da pasta de legendas", null, C.subdir, true))),
        h("div", { class: "col" },
          h("section", { class: "card" }, h("div", { class: "card-head" }, h("div", {}, h("h3", { text: "Legendas e thumbnail" }))),
            row("Baixar legendas", null, sw("subtitles")),
            row("Formato", "SRT abre em qualquer editor (DaVinci Resolve, Premiere…). VTT é o original do Weverse.", sel("subtitle_format", [["srt", "SRT"], ["vtt", "VTT"]])),
            row("Legendas de fãs", "Inclui traduções feitas por fãs, quando existirem.", sw("fan_subtitles")),
            h("div", { class: "setrow" }, h("div", {}, h("div", { class: "t", text: "Idiomas" }), h("div", { class: "d", text: "Sem seleção, baixa todos os disponíveis." })), h("div", { style: "max-width:300px" }, langs.el)),
            row("Baixar thumbnail", "Salva a imagem da live em JPG, ao lado do vídeo.", sw("thumbnail"))),
          h("section", { class: "card" }, h("div", { class: "card-head" }, h("div", {}, h("h3", { text: "Downloads" }))),
            row("Qualidade padrão", null, sel("quality", QUALITIES)),
            row("Downloads ao mesmo tempo", "Mais de um pode ser mais rápido, mas o Weverse pode limitar.", sel("concurrent_downloads", [["1", "1"], ["2", "2"], ["3", "3"], ["4", "4"]], Number)),
            row("Substituir arquivos existentes", "Baixa de novo mesmo que a live já esteja na biblioteca.", sw("overwrite"))),
          h("section", { class: "card" }, h("div", { class: "card-head" }, h("div", {}, h("h3", { text: "Sobre" }))),
            C.about = h("p", { class: "hint" }))))));

    function drawTree() {
      const cfg = settings(), t = "Título da live", sd = cfg.subtitles_dir_name || "Legendas";
      const L = (indent, text, note) => [h("span", { text: indent + text }), ...(note ? [h("i", { text: `   ${note}` })] : []), "\n"];
      C.tree.replaceChildren(...[
        h("b", { text: S.st.output_dir }), "\n",
        L("└─ ", "Grupo ou artista solo", ""), L("   ├─ ", "2026-03-10", "live da conta oficial"),
        L("   └─ ", "Membro", "só em grupos"), L("      └─ ", "2026-03-15", "data da live"),
        L("         ├─ ", `${t}.mp4`), L("         ├─ ", `${t}.jpg`), L("         └─ ", sd),
        L("            └─ ", `${t}.pt_BR.${cfg.subtitle_format}`)].flat());
    }
    function update() {
      const cfg = settings(), st = S.st;
      setValue(C.output_dir, cfg.output_dir); C.output_dir.placeholder = st.default_output_dir;
      C.pick.classList.toggle("hidden", !st.can_pick_folder); C.reset.classList.toggle("hidden", !cfg.output_dir);
      setValue(C.subdir, cfg.subtitles_dir_name);
      for (const k of ["artist_mode", "date_timezone", "subtitle_format", "quality"]) setValue(C[k], cfg[k]);
      setValue(C.concurrent_downloads, String(cfg.concurrent_downloads));
      for (const k of ["subtitles", "fan_subtitles", "thumbnail", "overwrite"]) setChecked(C[k], cfg[k]);
      langs.update(); drawTree();
      C.about.textContent = `Downverse ${st.version} usando yt-dlp ${st.ytdlp}. FFmpeg: ${st.ffmpeg ? "encontrado" : "não encontrado"}. Projeto independente, sem vínculo com a Weverse Company. Use só para uso pessoal e respeite os termos do Weverse.`;
    }
    return { update };
  }

  // ───────────────────────── casca: navegação e laço principal ─────────────────────────
  const VIEWS = {
    download: { title: "Baixar", icon: "arrow-down-to-line", mount: mountDownload },
    library: { title: "Biblioteca", icon: "library-big", mount: mountLibrary },
    account: { title: "Conta Weverse", icon: "circle-user-round", mount: mountAccount },
    settings: { title: "Configurações", icon: "settings", mount: mountSettings },
  };
  let current = null;

  function buildNav() {
    const nav = $("#nav");
    nav.replaceChildren(h("div", { class: "nav-title", text: "Menu" }), ...Object.entries(VIEWS).map(([key, v]) =>
      h("button", { type: "button", dataset: { view: key }, title: v.title, onClick: () => go(key) }, h("span", { class: "nav-ico" }, icon(v.icon)), h("span", { text: v.title }))));
  }
  function go(view) {
    S.view = view;
    const main = $("#main"); main.replaceChildren();
    const mounted = VIEWS[view].mount(main);
    current = mounted;
    for (const b of $("#nav").querySelectorAll("button")) b.toggleAttribute("aria-current", b.dataset.view === view), b.dataset.view === view ? b.setAttribute("aria-current", "page") : b.removeAttribute("aria-current");
    main.scrollTop = 0;
    if (S.st) current.update();
  }

  function renderChrome() {
    const st = S.st, c = st.queue.counts;
    $("#pstats").replaceChildren(
      ...[[st.library.count, "Baixados"], [c.queued + c.downloading, "Na fila"], [c.error, "Falhas"]].map(([n, l]) => h("div", {}, h("b", { text: String(n) }), h("span", { text: l }))));
    $("#versions").textContent = `v${st.version} · yt-dlp ${st.ytdlp}`;
  }

  async function refresh() {
    try {
      S.st = await api.get("/api/state");
      if (S.err) { S.err = false; toast("Conexão com o Downverse restabelecida"); }
    } catch (e) {
      if (!S.err) toast("Perdi a conexão com o Downverse. Se a janela foi reaberta, recarregue.", true);
      S.err = true; return;
    }
    applyTheme(); renderChrome();
    if (current) current.update();
  }

  async function loop() {
    for (;;) {
      await refresh();
      const q = S.st && S.st.queue.counts;
      await sleep(q && q.queued + q.downloading > 0 ? 900 : 2500);
    }
  }

  async function boot() {
    buildNav();
    $("#theme-toggle").addEventListener("change", (e) => save({ theme: e.target.checked ? "dark" : "light" }));
    await refresh();
    if (!S.st) { $("#main").replaceChildren(h("div", { class: "page" }, h("div", { class: "banner red" }, icon("triangle-alert"), h("p", { text: "Não consegui falar com o Downverse. Feche e abra o aplicativo de novo." })))); return; }
    go("download");
    loop();
  }
  boot();
})();
