/* MT5 Web Console — shared view fragments + pages. */
(function () {
  "use strict";
  const UI = window.UI;
  UI.views = {};

  const S = function () { return UI.state; };

  // ------------------------------------------------------------------ fragments
  UI.positionTable = function (rows, orders, opts) {
    opts = opts || {};
    const has = (rows && rows.length) || (orders && orders.length);
    if (!has) return '<div class="empty">nothing open — place a trade or start an algo</div>';
    let html = '<div class="tbl-wrap"><table class="tbl"><thead><tr>' +
      "<th>Ticket</th><th>Symbol</th><th>Side</th><th class='num'>Volume</th><th class='num'>Open</th>" +
      "<th class='num'>Current</th><th class='num'>SL</th><th class='num'>TP</th><th class='num'>P/L</th><th>Comment</th><th></th>" +
      "</tr></thead><tbody>";
    (rows || []).forEach(function (p) {
      html += '<tr class="' + (p.type === "buy" ? "side-buy" : "side-sell") + '">' +
        "<td class='mono tiny'>" + p.ticket + (p.magic ? " <span class='badge info'>m" + p.magic + "</span>" : "") + "</td>" +
        "<td class='sym'>" + UI.esc(p.symbol) + "</td>" +
        "<td><span class='badge " + (p.type === "buy" ? "run" : "err") + "'>" + p.type + "</span></td>" +
        "<td class='num'>" + UI.num(p.volume, 2) + "</td>" +
        "<td class='num'>" + p.price_open.toFixed(p.digits || 5) + "</td>" +
        "<td class='num'>" + (p.price_current || 0).toFixed(p.digits || 5) + "</td>" +
        "<td class='num muted'>" + (p.sl ? p.sl.toFixed(p.digits || 5) : "—") + "</td>" +
        "<td class='num muted'>" + (p.tp ? p.tp.toFixed(p.digits || 5) : "—") + "</td>" +
        "<td class='num " + UI.cls(p.profit) + "'>" + UI.signed(p.profit) + "</td>" +
        "<td class='tiny muted'>" + UI.esc(p.comment || "") + "</td>" +
        "<td class='nowrap'>" +
        "<button class='btn xs ghost' data-action='modify-pos' data-ticket='" + p.ticket + "' data-sl='" + (p.sl || "") + "' data-tp='" + (p.tp || "") + "'>SL/TP</button> " +
        "<button class='btn xs' data-action='close-pos' data-ticket='" + p.ticket + "'>close</button>" +
        "</td></tr>";
    });
    (orders || []).forEach(function (o) {
      html += '<tr><td class="mono tiny">' + o.ticket + "</td><td class='sym'>" + UI.esc(o.symbol) + "</td>" +
        "<td><span class='badge warn'>" + UI.esc(o.type_text || "pending") + "</span></td>" +
        "<td class='num'>—</td><td class='num'>" + (o.price_open || 0).toFixed(5) + "</td><td class='num muted'>" + (o.price_current || 0).toFixed(5) + "</td>" +
        "<td class='num muted'>" + (o.sl ? o.sl.toFixed(5) : "—") + "</td><td class='num muted'>" + (o.tp ? o.tp.toFixed(5) : "—") + "</td>" +
        "<td class='num muted'>—</td><td class='tiny muted'>" + UI.esc(o.comment || "") + "</td>" +
        "<td><button class='btn xs red' data-action='cancel-order' data-ticket='" + o.ticket + "'>cancel</button></td></tr>";
    });
    return html + "</tbody></table></div>";
  };

  UI.symbolChips = function () {
    const st = S();
    if (!st.symbols.length) return '<span class="muted tiny">no symbols — add in Settings</span>';
    return st.symbols.map(function (s) {
      return '<span class="chip ' + (st.selected === s.name ? "on" : "") + '" data-action="pick-symbol" data-symbol="' + s.name + '">' + s.name + "</span>";
    }).join("");
  };

  UI.algoCard = function (a) {
    const st = S();
    const stats = a.stats || {};
    const badge = a.status === "running" ? "<span class='badge run'>running</span>"
      : a.status === "error" ? "<span class='badge err'>error</span>"
        : (a.deploy && a.deploy.compiled) ? "<span class='badge warn'>deployed</span>" : "<span class='badge stop'>stopped</span>";
    return '<div class="card" data-algo="' + a.id + '">' +
      '<div class="row between"><h3 style="margin:0">' + UI.esc(a.name) + " " + badge + "</h3>" +
      "<span class='tiny muted mono'>" + a.symbol + " · " + a.timeframe + " · " + a.engine + "</span></div>" +
      (a.description ? '<div class="tiny muted">' + UI.esc(a.description) + "</div>" : "") +
      '<div class="grid cols-3" style="gap:8px">' +
      "<div class='kpi'><span class='k-label'>orders</span><span class='k-value' style='font-size:16px'>" + (stats.orders || 0) + "</span></div>" +
      "<div class='kpi'><span class='k-label'>signals</span><span class='k-value' style='font-size:16px'>" + (stats.signals || 0) + "</span></div>" +
      "<div class='kpi'><span class='k-label'>floating</span><span class='k-value " + UI.cls(stats.floating) + "' style='font-size:16px'>" + UI.signed(stats.floating || 0) + "</span></div>" +
      "</div>" +
      (a.error ? '<div class="warnbox tiny">' + UI.esc(a.error) + "</div>" : "") +
      (a.deploy && a.deploy.compiled === false && a.deploy.first_error ? '<div class="warnbox tiny">EA compile failed: ' + UI.esc(a.deploy.first_error) + "</div>" : "") +
      '<div class="row"><span class="tiny muted">vol ' + a.volume + (a.stop_loss_points ? " · SL " + a.stop_loss_points + " pts" : "") + (a.take_profit_points ? " · TP " + a.take_profit_points + " pts" : "") + "</span></div>" +
      '<div class="row end">' +
      "<button class='btn sm ghost' data-action='edit-algo' data-id='" + a.id + "'>edit</button>" +
      (a.status === "running"
        ? "<button class='btn sm red' data-action='stop-algo' data-id='" + a.id + "'>■ stop</button>"
        : "<button class='btn sm green' data-action='run-algo' data-id='" + a.id + "'>▶ run</button>") +
      "</div></div>";
  };

  UI.accountForm = function (account) {
    account = account || {};
    return '<div class="field-grid">' +
      "<div class='field'><label>Broker server</label><input class='input' name='server' placeholder='ICMarkets-Demo01' value=\"" + UI.esc(account.server || "") + '" /></div>' +
      "<div class='field'><label>Login (account number)</label><input class='input' name='login' inputmode='numeric' placeholder='1234567' value=\"" + UI.esc(account.login || "") + '" /></div>' +
      "<div class='field'><label>Password</label><input class='input' name='password' type='password' placeholder='" + (account.has_password ? "•••••• (leave blank to keep)" : "trading password") + "' autocomplete='new-password' /></div>'" +
      "<div class='field'><label>Nickname</label><input class='input' name='name' placeholder='My demo' value=\"" + UI.esc(account.name || "") + '" /></div>' +
      "</div>" +
      '<details class="tiny muted"><summary>advanced — terminal path (only when the app runs on the same Windows PC)</summary>' +
      "<div class='field' style='margin-top:8px'><label>terminal64.exe</label><input class='input mono' name='terminal_path' placeholder='C:\\Program Files\\MetaTrader 5\\terminal64.exe' value=\"" + UI.esc(account.terminal_path || "") + '" /></div></details>';
  };

  UI.collect = function (root) {
    const out = {};
    root.querySelectorAll("[name]").forEach(function (el) {
      let v = el.type === "checkbox" ? el.checked : el.value;
      if (typeof v === "string" && el.dataset.num !== undefined) v = v === "" ? null : Number(v);
      out[el.name] = v;
    });
    return out;
  };

  // ------------------------------------------------------------------ OVERVIEW
  UI.views.overview = async function (host) {
    const st = S();
    await Promise.all([UI.refreshStatus(), UI.refreshTradeState(true)].map(function (p) { return p.catch(function () { }); }));
    const status = st.status || {};
    const acct = status.account || {};
    const info = st.tradeState.account || {};
    const algos = st.algoList || [];
    const running = algos.filter(function (a) { return a.status === "running"; }).length;
    const bridge = (status.agents || [])[0];
    host.innerHTML =
      '<div class="grid cols-4">' +
      kpi("Balance", UI.num(info.balance) + (info.currency ? " " + info.currency : ""), acct.login ? "login " + acct.login + " · " + acct.server : "no MT5 account bound") +
      kpi("Equity", UI.num(info.equity), "margin level " + (info.margin_level ? UI.num(info.margin_level, 0) + "%" : "—")) +
      kpi("Floating P/L", UI.signed(st.tradeState.floating_profit || 0), (st.tradeState.positions || []).length + " open position(s)") +
      kpi("Algos running", String(running), algos.length + " configured · " + (status.transport === "agent" ? "via bridge" : status.transport === "local" ? "local MT5" : "no terminal")) +
      "</div>" +

      '<div class="split wide-left">' +
      '<div class="card"><div class="row between"><h3>Watchlist <small>live quotes</small></h3>' +
      "<span class='tiny muted'>stream " + (st.ws && st.ws.readyState === 1 ? "<span class='pos'>connected</span>" : "<span class='neg'>down</span>") + "</span></div>" +
      quoteTable() + "</div>" +

      '<div class="stack">' +
      '<div class="card"><h3>Connection <small>what the app can reach</small></h3>' + connRows(status, bridge) + "</div>" +
      '<div class="card"><h3>Quick actions</h3><div class="row">' +
      "<button class='btn sm' data-action='nav' data-view='trade'>Manual trade</button>" +
      "<button class='btn sm' data-action='nav' data-view='studio'>Algo Studio</button>" +
      "<button class='btn sm ghost' data-action='nav' data-view='bridge'>Bridge agent</button>" +
      "<button class='btn sm ghost' data-action='refresh'>↻ Refresh</button>" +
      "</div></div>" +
      "</div></div>" +

      '<div class="card"><div class="row between"><h3>Algos <small>fastest way to run a strategy</small></h3>' +
      "<button class='btn sm green' data-action='new-algo'>+ new algo</button></div>" +
      (algos.length ? '<div class="grid cols-3">' + algos.map(UI.algoCard).join("") + "</div>"
        : '<div class="empty">no algo yet — open <b>Algo Studio</b> and create one from a template</div>') + "</div>" +

      '<div class="card"><h3>Recent activity</h3>' + auditList(st.audit) + "</div>";

    function kpi(label, value, sub) {
      return '<div class="card kpi"><span class="k-label">' + label + '</span><span class="k-value">' + value + '</span><span class="k-sub">' + (sub || "") + "</span></div>";
    }
  };

  function connRows(status, bridge) {
    const rows = [
      ["terminal transport", status.transport === "agent" ? "Bridge agent (Windows)" : status.transport === "local" ? "local MetaTrader5 package" : "not wired up"],
      ["OS / runtime", (status.platform || {}).system + " · python " + (status.platform || {}).python + (status.platform && status.platform.render ? " · Render" : "")],
      ["MetaTrader5 package", status.mt5_package_installed ? "importable" : "not installed here (Windows-only wheel)"],
      ["bridge agent", bridge ? bridge.name + " · " + (bridge.os || "?") + " · MT5 " + (bridge.mt5_version || "?") + " · rpc " + (bridge.rpc_count || 0) : "none connected"],
      ["account", status.account ? status.account.login + " @ " + status.account.server + " (" + status.account.status + ")" : "—"],
      ["last error", (status.account && status.account.last_error) || "—"],
    ];
    return '<dl class="kv">' + rows.map(function (r) { return "<dt>" + r[0] + "</dt><dd>" + UI.esc(r[1]) + "</dd>"; }).join("") + "</dl>";
  }

  function quoteTable() {
    const st = S();
    if (!st.symbols.length) return '<div class="empty">no symbols configured</div>';
    const rows = st.symbols.map(function (s) {
      const p = st.prices[s.name];
      const d = s.digits || 5;
      const prev = st.prevPrices[s.name];
      const dir = prev && prev.bid && p ? (p.bid > prev.bid ? "up" : p.bid < prev.bid ? "down" : "") : "";
      return "<tr><td class='sym'>" + s.name + "<div class='tiny muted'>" + UI.esc(s.description || "") + "</div></td>" +
        "<td class='num " + dir + "'>" + (p ? p.bid.toFixed(d) : "—") + "</td>" +
        "<td class='num'>" + (p ? p.ask.toFixed(d) : "—") + "</td>" +
        "<td class='num muted'>" + (p && p.ask && p.bid ? ((p.ask - p.bid) / (s.point || 1e-5)).toFixed(0) + " pts" : "—") + "</td>" +
        "<td class='num muted'>" + (p && p.time ? UI.hhmmss(p.time) : "—") + "</td>" +
        "<td><button class='btn xs ghost' data-action='nav-chart' data-symbol='" + s.name + "'>chart</button> " +
        "<button class='btn xs' data-action='open-ticket' data-symbol='" + s.name + "'>trade</button></td></tr>";
    }).join("");
    return '<div class="tbl-wrap" style="max-height:300px"><table class="tbl"><thead><tr><th>Symbol</th><th class="num">Bid</th><th class="num">Ask</th><th class="num">Spread</th><th class="num">As of</th><th></th></tr></thead><tbody>' + rows + "</tbody></table></div>";
  }

  UI.renderMt5Log = function () {
    const el = document.getElementById("mt5-log-box");
    if (!el) return;
    el.innerHTML = (S().logFeed || []).slice(0, 200).map(function (l) {
      const level = /\berror\b/i.test(l.line || "") ? "error" : /warning|failed|rejected/i.test(l.line || "") ? "warn" : "info";
      return '<div class="l"><span class="ts muted tiny">' + UI.esc((l.line || "").slice(0, 8)) + '</span><span class="lv lv-' + level + '">' + level + '</span><span>' + UI.esc((l.line || "").slice(8)) + "</span></div>";
    }).join("") || '<span class="muted">waiting for terminal log lines…</span>';
  };

  UI.bumpAlgoBadge = function (id) {
    const el = document.querySelector("[data-algo=\"" + id + "\"] .spinner");
    if (el) el.remove();
  };

  UI.setAlgos = function (items) {
    S().algoList = items || [];
    S().algos = {};
    (items || []).forEach(function (a) { S().algos[a.id] = a; });
    if (S().activeAlgo && S().algos[S().activeAlgo]) S().algoLog = S().algoLog || [];
    UI.renderIfView(["overview", "studio", "positions"]);
  };

  UI.setAlgoRuntime = function (id, row) {
    const a = S().algos[id];
    if (!a) return;
    a.stats = Object.assign({}, a.stats || {}, {
      orders: row.orders, signals: row.signals, floating: row.floating, price: row.price,
      bars: row.bars, heartbeat: row.heartbeat, positions: row.positions, equity: row.equity, errors: row.errors,
    });
    a.status = row.status || a.status;
    const card = document.querySelector('[data-algo="' + id + '"]');
    if (card && UI.state.view === "overview") { const html = UI.algoCard(a); const tmp = document.createElement("div"); tmp.innerHTML = html; card.replaceWith(tmp.firstChild); }
    if (UI.state.view === "studio" && UI.state.activeAlgo === id) UI.renderAlgoRuntime(a);
  };

  UI.auditList = async function () {
    try {
      const r = await UI.get("/bridge/audit?limit=40");
      S().audit = r.items || [];
      const el = document.getElementById("audit-list");
      if (el) el.innerHTML = auditList(S().audit);
    } catch (e) { }
  };
  function auditList(items) {
    items = items || [];
    if (!items.length) return '<div class="empty tiny">no actions yet</div>';
    return '<div class="tbl-wrap" style="max-height:220px"><table class="tbl"><thead><tr><th>when</th><th>action</th><th>detail</th></tr></thead><tbody>' +
      items.map(function (r) {
        return "<tr><td class='mono tiny muted nowrap'>" + UI.dt(r.ts) + "</td><td class='mono tiny'>" + UI.esc(r.action) + "</td><td class='tiny'>" + UI.esc(r.detail || "") + "</td></tr>";
      }).join("") + "</tbody></table></div>";
  }
  UI.auditList = UI.auditList;


  UI.renderAudit = function () { return UI.auditList(); };
})();
