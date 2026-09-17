/* MT5 Web Console — Markets, Manual Trade, Algo Studio pages. */
(function () {
  "use strict";
  const UI = window.UI;
  const S = function () { return UI.state; };

  // ------------------------------------------------------------------ MARKETS
  UI.views.markets = async function (host) {
    const st = S();
    if (!st.selected && st.symbols.length) st.selected = st.symbols[0].name;
    host.innerHTML =
      '<div class="card"><div class="row between">' +
      "<div class='row'><h3 style='margin:0'>Markets</h3><span class='chips' id='sym-chips'>" + UI.symbolChips() + "</span></div>" +
      "<div class='row'>" +
      '<div class="seg" id="tf-seg">' + ["M1", "M5", "M15", "M30", "H1", "H4", "D1"].map(function (tf) {
        return '<button data-action="set-tf" data-tf="' + tf + '" class="' + (st.timeframe === tf ? "on" : "") + '">' + tf + "</button>";
      }).join("") + "</div>" +
      '<select class="input" style="width:auto" id="bars-sel" data-action="set-bars">' + [100, 200, 400, 800].map(function (b) {
        return "<option value='" + b + "'" + (st.bars === b ? " selected" : "") + ">" + b + " bars</option>";
      }).join("") + "</select>" +
      '<button class="btn sm ghost" data-action="reload-chart">↻</button>' +
      "</div></div></div>" +

      '<div class="card" id="chart-card"><div class="row between">' +
      "<h3 id='chart-title'>" + UI.esc(st.selected || "—") + " <small>loading…</small></h3>" +
      "<span id='chart-quote' class='mono tiny muted'></span></div>" +
      '<div id="chart-box"><div class="empty">waiting for candles from the terminal…</div></div>' +
      '<div class="row between"><div class="chart-legend" id="chart-legend"></div>' +
      "<div class='row'><button class='btn sm green' data-action='open-ticket' data-side='buy'>Buy</button>" +
      "<button class='btn sm red' data-action='open-ticket' data-side='sell'>Sell</button>" +
      "<button class='btn sm ghost' data-action='new-algo-from-chart'>+ algo on this symbol</button></div></div></div>" +

      '<div class="split"><div class="card"><h3>Open positions on this symbol</h3><div id="sym-positions">' + positionsForSymbol() + "</div></div>" +
      '<div class="card"><h3>Symbol info <small>from the terminal</small></h3><div id="sym-info">' + symbolInfo() + "</div></div></div>";

    UI.loadChart();
  };

  function positionsForSymbol() {
    const st = S();
    const rows = (st.tradeState.positions || []).filter(function (p) { return p.symbol === st.selected; });
    return UI.positionTable(rows, []);
  }
  function symbolInfo() {
    const st = S();
    const meta = st.chart.meta || st.symbols.find(function (s) { return s.name === st.selected; }) || {};
    const rows = [
      ["description", meta.description || "—"],
      ["digits / point", (meta.digits || 5) + " / " + (meta.point || 1e-5)],
      ["min / max / step", [meta.volume_min, meta.volume_max, meta.volume_step].map(function (v) { return v == null ? "—" : v; }).join(" / ")],
      ["spread", (meta.spread == null ? "—" : meta.spread + " pts")],
      ["contract size", meta.contract_size || "—"],
      ["profit currency", meta.currency_profit || "—"],
      ["source", meta.source || (meta.point ? "terminal" : "app default")],
    ];
    return "<dl class='kv'>" + rows.map(function (r) { return "<dt>" + r[0] + "</dt><dd>" + UI.esc(r[1]) + "</dd>"; }).join("") + "</dl>";
  }

  UI.loadChart = async function (quiet) {
    const st = S();
    const box = document.getElementById("chart-box");
    if (!st.selected) { if (box) box.innerHTML = '<div class="empty">pick a symbol above</div>'; return; }
    if (!quiet && box) box.innerHTML = '<div class="empty"><span class="spinner"></span> fetching ' + st.selected + " " + st.timeframe + "…</div>";
    try {
      const r = await UI.get("/market/rates?symbol=" + st.selected + "&timeframe=" + st.timeframe + "&bars=" + st.bars);
      st.chart = { rows: r.bars || [], meta: r.meta || {}, loading: false, error: null };
      UI.renderChart();
    } catch (e) {
      st.chart.error = e.message;
      if (box) box.innerHTML = '<div class="warnbox">' + UI.esc(e.message) + "</div>";
    }
  };

  UI.renderChart = function () {
    const st = S();
    const box = document.getElementById("chart-box");
    if (!box) return;
    const rows = st.chart.rows || [];
    const meta = st.chart.meta || {};
    const digits = meta.digits || 5;
    const title = document.getElementById("chart-title");
    if (title) title.innerHTML = UI.esc(st.selected) + " <small>" + st.timeframe + " · " + rows.length + " bars</small>";
    const levels = [];
    (st.tradeState.positions || []).forEach(function (p) {
      if (p.symbol !== st.selected) return;
      levels.push({ price: p.price_open, label: "#" + p.ticket + " " + p.type, color: p.type === "buy" ? "#37e6a4" : "#ff5d6c" });
      if (p.sl) levels.push({ price: p.sl, label: "SL", color: "#ffc76b" });
      if (p.tp) levels.push({ price: p.tp, label: "TP", color: "#6ba8ff" });
    });
    const series = [];
    if (rows.length > 20) {
      const closes = rows.map(function (r) { return r.close; });
      const period = st.timeframe === "M1" || st.timeframe === "M5" ? 20 : 14;
      const ema = []; let prev = closes[0]; const k = 2 / (period + 1);
      closes.forEach(function (c) { prev = c * k + prev * (1 - k); ema.push(prev); });
      series.push({ values: ema, color: "#6ba8ff", width: 1.3, opacity: 0.85 });
    }
    box.innerHTML = UI.candleChart(rows, {
      height: 380, digits: digits, levels: levels, series: series,
      symbol: st.selected, timeframe: st.timeframe, volume: true,
    });
    const legend = document.getElementById("chart-legend");
    if (legend) legend.innerHTML = "<i style='color:#6ba8ff'>— EMA " + (st.timeframe === "M1" || st.timeframe === "M5" ? 20 : 14) + "</i>" +
      (levels.length ? "<i class='muted'>levels: " + levels.map(function (l) { return UI.esc(l.label); }).join(", ") + "</i>" : "");
    const q = document.getElementById("chart-quote");
    const p = st.prices[st.selected];
    if (q) q.innerHTML = p ? "bid <b class='mono'>" + p.bid.toFixed(digits) + "</b> · ask <b class='mono'>" + p.ask.toFixed(digits) + "</b> · " + UI.hhmmss(p.time) : "";
    const sp = document.getElementById("sym-positions");
    if (sp) sp.innerHTML = positionsForSymbol();
    const si = document.getElementById("sym-info");
    if (si) si.innerHTML = symbolInfo();
  };

  UI.patchChartLastTick = function (tick) {
    const st = S();
    const rows = st.chart.rows;
    if (!rows || !rows.length) return;
    const price = (tick.bid + tick.ask) / 2;
    const last = rows[rows.length - 1];
    last.close = price;
    last.high = Math.max(last.high, price);
    last.low = Math.min(last.low, price);
    const box = document.getElementById("chart-box");
    if (box && box.querySelector("svg")) UI.renderChart();
    const q = document.getElementById("chart-quote");
    if (q) q.innerHTML = "bid <b class='mono'>" + tick.bid.toFixed((st.chart.meta.digits || 5)) + "</b> · ask <b class='mono'>" + tick.ask.toFixed((st.chart.meta.digits || 5)) + "</b> · " + UI.hhmmss(tick.time);
  };

  // ------------------------------------------------------------------ TICKET
  UI.openTicket = async function (symbol, side) {
    const st = S();
    symbol = symbol || st.selected || (st.symbols[0] || {}).name;
    const meta = st.symbols.find(function (s) { return s.name === symbol; }) || {};
    const digits = meta.digits || 5;
    const tick = st.prices[symbol] || {};
    const suggestedSL = Math.max(10, Math.round((meta.spread || 10) * 3));
    UI.modal("Order ticket · " + symbol,
      '<div class="field-grid">' +
      "<div class='field'><label>Symbol</label><select class='input' name='symbol'>" +
      st.symbols.map(function (s) { return "<option " + (s.name === symbol ? "selected" : "") + ">" + s.name + "</option>"; }).join("") + "</select></div>" +
      "<div class='field'><label>Order type</label><select class='input' name='order_type'>" +
      ["market", "buy_limit", "sell_limit", "buy_stop", "sell_stop"].map(function (o) { return "<option " + (o === "market" ? "selected" : "") + ">" + o + "</option>"; }).join("") + "</select></div>" +
      "<div class='field'><label>Volume (lots)</label><input class='input' name='volume' data-num='1' value='" + (meta.volume_min || 0.01) + "' /></div>" +
      "<div class='field'><label>Price (pending only)</label><input class='input' name='price' data-num='1' placeholder='" + (tick.bid ? tick.bid.toFixed(digits) : "market") + "' /></div>" +
      "<div class='field'><label>SL in points</label><input class='input' name='sl_points' data-num='1' placeholder='" + suggestedSL + "' /></div>" +
      "<div class='field'><label>TP in points</label><input class='input' name='tp_points' data-num='1' placeholder='" + suggestedSL * 2 + "' /></div>" +
      "<div class='field'><label>Deviation</label><input class='input' name='deviation' data-num='1' value='20' /></div>" +
      "<div class='field'><label>Comment</label><input class='input' name='comment' value='web' /></div>" +
      "</div>" +
      '<div class="row" style="margin-top:10px"><span class="tiny muted">last quote: ' +
      (tick.bid ? "<span class='mono'>bid " + tick.bid.toFixed(digits) + " / ask " + tick.ask.toFixed(digits) + "</span>" : "<span class='neg'>no live quote</span>") +
      "</span></div>" +
      '<div class="row" style="margin-top:12px;gap:8px">' +
      "<button class='btn green' data-action='send-order' data-dir='buy'>BUY " + UI.esc(symbol) + "</button>" +
      "<button class='btn red' data-action='send-order' data-dir='sell'>SELL " + UI.esc(symbol) + "</button>" +
      "<span class='spacer'></span><button class='btn ghost' data-action='close-modal'>cancel</button></div>",
      { actions: "" });
  };

  // ------------------------------------------------------------------ TRADE page
  UI.views.trade = async function (host) {
    const st = S();
    await UI.refreshTradeState(true).catch(function () { });
    host.innerHTML =
      '<div class="split"><div class="card"><h3>Manual order <small>sent straight to the terminal</small></h3>' +
      '<div id="ticket-inline"></div>' +
      '<div class="infox tiny" id="ticket-hint">Tip: point/SL/TP sizes are read from the symbol — XAUUSD and BTCUSD use different point values than FX pairs.</div>' +
      "</div>" +
      '<div class="stack"><div class="card"><h3>Risk calculator</h3>' + riskCalc() + "</div>" +
      '<div class="card"><h3>Kill switch</h3><div class="tiny muted">When engaged, every new order is refused and all algos stop. Use it the instant something looks wrong.</div>' +
      "<div class='row'><button class='btn red' data-action='kill-on'>Engage kill switch</button>" +
      "<button class='btn ghost' data-action='close-all'>Close all positions</button></div></div></div></div>" +

      '<div class="card"><h3>Open positions &amp; pending orders</h3><div id="trade-list">' +
      UI.positionTable(st.tradeState.positions || [], st.tradeState.orders || []) + "</div></div>";
    document.getElementById("ticket-inline").innerHTML =
      '<div class="field-grid">' +
      "<div class='field'><label>Symbol</label><select class='input' name='symbol' id='tk-symbol'>" +
      st.symbols.map(function (s) { return "<option>" + s.name + "</option>"; }).join("") + "</select></div>" +
      "<div class='field'><label>Volume</label><input class='input' name='volume' data-num='1' value='0.01' /></div>" +
      "<div class='field'><label>SL points</label><input class='input' name='sl_points' data-num='1' placeholder='300' /></div>" +
      "<div class='field'><label>TP points</label><input class='input' name='tp_points' data-num='1' placeholder='600' /></div>" +
      "<div class='field'><label>Order type</label><select class='input' name='order_type'><option>market</option><option>buy_limit</option><option>sell_limit</option><option>buy_stop</option><option>sell_stop</option></select></div>" +
      "<div class='field'><label>Price</label><input class='input' name='price' data-num='1' placeholder='auto' /></div>" +
      "</div>" +
      '<div class="row" style="margin-top:10px"><button class="btn green" data-action="send-order" data-dir="buy">BUY</button>' +
      '<button class="btn red" data-action="send-order" data-dir="sell">SELL</button>' +
      '<button class="btn ghost" data-action="close-modal">clear</button></div>';
  };

  function riskCalc() {
    const info = S().tradeState.account || {};
    return '<div class="field-grid">' +
      "<div class='field'><label>Balance</label><input class='input' id='rc-bal' data-num='1' value='" + (info.balance || 10000) + "' /></div>" +
      "<div class='field'><label>Risk %</label><input class='input' id='rc-risk' data-num='1' value='1' /></div>" +
      "<div class='field'><label>SL points</label><input class='input' id='rc-sl' data-num='1' value='250' /></div>" +
      "<div class='field'><label>Symbol</label><select class='input' id='rc-sym'>" +
      S().symbols.map(function (s) { return "<option>" + s.name + "</option>"; }).join("") + "</select></div>" +
      "</div><div class='row between' style='margin-top:8px'><button class='btn sm' data-action='calc-risk'>Suggest lots</button>" +
      "<span class='mono tiny' id='rc-out'>—</span></div>";
  }

  // ------------------------------------------------------------------ ALGO STUDIO
  UI.views.studio = async function (host) {
    const st = S();
    const r = await UI.get("/algos");
    st.algoList = r.items || [];
    if (!st.activeAlgo && st.algoList.length) st.activeAlgo = st.algoList[0].id;
    host.innerHTML =
      '<div class="row between"><h3 style="margin:0">Algo Studio <span class="muted tiny">' + st.algoList.length + " configured</span></h3>" +
      "<div class='row'><button class='btn sm ghost' data-action='new-algo-mql5'>+ import MQL5 EA</button>" +
      "<button class='btn sm ghost' data-action='new-algo-hybrid'>+ Python → EA bridge</button>" +
      "<button class='btn sm green' data-action='new-algo'>+ new Python algo</button></div></div>" +
      (st.algoList.length
        ? '<div class="grid cols-3">' + st.algoList.map(UI.algoCard).join("") + "</div>"
        : '<div class="empty">No algos yet. Create one — a Python strategy runs from this server (recommended), an MQL5 Expert Advisor is compiled into your terminal.</div>') +
      (st.activeAlgo ? '<div id="algo-detail"></div>' : "");
    if (st.activeAlgo) UI.renderAlgoDetail(st.activeAlgo);
  };

  UI.renderAlgoDetail = async function (id) {
    const box = document.getElementById("algo-detail");
    if (!box) return;
    const a = await UI.get("/algos/" + id);
    const src = await UI.get("/algos/" + id + "/source");
    S().activeAlgo = id;
    S().algoLog = [];
    box.innerHTML =
      '<div class="split wide-left"><div class="card">' +
      '<div class="row between"><h3>Strategy source <small>' + UI.esc(a.name) + " · " + a.engine + "</small></h3>" +
      "<span class='tiny muted mono'>" + a.source_bytes + " bytes</span></div>" +
      "<textarea class='input mono' id='algo-src' spellcheck='false'>" + UI.esc(src.source || "") + "</textarea>" +
      '<div class="row">' +
      "<button class='btn sm' data-action='save-source' data-id='" + a.id + "'>save</button>" +
      "<button class='btn sm ghost' data-action='backtest' data-id='" + a.id + "'>▶ backtest on real candles</button>" +
      (a.engine === "mql5"
        ? "<button class='btn sm amber' data-action='deploy-ea' data-id='" + a.id + "'>compile + deploy to MT5</button>"
        : "") +
      (a.engine !== "python"
        ? "<button class='btn sm ghost' data-action='download-ea' data-id='" + a.id + "'>download .mq5</button>"
        : "") +
      "<span class='spacer'></span>" +
      (a.status === "running"
        ? "<button class='btn sm red' data-action='stop-algo' data-id='" + a.id + "'>■ stop engine</button>"
        : "<button class='btn sm green' data-action='run-algo' data-id='" + a.id + "'>▶ run live</button>") +
      "</div>" +
      '<div class="tiny muted">Live mode executes orders through your MT5 account on every closed bar. Backtest never sends orders.</div>' +
      "</div>" +
      '<div class="stack">' +
      '<div class="card"><h3>Runtime</h3><div id="algo-runtime">' + runtimeRows(a) + "</div></div>" +
      '<div class="card"><h3>Settings</h3>' + algoSettings(a) + "</div>" +
      "</div></div>" +
      '<div class="card"><h3>Engine log <small>live</small></h3><div class="log" id="algo-log"><span class="muted">waiting for engine output…</span></div></div>' +
      '<div class="card" id="bt-card" style="display:none"><h3>Backtest <small>bar-based smoke test</small></h3><div id="bt-body"></div></div>';
    UI.renderAlgoLog();
    try {
      const lg = await UI.get("/algos/" + id + "/log");
      S().algoLog = lg.lines || [];
      UI.renderAlgoLog();
    } catch (e) { }
  };

  function runtimeRows(a) {
    const s = a.stats || {};
    const d = a.deploy || {};
    const rows = [
      ["status", a.status + (s.heartbeat ? " · beat " + UI.ago(s.heartbeat) : "")],
      ["symbol", a.symbol + " " + a.timeframe],
      ["volume", a.volume + (a.volume_from_risk ? " (risk " + a.risk_percent + "% of balance)" : "")],
      ["stops", (a.stop_loss_points || "—") + " / " + (a.take_profit_points || "—") + " pts" + (a.trailing_points ? " · trail " + a.trailing_points : "")],
      ["orders sent", s.orders || 0],
      ["signals", s.signals || 0],
      ["errors", s.errors || 0],
      ["floating", UI.signed(s.floating || 0)],
      ["position(s)", s.positions == null ? "—" : s.positions],
      ["last price", s.price == null ? "—" : s.price],
      ["EA compile", d.compiled === undefined ? "n/a" : d.compiled ? "ok (" + (d.warnings || 0) + " warnings)" : "FAILED " + (d.first_error || "")],
      ["EA signal file", d.signal_file || "n/a"],
    ];
    return "<dl class='kv'>" + rows.map(function (r) { return "<dt>" + r[0] + "</dt><dd>" + UI.esc(r[1]) + "</dd>"; }).join("") + "</dl>";
  }

  function algoSettings(a) {
    const num = function (name, label, value, step) {
      return "<div class='field'><label>" + label + "</label><input class='input' data-num='1' step='" + (step || 1) + "' name='" + name + "' value='" + (value === null || value === undefined ? "" : value) + "' /></div>";
    };
    const st = S();
    return '<div class="field-grid">' +
      "<div class='field'><label>Symbol</label><select class='input' name='symbol'>" +
      st.symbols.map(function (s) { return "<option " + (s.name === a.symbol ? "selected" : "") + ">" + s.name + "</option>"; }).join("") + "</select></div>" +
      "<div class='field'><label>Timeframe</label><select class='input' name='timeframe'>" +
      ["M1", "M5", "M15", "M30", "H1", "H4", "D1"].map(function (t) { return "<option " + (t === a.timeframe ? "selected" : "") + ">" + t + "</option>"; }).join("") + "</select></div>" +
      num("volume", "Fixed volume (lots)", a.volume, 0.01) +
      num("risk_percent", "Risk % of balance", a.risk_percent, 0.1) +
      num("stop_loss_points", "SL points", a.stop_loss_points) +
      num("take_profit_points", "TP points", a.take_profit_points) +
      num("trailing_points", "Trailing points", a.trailing_points) +
      num("max_daily_loss_percent", "Daily loss halt %", a.max_daily_loss_percent, 0.5) +
      num("max_open_positions", "Max positions", a.max_open_positions) +
      num("magic", "Magic number", a.magic) +
      "</div>" +
      '<div class="row" style="margin-top:10px">' +
      toggle("volume_from_risk", "size lots from risk", a.volume_from_risk) +
      toggle("allow_reverse", "allow reversing", a.allow_reverse) +
      toggle("one_position_per_symbol", "one position per symbol", a.one_position_per_symbol) +
      '<span class="spacer"></span><button class="btn sm green" data-action="save-algo" data-id="' + a.id + '">apply settings</button></div>';
  }
  function toggle(name, label, on) {
    return "<label class='switch-row'><input type='checkbox' name='" + name + "'" + (on ? " checked" : "") + " /><span class='sw'></span><span class='tiny'>" + label + "</span></label>";
  }

  UI.renderAlgoLog = function () {
    const el = document.getElementById("algo-log");
    if (!el) return;
    const rows = S().algoLog || [];
    el.innerHTML = rows.length ? rows.map(function (l) {
      return '<div class="l"><span class="ts">' + UI.hhmmss(l.ts) + '</span><span class="lv lv-' + (l.level || "info") + '">' + (l.level || "info") + "</span><span>" + UI.esc(l.text) + "</span></div>";
    }).join("") : '<span class="muted">waiting for engine output…</span>';
    el.scrollTop = el.scrollHeight;
  };
  UI.renderAlgoRuntime = function (a) {
    const el = document.getElementById("algo-runtime");
    if (el) el.innerHTML = runtimeRows(a);
    UI.renderAlgoLog();
  };

  UI.renderBacktest = function (res) {
    const card = document.getElementById("bt-card");
    const body = document.getElementById("bt-body");
    if (!card || !body) return;
    card.style.display = "";
    const trades = res.trades || [];
    body.innerHTML =
      '<div class="grid cols-4">' +
      ["Net " + UI.signed(res.net_money) + "<div class='tiny muted'>" + UI.signed(res.net_points, 1) + " pts</div>",
      "Trades " + res.trade_count + "<div class='tiny muted'>" + res.wins + "W / " + res.losses + "L</div>",
      "Win rate " + res.win_rate + "%<div class='tiny muted'>PF " + (res.profit_factor == null ? "—" : res.profit_factor) + "</div>",
      "Max DD " + UI.money(res.max_drawdown_money) + "<div class='tiny muted'>errors " + res.errors + "</div>"]
        .map(function (x, i) { return '<div class="kpi"><span class="k-label">' + ["result", "count", "quality", "risk"][i] + "</span><span class='k-value' style='font-size:17px'>" + x + "</span></div>"; }).join("") +
      "</div>" +
      (res.equity_curve && res.equity_curve.length > 1 ? UI.sparkline(res.equity_curve.map(function (p) { return p.equity; }), { height: 70 }) : "") +
      (res.first_error ? '<div class="warnbox tiny">strategy error: ' + UI.esc(res.first_error) + "</div>" : "") +
      '<div class="tiny muted">' + UI.esc(res.note || "") + "</div>" +
      (trades.length ? '<div class="tbl-wrap" style="max-height:230px"><table class="tbl"><thead><tr><th>in</th><th>out</th><th>side</th><th class="num">price</th><th class="num">exit</th><th class="num">points</th><th class="num">money</th><th>why</th></tr></thead><tbody>' +
        trades.slice(-40).reverse().map(function (t) {
          return "<tr><td class='tiny mono'>" + UI.dt(t.entry_time) + "</td><td class='tiny mono'>" + UI.dt(t.exit_time) + "</td>" +
            "<td><span class='badge " + (t.dir > 0 ? "run" : "err") + "'>" + (t.dir > 0 ? "buy" : "sell") + "</span></td>" +
            "<td class='num'>" + t.price + "</td><td class='num'>" + t.exit_price + "</td>" +
            "<td class='num " + UI.cls(t.points) + "'>" + UI.signed(t.points, 1) + "</td><td class='num " + UI.cls(t.money) + "'>" + UI.signed(t.money) + "</td>" +
            "<td class='tiny muted'>" + UI.esc(t.reason + (t.reason_in ? "/" + t.reason_in : "")) + "</td></tr>";
        }).join("") + "</tbody></table></div>" : '<div class="empty tiny">the strategy produced no trades on this window</div>');
    card.scrollIntoView({ behavior: "smooth", block: "nearest" });
  };
})();
