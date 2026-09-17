/* MT5 Web Console — core: state, API, live stream, helpers, SVG chart. */
(function () {
  "use strict";
  const UI = (window.UI = window.UI || {});

  // ------------------------------------------------------------------ state
  UI.state = {
    token: sessionStorage.getItem("m5tok") || "",
    boot: window.__BOOT__ || {},
    status: null,
    symbols: [],
    algoList: [],
    view: "overview",
    account: null,
    tradeState: { positions: [], orders: [], account: {}, floating_profit: 0 },
    prices: {},
    prevPrices: {},
    ws: null,
    wsRetry: 0,
    selected: null,
    timeframe: "M5",
    bars: 200,
    chart: { rows: [], meta: {}, loading: false, error: null, marker: null },
    algos: {},
    activeAlgo: null,
    algoLog: [],
    backtest: null,
    bridge: null,
    audit: [],
    logFeed: [],
    tickers: {},
  };

  // ------------------------------------------------------------------ utils
  UI.esc = function (s) {
    return String(s === null || s === undefined ? "" : s).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  };
  UI.num = function (v, digits) {
    if (v === null || v === undefined || v === "" || isNaN(v)) return "—";
    return Number(v).toLocaleString(undefined, { minimumFractionDigits: digits === undefined ? 2 : digits, maximumFractionDigits: digits === undefined ? 2 : digits });
  };
  UI.money = function (v, currency) {
    if (v === null || v === undefined || isNaN(v)) return "—";
    const sign = v < 0 ? "-" : "";
    return sign + "$" + Math.abs(Number(v)).toFixed(2) + (currency ? "" : "");
  };
  UI.cls = function (v) { return v > 0 ? "pos" : v < 0 ? "neg" : "flat"; };
  UI.signed = function (v, digits) { return (v > 0 ? "+" : "") + UI.num(v, digits); };
  UI.hhmmss = function (ts) {
    if (!ts) return "--:--:--";
    const d = new Date(ts * 1000);
    return d.toTimeString().slice(0, 8);
  };
  UI.dt = function (ts) {
    if (!ts) return "—";
    const d = new Date(ts * 1000);
    return d.toISOString().slice(0, 16).replace("T", " ");
  };
  UI.ago = function (ts) {
    if (!ts) return "never";
    const s = Math.max(0, Math.floor(Date.now() / 1000 - ts));
    if (s < 60) return s + "s ago";
    if (s < 3600) return Math.floor(s / 60) + "m ago";
    if (s < 86400) return Math.floor(s / 3600) + "h ago";
    return Math.floor(s / 86400) + "d ago";
  };
  UI.copy = function (text, label) {
    navigator.clipboard.writeText(text).then(function () { UI.toast((label || "copied") + " to clipboard", "ok"); },
      function () { UI.toast("clipboard blocked - select and copy manually", "warn"); });
  };
  UI.debounce = function (fn, ms) {
    let t; return function () { const a = arguments, s = this; clearTimeout(t); t = setTimeout(function () { fn.apply(s, a); }, ms || 250); };
  };

  // ------------------------------------------------------------------ toast
  UI.toast = function (msg, kind, ms) {
    const root = document.getElementById("toasts");
    const el = document.createElement("div");
    el.className = "toast " + (kind || "ok");
    el.textContent = msg;
    root.appendChild(el);
    setTimeout(function () { el.style.opacity = "0"; el.style.transition = "opacity .3s"; setTimeout(function () { el.remove(); }, 320); }, ms || 4200);
  };

  // ------------------------------------------------------------------ modal
  UI.modal = function (title, bodyHtml, opts) {
    opts = opts || {};
    const root = document.getElementById("modal-root");
    root.innerHTML =
      '<div class="modal" role="dialog" aria-label="' + UI.esc(title) + '">' +
      "<h3>" + UI.esc(title) + "</h3>" +
      '<div class="modal-body">' + bodyHtml + "</div>" +
      '<div class="modal-actions">' +
      (opts.actions || '<button class="btn ghost" data-action="close-modal">Close</button>') +
      "</div></div>";
    root.onclick = function (e) { if (e.target === root) UI.closeModal(); };
    if (opts.onMount) opts.onMount(root.querySelector(".modal"));
    return root.querySelector(".modal");
  };
  UI.closeModal = function () { document.getElementById("modal-root").innerHTML = ""; };

  // ------------------------------------------------------------------ api
  UI.api = async function (path, opts) {
    opts = opts || {};
    const headers = Object.assign({}, opts.headers || {});
    if (UI.state.token) headers["Authorization"] = "Bearer " + UI.state.token;
    if (opts.body !== undefined && typeof opts.body !== "string") {
      headers["Content-Type"] = "application/json";
      opts.body = JSON.stringify(opts.body);
    }
    const res = await fetch("/api" + path, Object.assign({ method: opts.method || "GET" }, opts, { headers }));
    if (res.status === 401) { UI.setAuthed(false); throw new Error("session expired - sign in again"); }
    const text = await res.text();
    let data = null;
    try { data = text ? JSON.parse(text) : null; } catch (e) { data = { detail: text.slice(0, 400) }; }
    if (!res.ok) {
      const err = new Error((data && (data.detail || data.message)) || res.statusText + " " + res.status);
      err.payload = data; err.status = res.status;
      throw err;
    }
    return data;
  };
  UI.get = function (p) { return UI.api(p); };
  UI.post = function (p, body) { return UI.api(p, { method: "POST", body: body === undefined ? null : body }); };
  UI.patch = function (p, body) { return UI.api(p, { method: "PATCH", body: body || {} }); };
  UI.put = function (p, body) { return UI.api(p, { method: "PUT", body: body || {} }); };
  UI.del = function (p) { return UI.api(p, { method: "DELETE" }); };

  // ------------------------------------------------------------------ stream
  UI.connectStream = function () {
    const st = UI.state;
    if (!st.token) return;
    if (st.ws) { try { st.ws.close(); } catch (e) {} }
    const proto = location.protocol === "https:" ? "wss" : "ws";
    const syms = st.symbols.map(function (s) { return s.name; }).join(",");
    const ws = new WebSocket(proto + "://" + location.host + "/ws/stream?token=" + encodeURIComponent(st.token) + (syms ? "&symbols=" + encodeURIComponent(syms) : ""));
    st.ws = ws;
    ws.onopen = function () { st.wsRetry = 0; UI.setStatus("stream", "live"); };
    ws.onmessage = function (ev) {
      let msg; try { msg = JSON.parse(ev.data); } catch (e) { return; }
      if (msg.t === "hello") {
        if (msg.prices) Object.assign(st.prices, msg.prices);
        if (msg.state) UI.applyState(msg.state);
        if (msg.algos) UI.setAlgos(msg.algos);
        UI.renderTicker(); UI.renderIfView(["overview", "markets", "positions"]);
      } else if (msg.t === "tick") {
        st.prevPrices[msg.data.symbol] = st.prices[msg.data.symbol];
        st.prices[msg.data.symbol] = msg.data;
        UI.renderTicker();
        if (st.view === "markets" && msg.data.symbol === st.selected) UI.patchChartLastTick(msg.data);
      } else if (msg.t === "log") {
        UI.onLogEvent(msg.data);
      } else if (msg.t === "event") {
        UI.onStreamEvent(msg.data);
      }
    };
    ws.onclose = function () {
      UI.setStatus("stream", "down");
      st.wsRetry = Math.min((st.wsRetry || 0) + 1, 6);
      setTimeout(UI.connectStream, 800 * st.wsRetry);
    };
    ws.onerror = function () { try { ws.close(); } catch (e) {} };
  };

  UI.onLogEvent = function (row) {
    if (!row) return;
    if (row.type === "algo_log") {
      const st = UI.state;
      if (row.algo === st.activeAlgo) { st.algoLog.push(row); if (st.algoLog.length > 400) st.algoLog.shift(); UI.renderAlgoLog(); }
      if (row.algo) UI.bumpAlgoBadge(row.algo);
    } else if (row.type === "mt5_log") {
      const st = UI.state;
      st.logFeed = (row.lines || row.lines === undefined ? row.lines : []).concat(st.logFeed).slice(0, 300);
      if (row.line) st.logFeed.unshift({ file: row.file, line: row.line, at: Date.now() / 1000 });
      st.logFeed = st.logFeed.slice(0, 300);
      if (st.view === "bridge") UI.renderMt5Log();
    } else if (row.type === "info") {
      UI.toast(row.text, "warn", 2600);
    }
  };

  UI.onStreamEvent = function (row) {
    if (!row) return;
    if (row.type === "order" || row.type === "close") {
      UI.toast((row.type === "order" ? "order sent: " : "position closed: ") + (row.symbol || row.ticket || ""), "ok", 3000);
      UI.refreshTradeState();
    } else if (row.type === "algo") {
      UI.setAlgoRuntime(row.algo, row);
    } else if (row.type === "bar") {
      const st = UI.state;
      if (st.view === "markets" && row.symbol === st.selected && row.timeframe === st.timeframe) UI.loadChart(true);
    } else if (row.type === "mt5_trade") {
      UI.refreshTradeState();
    }
  };

  // ------------------------------------------------------------------ status pills
  UI.setStatus = function (what, kind) {
    const map = { bridge: document.getElementById("pill-bridge"), account: document.getElementById("pill-account"), stream: null };
    const el = map[what];
    if (!el) return;
    el.dataset.kind = kind;
    el.classList.remove("ok", "bad", "warn");
    el.classList.add(kind === "up" || kind === "live" ? "ok" : kind === "down" ? "bad" : "warn");
  };

  UI.applyState = function (state) {
    if (!state) return;
    const st = UI.state;
    st.status = state;
    if (state.account) st.account = state.account;
    st.symbols = (state.symbols || []).map(function (name) {
      const existing = (st.symbols || []).find(function (s) { return s.name === name; }) || {};
      return Object.assign({ name: name }, existing);
    });
    const bridgeEl = document.getElementById("pill-bridge");
    if (bridgeEl) {
      const n = (state.agents || []).length;
      bridgeEl.textContent = "bridge: " + (n ? n + " agent" + (n > 1 ? "s" : "") + " online" : "offline");
      UI.setStatus("bridge", n ? "up" : "down");
    }
    const acctEl = document.getElementById("pill-account");
    if (acctEl) {
      const a = state.account;
      const txt = !a ? "no account" : a.status === "connected" ? a.login + " @ " + a.server : a.status;
      acctEl.textContent = "account: " + txt;
      UI.setStatus("account", !a ? "warn" : a.status === "connected" ? "up" : "down");
    }
    const ks = document.getElementById("kill-switch");
    if (ks) ks.checked = !!state.kill_switch;
    const sub = document.getElementById("brand-sub");
    if (sub) sub.textContent = (state.transport === "agent" ? "agent transport" : state.transport === "local" ? "local MT5" : "no terminal") + " · v" + (state.version || "");
    UI.renderTopAccount();
  };

  UI.renderTopAccount = function () {
    const a = (UI.state.tradeState && UI.state.tradeState.account) || {};
    const cur = a.currency || "";
    document.getElementById("top-balance").textContent = UI.num(a.balance) + (cur ? " " + cur : "");
    document.getElementById("top-equity").textContent = UI.num(a.equity) + (cur ? " " + cur : "");
    const fl = UI.state.tradeState.floating_profit;
    const el = document.getElementById("top-fl");
    el.textContent = UI.signed(fl, 2);
    el.className = UI.cls(fl);
  };

  UI.refreshTradeState = async function (quiet) {
    if (!UI.state.account) return;
    try {
      const s = await UI.get("/trade/state");
      UI.state.tradeState = s;
      UI.renderTopAccount();
      UI.renderIfView(["overview", "positions", "markets", "trade"]);
    } catch (e) {
      if (!quiet) UI.state.tradeStateError = e.message;
      UI.renderIfView(["overview", "positions"]);
    }
  };

  UI.refreshStatus = async function () {
    try {
      const s = await UI.get("/state");
      UI.applyState(s);
      UI.setAlgos(s.algos || []);
      if (UI.state.symbols.length) UI.refreshQuotes();
      return s;
    } catch (e) {
      UI.toast("status: " + e.message, "err");
    }
  };

  UI.refreshQuotes = async function () {
    try {
      const r = await UI.get("/market/quote");
      const prices = Object.assign({}, r.cache || {}, r.prices || {});
      UI.state.prevPrices = UI.state.prices;
      UI.state.prices = prices;
      UI.renderTicker();
      UI.renderIfView(["overview", "markets"]);
    } catch (e) { /* offline is normal before the agent connects */ }
  };

  // ------------------------------------------------------------------ ticker
  UI.renderTicker = function () {
    const el = document.getElementById("ticker");
    if (!el) return;
    const st = UI.state;
    const names = st.symbols.map(function (s) { return s.name; });
    if (!names.length) { el.innerHTML = "<em>no symbols yet — add them in Settings</em>"; return; }
    el.innerHTML = names.map(function (n) {
      const p = st.prices[n]; const prev = st.prevPrices[n];
      if (!p) return '<span class="q">' + n + " <b class='muted'>—</b></span>";
      const dir = prev && prev.bid ? (p.bid > prev.bid ? "up" : p.bid < prev.bid ? "down" : "") : "";
      const digits = (st.symbols.find(function (s) { return s.name === n; }) || {}).digits || 5;
      return '<span class="q">' + n + ' <b class="' + dir + '">' + p.bid.toFixed(digits) + "</b>" +
        (p.ask ? '<span class="muted tiny">' + (p.ask - p.bid).toFixed(digits) + "</span>" : "") + "</span>";
    }).join("");
  };

  // ------------------------------------------------------------------ chart
  UI.candleChart = function (rows, opts) {
    opts = opts || {};
    const W = opts.width || 1000, H = opts.height || 320;
    const padL = 8, padR = 62, padT = 14, padB = opts.volume === false ? 10 : 56;
    if (!rows || !rows.length) return '<div class="empty">no candles yet — the terminal needs to send history</div>';
    const n = rows.length;
    const highs = rows.map(function (r) { return r.high; });
    const lows = rows.map(function (r) { return r.low; });
    let hi = Math.max.apply(null, highs), lo = Math.min.apply(null, lows);
    (opts.levels || []).forEach(function (lv) { if (lv.price) { hi = Math.max(hi, lv.price); lo = Math.min(lo, lv.price); } });
    const span = hi - lo || Math.max(hi * 0.001, 1e-5);
    hi += span * 0.06; lo -= span * 0.06;
    const plotW = W - padL - padR, plotH = H - padT - padB;
    const x = function (i) { return padL + (i + 0.5) * (plotW / n); };
    const y = function (p) { return padT + (hi - p) / (hi - lo) * plotH; };
    const cw = Math.max(1.2, Math.min(11, plotW / n * 0.68));
    const digits = opts.digits || 5;

    const parts = ['<svg viewBox="0 0 ' + W + " " + H + '" preserveAspectRatio="none" class="chart-svg">'];
    // horizontal grid + price axis
    for (let g = 0; g <= 4; g++) {
      const price = lo + (hi - lo) * (g / 4);
      const yy = y(price);
      parts.push('<line class="grid-line" x1="' + padL + '" x2="' + (W - padR) + '" y1="' + yy + '" y2="' + yy + '"/>');
      parts.push('<text class="axis-txt" x="' + (W - padR + 5) + '" y="' + (yy + 3.5) + '">' + price.toFixed(digits) + "</text>");
    }
    // time axis
    const ticks = 5;
    for (let g = 0; g <= ticks; g++) {
      const idx = Math.min(n - 1, Math.round((n - 1) * (g / ticks)));
      const xx = x(idx);
      parts.push('<line class="grid-line" x1="' + xx + '" x2="' + xx + '" y1="' + padT + '" y2="' + (padT + plotH) + '"/>');
      const d = new Date(rows[idx].time * 1000);
      const label = digits > 3 ? d.toTimeString().slice(0, 5) : d.toISOString().slice(5, 10);
      parts.push('<text class="axis-txt" x="' + xx + '" y="' + (H - padB + 34) + '" text-anchor="middle">' + label + "</text>");
    }
    // candles
    rows.forEach(function (r, i) {
      const up = r.close >= r.open;
      const cx = x(i);
      parts.push('<line x1="' + cx + '" x2="' + cx + '" y1="' + y(r.high) + '" y2="' + y(r.low) + '" stroke="' + (up ? "#37e6a4" : "#ff5d6c") + '" stroke-width="1"/>');
      const yo = y(r.open), yc = y(r.close);
      parts.push('<rect class="' + (up ? "candle-up" : "candle-down") + '" x="' + (cx - cw / 2) + '" y="' + Math.min(yo, yc) + '" width="' + cw + '" height="' + Math.max(1, Math.abs(yc - yo)) + '" rx="0.6"/>');
    });
    // optional line series
    (opts.series || []).forEach(function (s) {
      if (!s.values) return;
      const dPath = s.values.map(function (v, i) { return (i ? "L" : "M") + x(i).toFixed(1) + " " + y(v).toFixed(1); }).join(" ");
      parts.push('<path d="' + dPath + '" fill="none" stroke="' + (s.color || "#6ba8ff") + '" stroke-width="' + (s.width || 1.4) + '" opacity="' + (s.opacity || 0.95) + '"/>');
    });
    // levels (SL/TP/entries)
    (opts.levels || []).forEach(function (lv) {
      if (!lv.price) return;
      const yy = y(lv.price);
      parts.push('<line class="level-line" x1="' + padL + '" x2="' + (W - padR) + '" y1="' + yy + '" y2="' + yy + '" stroke="' + (lv.color || "#6ba8ff") + '"/>');
      parts.push('<text class="axis-txt" x="' + (padL + 4) + '" y="' + (yy - 4) + '" fill="' + (lv.color || "#6ba8ff") + '">' + UI.esc(lv.label || "") + " " + lv.price.toFixed(digits) + "</text>");
    });
    // markers
    (opts.markers || []).forEach(function (m) {
      if (m.index === undefined || m.index < 0 || m.index >= n) return;
      const cx = x(m.index), cy = y(m.price || rows[m.index].close);
      const color = m.color || (m.dir === "buy" ? "#37e6a4" : "#ff5d6c");
      parts.push(m.dir === "buy"
        ? '<polygon points="' + (cx - 5) + "," + (cy + 7) + " " + (cx + 5) + "," + (cy + 7) + " " + cx + "," + (cy - 1) + '" fill="' + color + '"/>'
        : '<polygon points="' + (cx - 5) + "," + (cy - 7) + " " + (cx + 5) + "," + (cy - 7) + " " + cx + "," + (cy + 1) + '" fill="' + color + '"/>');
    });
    // volume pane
    if (opts.volume !== false) {
      const vh = 34;
      const maxVol = Math.max.apply(null, rows.map(function (r) { return r.tick_volume || 1; }));
      rows.forEach(function (r, i) {
        const h = Math.max(1, (r.tick_volume || 0) / maxVol * vh);
        parts.push('<rect x="' + (x(i) - cw / 2) + '" y="' + (H - padB + 42 - h) + '" width="' + cw + '" height="' + h + '" fill="' + (r.close >= r.open ? "#143a2e" : "#3a1420") + '"/>');
      });
    }
    parts.push("</svg>");
    return '<div class="chart-shell">' + parts.join("") +
      '<div class="chart-hud"><span class="t">' + UI.esc(opts.symbol || "") + " " + UI.esc(opts.timeframe || "") + "</span>" +
      "<span>O <b>" + rows[n - 1].open.toFixed(digits) + "</b></span><span>H <b>" + rows[n - 1].high.toFixed(digits) + "</b></span>" +
      "<span>L <b>" + rows[n - 1].low.toFixed(digits) + "</b></span><span>C <b>" + rows[n - 1].close.toFixed(digits) + "</b></span></div></div>";
  };

  UI.sparkline = function (values, opts) {
    opts = opts || {};
    if (!values || values.length < 2) return '<div class="empty tiny">no data</div>';
    const W = opts.width || 320, H = opts.height || 60;
    const hi = Math.max.apply(null, values), lo = Math.min.apply(null, values);
    const span = hi - lo || 1;
    const pts = values.map(function (v, i) { return (i / (values.length - 1)) * W + " " + (H - ((v - lo) / span) * (H - 6) - 3); });
    const color = values[values.length - 1] >= values[0] ? "#37e6a4" : "#ff5d6c";
    return '<svg viewBox="0 0 ' + W + " " + H + '" preserveAspectRatio="none" style="width:100%;height:' + H + 'px">' +
      '<polyline points="' + pts.join(" ") + '" fill="none" stroke="' + color + '" stroke-width="1.6"/>' +
      '<polyline points="0,' + H + " " + pts.join(" ") + " " + W + "," + H + '" fill="' + color + '" opacity="0.08" stroke="none"/></svg>';
  };

  // ------------------------------------------------------------------ router
  UI.go = function (view) {
    if (location.hash !== "#/" + view) location.hash = "#/" + view;
    UI.state.view = view;
    document.querySelectorAll(".nav-item").forEach(function (a) {
      a.classList.toggle("active", a.dataset.view === view);
    });
    UI.render();
  };
  UI.render = function () {
    const host = document.getElementById("view");
    const fn = UI.views && UI.views[UI.state.view];
    host.innerHTML = '<div class="card"><div class="row"><span class="spinner"></span><span class="muted">loading…</span></div></div>';
    Promise.resolve(fn ? fn(host) : null).catch(function (e) {
      host.innerHTML = '<div class="card"><h3>error</h3><div class="warnbox">' + UI.esc(e.message) + "</div></div>";
    });
  };
  UI.renderIfView = function (views) { if (views.indexOf(UI.state.view) >= 0) UI.render(); };

  // ------------------------------------------------------------------ action dispatch
  UI.actions = {};
  document.addEventListener("click", function (ev) {
    const el = ev.target.closest("[data-action]");
    if (!el) return;
    const name = el.dataset.action;
    const fn = UI.actions[name];
    if (!fn) return;
    ev.preventDefault();
    Promise.resolve(fn(el.dataset, el, ev)).catch(function (e) { UI.toast(e.message, "err", 6000); });
  });
  document.addEventListener("keydown", function (ev) {
    if (ev.key === "Escape") UI.closeModal();
  });
})();
