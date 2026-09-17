/* MT5 Web Console — action handlers + boot. */
(function () {
  "use strict";
  const UI = window.UI;
  const S = function () { return UI.state; };
  const A = UI.actions;

  // ------------------------------------------------------------------ helpers
  function val(sel, root) { const el = (root || document).querySelector(sel); return el ? el.value.trim() : ""; }
  function numv(sel, root) { const v = val(sel, root); return v === "" ? null : Number(v); }
  function boolv(sel, root) { const el = (root || document).querySelector(sel); return el ? !!el.checked : false; }
  async function run(btn, fn) {
    if (btn) { btn.disabled = true; const old = btn.innerHTML; btn.innerHTML = '<span class="spinner"></span> working'; }
    try { await fn(); } finally {
      if (btn) { btn.disabled = false; btn.innerHTML = old; }
    }
  }

  // ------------------------------------------------------------------ auth
  A.login = function (d, el) {
    const pass = val("#pass-input");
    if (!pass) { UI.toast("enter a passcode first", "warn"); return; }
    return run(el, async function () {
      const r = await UI.post("/auth/login", { passcode: pass });
      UI.state.token = r.token;
      sessionStorage.setItem("m5tok", r.token);
      UI.toast(r.first_run ? "passcode created — welcome" : "signed in", "ok");
      UI.boot();
    });
  };
  A.logout = function () {
    sessionStorage.removeItem("m5tok"); UI.state.token = ""; UI.renderAuth();
  };
  A["nav"] = function (d) { UI.go(d.view); };
  A["nav-chart"] = function (d) { S().selected = d.symbol; UI.go("markets"); };
  A["close-modal"] = function () { UI.closeModal(); };
  A["refresh"] = async function () { await UI.refreshStatus(); UI.refreshTradeState(); if (S().view === "markets") UI.loadChart(true); UI.toast("refreshed", "ok", 1500); };
  A["reload-chart"] = function () { return UI.loadChart(); };
  A["copy"] = function (d) { UI.copy(d.text, "value"); };
  A["set-tf"] = function (d) {
    S().timeframe = d.tf;
    document.querySelectorAll("#tf-seg button").forEach(function (b) { b.classList.toggle("on", b.dataset.tf === d.tf); });
    return UI.loadChart();
  };
  A["set-bars"] = function (d, el) { S().bars = Number(el.value); return UI.loadChart(); };
  A["pick-symbol"] = function (d) { S().selected = d.symbol; UI.render(); };

  // ------------------------------------------------------------------ symbols
  A["add-symbols"] = function (d, el) {
    const raw = val("#new-syms");
    if (!raw) { UI.toast("type one or more symbols", "warn"); return; }
    return run(el, async function () {
      const r = await UI.post("/symbols", { symbols: raw.split(/[,\s]+/).filter(Boolean) });
      UI.toast("added: " + (r.added.join(", ") || "already present"), "ok");
      await UI.refreshStatus(); UI.render();
    });
  };
  A["del-symbol"] = function (d, el) {
    return run(el, async function () {
      await UI.del("/symbols/" + d.symbol);
      await UI.refreshStatus(); UI.render();
    });
  };

  // ------------------------------------------------------------------ account
  A["save-account"] = function (d, el) {
    const root = document.getElementById("acct-form");
    const f = UI.collect(root);
    if (!f.server || !f.login || !f.password) { UI.toast("server, login and password are all required", "warn"); return; }
    return run(el, async function () {
      const r = await UI.post("/accounts", {
        name: f.name || (f.server + " " + f.login), server: f.server, login: Number(f.login),
        password: f.password, terminal_path: f.terminal_path || null, make_default: true,
      });
      if (r.connected) { UI.toast("connected to MT5 ✓", "ok", 6000); await UI.refreshStatus(); UI.renderIfView(["settings", "overview"]); UI.render(); }
      else { UI.modal("Account saved, but the terminal refused the login", '<div class="warnbox">' + UI.esc(r.error) + "</div><div class='tiny muted' style='margin-top:10px'>Checklist: 1) is a Bridge agent connected? 2) does the login/password belong to this server? 3) is the broker account active (demo accounts expire)? 4) on a Linux/Wine box, is the terminal actually running in that user session?</div>"); }
    });
  };
  A["connect-account"] = function (d, el) {
    return run(el, async function () {
      try { const r = await UI.post("/accounts/connect?account_id=" + d.id); UI.toast("connected · equity " + UI.num(r.account.equity), "ok", 6000); UI.render(); }
      catch (e) { UI.toast(e.message, "err", 9000); }
    });
  };
  A["disconnect"] = function (d, el) {
    return run(el, async function () { await UI.post("/accounts/disconnect"); UI.toast("disconnected", "warn"); UI.refreshStatus(); });
  };
  A["del-account"] = function (d, el) {
    return run(el, async function () { await UI.del("/accounts/" + d.id); UI.refreshStatus(); UI.render(); });
  };
  A["save-settings"] = function (d, el) {
    return run(el, async function () {
      await UI.post("/settings", {
        max_lot: numv("#max-lot"), tick_interval: numv("#tick-int"),
        allow_live_trading: boolv('[name=allow_live]'),
      });
      const tf = val("#chart-tf"); if (tf) S().timeframe = tf;
      UI.toast("settings applied", "ok"); UI.refreshStatus();
    });
  };
  A["change-passcode"] = function (d, el) {
    const p = val("#new-pass");
    if (!p || p.length < 6) { UI.toast("passcode must be 6+ chars", "warn"); return; }
    return run(el, async function () {
      try { await UI.post("/auth/change-passcode", { passcode: p }); UI.toast("passcode changed — sign in again", "ok"); setTimeout(function () { A.logout(); }, 900); }
      catch (e) { UI.toast(e.message, "err"); }
    });
  };

  // ------------------------------------------------------------------ kill switch
  A["kill-on"] = function (d, el) {
    return run(el, async function () { await UI.post("/settings", { kill_switch: true }); await UI.refreshStatus(); UI.toast("kill switch engaged — orders blocked, algos stopped", "warn", 6000); });
  };
  document.addEventListener("change", function (ev) {
    if (ev.target.id !== "kill-switch") return;
    UI.post("/settings", { kill_switch: ev.target.checked }).then(function () {
      UI.toast(ev.target.checked ? "kill switch engaged" : "kill switch released", ev.target.checked ? "warn" : "ok");
      UI.refreshStatus();
    }).catch(function (e) { UI.toast(e.message, "err"); ev.target.checked = false; });
  });

  // ------------------------------------------------------------------ orders
  A["open-ticket"] = function (d) { return UI.openTicket(d.symbol, d.side); };
  A["send-order"] = function (d, el) {
    const root = el.closest(".modal") || document.getElementById("view");
    const f = UI.collect(root);
    if (!f.symbol) { UI.toast("no symbol selected", "warn"); return; }
    const dir = el.dataset.dir;
    if (!confirm(dir.toUpperCase() + " " + f.volume + " " + f.symbol + " ?")) return;
    return run(el, async function () {
      try {
        const r = await UI.post("/trade/order", {
          symbol: f.symbol, direction: dir, volume: Number(f.volume || 0.01),
          order_type: f.order_type || "market", price: f.price ? Number(f.price) : null,
          sl_points: f.sl_points ? Number(f.sl_points) : null, tp_points: f.tp_points ? Number(f.tp_points) : null,
          deviation: Number(f.deviation || 20), comment: f.comment || "web",
        });
        UI.toast(dir.toUpperCase() + " sent · order " + r.order + " @ " + r.price + " (SL " + (r.sl || "-") + " / TP " + (r.tp || "-") + ")", "ok", 7000);
        UI.closeModal(); UI.refreshTradeState();
        if (S().view === "markets") UI.loadChart(true);
      } catch (e) {
        UI.modal("Order rejected", '<div class="warnbox">' + UI.esc(e.message) + "</div>" +
          (e.payload && e.payload.code ? "<div class='tiny muted mono' style='margin-top:8px'>retcode " + e.payload.code + "</div>" : "") +
          "<div class='tiny muted' style='margin-top:10px'>Most common causes: the symbol is not in Market Watch, algo trading is switched off in the terminal, volume below the symbol minimum, or SL/TP closer than the broker's freeze level.</div>");
      }
    });
  };
  A["close-pos"] = function (d, el) {
    if (!confirm("Close position #" + d.ticket + " completely?")) return;
    return run(el, async function () {
      try { await UI.post("/trade/close", { ticket: Number(d.ticket) }); UI.toast("closed #" + d.ticket, "ok"); UI.refreshTradeState(); }
      catch (e) { UI.toast(e.message, "err", 7000); }
    });
  };
  A["modify-pos"] = function (d, el) {
    UI.modal("Modify #" + d.ticket,
      '<div class="field-grid">' +
      "<div class='field'><label>Stop loss (price)</label><input class='input' id='m-sl' data-num='1' value='" + (d.sl || "") + "' placeholder='0 = none' /></div>" +
      "<div class='field'><label>Take profit (price)</label><input class='input' id='m-tp' data-num='1' value='" + (d.tp || "") + "' placeholder='0 = none' /></div>" +
      "</div><div class='infox tiny' style='margin-top:8px'>Absolute prices, not points. Leave blank to keep, 0 to remove.</div>" +
      '<div class="modal-actions"><button class="btn ghost" data-action="close-modal">cancel</button>' +
      "<button class='btn green' data-action='modify-apply' data-ticket='" + d.ticket + "'>apply</button></div>");
  };
  A["modify-apply"] = function (d, el) {
    const body = { ticket: Number(d.ticket), stop_loss: numv("#m-sl"), take_profit: numv("#m-tp") };
    return run(el, async function () {
      try { await UI.post("/trade/modify", body); UI.toast("SL/TP updated", "ok"); UI.closeModal(); UI.refreshTradeState(); }
      catch (e) { UI.toast(e.message, "err", 8000); }
    });
  };
  A["cancel-order"] = function (d, el) {
    return run(el, async function () {
      try { await UI.post("/trade/cancel-order", { ticket: Number(d.ticket) }); UI.toast("pending order cancelled", "ok"); UI.refreshTradeState(); }
      catch (e) { UI.toast(e.message, "err", 7000); }
    });
  };
  A["close-all"] = async function (d, el) {
    const rows = (S().tradeState.positions || []).slice();
    if (!rows.length) { UI.toast("nothing to close", "warn"); return; }
    if (!confirm("Close ALL " + rows.length + " open position(s)?")) return;
    await run(el, async function () {
      let ok = 0, fail = 0;
      for (const p of rows) {
        try { await UI.post("/trade/close", { ticket: p.ticket }); ok++; } catch (e) { fail++; UI.toast("#" + p.ticket + ": " + e.message, "err"); }
      }
      UI.toast(ok + " closed" + (fail ? ", " + fail + " failed" : ""), fail ? "warn" : "ok", 6000);
      UI.refreshTradeState();
    });
  };
  A["calc-risk"] = function (d, el) {
    return run(el, async function () {
      const r = await UI.get("/trade/risk?balance=" + numv("#rc-bal") + "&risk_percent=" + numv("#rc-risk") +
        "&sl_points=" + numv("#rc-sl") + "&symbol=" + val("#rc-sym"));
      document.getElementById("rc-out").innerHTML = "→ <b>" + r.suggested_lots + "</b> lots (" + UI.money(r.risk_money) + " at risk)";
      UI.toast("suggested volume " + r.suggested_lots + " lots", "ok", 4000);
    });
  };

  // ------------------------------------------------------------------ algos
  A["new-algo"] = function (d, el) { algoForm("python"); };
  A["new-algo-mql5"] = function () { algoForm("mql5"); };
  A["new-algo-hybrid"] = function () { algoForm("hybrid"); };
  A["new-algo-from-chart"] = function () { algoForm("python", S().selected); };
  A["edit-algo"] = function (d) { S().activeAlgo = d.id; UI.go("studio"); };

  function algoForm(engine, symbol) {
    const st = S();
    symbol = symbol || st.selected || (st.symbols[0] || {}).name || "EURUSD";
    const options = st.symbols.map(function (s) { return "<option " + (s.name === symbol ? "selected" : "") + ">" + s.name + "</option>"; }).join("");
    const engineRow =
      '<div class="field-grid" style="grid-template-columns:repeat(3,minmax(0,1fr))">' +
      [["python", "Python in-app engine", "runs on this server, executes live on each closed bar"],
      ["hybrid", "Python → EA bridge", "python computes signals, a generated MQL5 EA executes them inside MT5"],
      ["mql5", "Pure MQL5 EA", "your .mq5 source is compiled and deployed into the terminal"]]
        .map(function (e, i) {
          return '<label class="chip ' + (e[0] === engine ? "on" : "") + '" style="text-align:left;padding:8px 10px">' +
            '<input type="radio" name="engine" value="' + e[0] + '" ' + (e[0] === engine ? "checked" : "") + ' style="display:none">' +
            "<b>" + e[1] + "</b><div class='tiny muted' style='margin-top:2px'>" + e[2] + "</div></label>";
        }).join("") + "</div>";
    UI.modal("New algo",
      engineRow +
      '<div class="field-grid" style="margin-top:10px">' +
      "<div class='field'><label>Name (letters/digits/-/_)</label><input class='input' name='name' value='My Algo' /></div>" +
      "<div class='field'><label>Symbol</label><select class='input' name='symbol'>" + options + "</select></div>" +
      "<div class='field'><label>Timeframe</label><select class='input' name='timeframe'>" +
      ["M1", "M5", "M15", "H1", "H4"].map(function (t) { return "<option" + (t === "M5" ? " selected" : "") + ">" + t + "</option>"; }).join("") + "</select></div>" +
      "<div class='field'><label>Volume (lots)</label><input class='input' name='volume' data-num='1' value='0.01' /></div>" +
      "<div class='field'><label>SL points</label><input class='input' name='stop_loss_points' data-num='1' value='300' /></div>" +
      "<div class='field'><label>TP points</label><input class='input' name='take_profit_points' data-num='1' value='600' /></div>" +
      "<div class='field'><label>Risk % (if sizing)</label><input class='input' name='risk_percent' data-num='1' value='1' /></div>" +
      "<div class='field'><label>Magic</label><input class='input' name='magic' data-num='1' value='" + (20260000 + Math.floor(Math.random() * 999)) + "' /></div>" +
      "</div>" +
      '<div class="modal-actions"><button class="btn ghost" data-action="close-modal">cancel</button>' +
      "<button class='btn green' data-action='create-algo'>create</button></div>");
  }

  A["create-algo"] = function (d, el) {
    const root = el.closest(".modal");
    const f = UI.collect(root);
    if (!f.name || !/^[A-Za-z0-9_.-]+$/.test(f.name)) { UI.toast("name: letters, digits, . _ - only", "warn"); return; }
    return run(el, async function () {
      try {
        const a = await UI.post("/algos", {
          name: f.name, engine: f.engine, symbol: f.symbol, timeframe: f.timeframe,
          volume: Number(f.volume || 0.01), stop_loss_points: f.stop_loss_points ? Number(f.stop_loss_points) : null,
          take_profit_points: f.take_profit_points ? Number(f.take_profit_points) : null,
          risk_percent: Number(f.risk_percent || 1), magic: Number(f.magic || 0), description: "",
        });
        UI.closeModal(); S().activeAlgo = a.id; UI.toast("algo created", "ok"); UI.go("studio");
      } catch (e) { UI.toast(e.message, "err", 8000); }
    });
  };
  A["save-source"] = function (d, el) {
    const src = document.getElementById("algo-src").value;
    return run(el, async function () {
      try { const r = await UI.put("/algos/" + d.id + "/source", { source: src }); UI.toast(r.error ? "saved with a warning" : "saved ✓", r.error ? "warn" : "ok"); if (r.error) UI.modal("Syntax check", '<div class="warnbox">' + UI.esc(r.error) + "</div>"); }
      catch (e) { UI.toast(e.message, "err", 9000); }
    });
  };
  A["save-algo"] = function (d, el) {
    const box = el.closest(".card");
    const f = UI.collect(box);
    const body = {};
    ["symbol", "timeframe", "comment"].forEach(function (k) { if (f[k]) body[k] = f[k]; });
    ["volume", "risk_percent", "max_daily_loss_percent"].forEach(function (k) { if (f[k] !== "" && f[k] !== undefined) body[k] = Number(f[k]); });
    ["stop_loss_points", "take_profit_points", "trailing_points", "magic", "max_open_positions"].forEach(function (k) {
      if (f[k] !== "" && f[k] !== undefined && f[k] !== null) body[k] = Number(f[k]);
    });
    ["volume_from_risk", "allow_reverse", "one_position_per_symbol"].forEach(function (k) { if (f[k] !== undefined) body[k] = !!f[k]; });
    return run(el, async function () {
      await UI.patch("/algos/" + d.id, body);
      UI.toast("settings applied — restart the engine to take effect", "ok", 5000);
      UI.renderAlgoDetail(d.id);
    });
  };
  A["run-algo"] = function (d, el) {
    return run(el, async function () {
      try {
        const r = await UI.post("/algos/" + d.id + "/run", { lookback_bars: 600, replay: true });
        UI.toast(r.algo_status || "engine started (" + (r.status || "running") + ")", "ok", 5000);
        S().activeAlgo = d.id; UI.refreshStatus().then(function () { UI.render(); });
      } catch (e) { UI.modal("Could not start", '<div class="warnbox">' + UI.esc(e.message) + "</div>" + helpHint(e.message)); }
    });
  };
  function helpHint(msg) {
    const m = String(msg).toLowerCase();
    let hint = "";
    if (m.includes("bridge agent") || m.includes("not connected")) hint = "Start the agent on the machine that runs MT5: <b>Bridge Agent</b> tab has the exact command.";
    else if (m.includes("initialize")) hint = "Login was rejected — verify login/password/server, and that the MT5 terminal on the agent machine is running and logged in.";
    else if (m.includes("windows")) hint = "This service runs on Linux; MT5 needs the Bridge agent (or run this app on the Windows box itself).";
    else if (m.includes("no candles")) hint = "The terminal has not downloaded history for that symbol yet — open the chart in MT5 once, or add the symbol in Settings.";
    return hint ? "<div class='infox tiny' style='margin-top:10px'>" + hint + "</div>" : "";
  }
  A["stop-algo"] = function (d, el) {
    return run(el, async function () {
      try { await UI.post("/algos/" + d.id + "/stop"); UI.toast("engine stopped", "warn"); UI.refreshStatus(); UI.render(); }
      catch (e) { UI.toast(e.message, "err"); }
    });
  };
  A["backtest"] = function (d, el) {
    return run(el, async function () {
      try {
        const src = document.getElementById("algo-src");
        if (src) await UI.put("/algos/" + d.id + "/source", { source: src.value }).catch(function () { });
        const r = await UI.post("/algos/" + d.id + "/backtest?bars=800");
        UI.renderBacktest(r); UI.toast("backtest done: " + r.trade_count + " trades", "ok", 4000);
      } catch (e) { UI.modal("Backtest failed", '<div class="warnbox">' + UI.esc(e.message) + "</div>" + helpHint(e.message)); }
    });
  };
  A["deploy-ea"] = function (d, el) {
    return run(el, async function () {
      try {
        const src = document.getElementById("algo-src");
        if (src) await UI.put("/algos/" + d.id + "/source", { source: src.value }).catch(function () { });
        const r = await UI.post("/algos/" + d.id + "/deploy");
        UI.modal("EA deployment", (r.compiled
          ? '<div class="okbox">compiled with ' + (r.errors || 0) + " errors / " + (r.warnings || 0) + " warnings</div>"
          : '<div class="warnbox">compilation reported ' + (r.errors || "?") + " error(s)</div>") +
          "<dl class='kv' style='margin-top:10px'>" +
          [["source", r.mq5_path], ["binary", r.ex5_path], ["signal file", r.signal_file], ["attach", r.attach ? r.attach.how : ""]].map(function (x) {
            return "<dt>" + x[0] + "</dt><dd>" + UI.esc(x[1] || "—") + "</dd>";
          }).join("") + "</dl>" +
          (r.log ? "<pre class='code wrap tiny' style='margin-top:10px'>" + UI.esc(r.log) + "</pre>" : ""));
        UI.refreshStatus();
      } catch (e) { UI.modal("Deployment failed", '<div class="warnbox">' + UI.esc(e.message) + "</div>" + helpHint(e.message)); }
    });
  };
  A["download-ea"] = function (d) { window.open("/algos/" + d.id + "/ea?download=1&token=" + encodeURIComponent(S().token), "_blank"); };

  // ------------------------------------------------------------------ bridge
  A["rotate-key"] = function (d, el) {
    if (!confirm("Rotating the key disconnects any agent using the old one.")) return;
    return run(el, async function () { await UI.post("/bridge/rotate-key"); UI.toast("new bridge key issued — update the agent", "warn", 6000); UI.render(); });
  };
  A["download-agent"] = function () { window.location.href = "/api/bridge/download?token=" + encodeURIComponent(S().token); };
  document.addEventListener("change", function (ev) {
    if (ev.target.tagName === "SELECT" && ev.target.dataset.action === "set-bars") A["set-bars"]({}, ev.target);
  });

  // ------------------------------------------------------------------ auth screen
  UI.renderAuth = function () {
    const needs = S().boot.needs_setup;
    document.body.innerHTML =
      '<div class="auth-screen"><form class="auth-card" onsubmit="return false">' +
      '<div class="row" style="gap:12px"><span class="logo" style="width:42px;height:42px;font-size:15px">M5</span>' +
      "<div><h1>MT5 Web Console</h1><div class='muted tiny'>MetaTrader 5 control plane</div></div></div>" +
      "<div class='lead'>" + (needs
        ? "First run: choose the passcode that protects this dashboard. Everything here can place <b>real orders</b> on a live account, so treat it like a trading password."
        : "Enter the app passcode to continue.") + "</div>" +
      '<div class="field"><label>' + (needs ? "Choose a passcode (min 6 chars)" : "Passcode") + "</label>" +
      '<input class="input" id="pass-input" type="password" autofocus placeholder="' + (needs ? "e.g. tr4de-2026" : "••••••••") + '" /></div>' +
      '<button class="btn green" data-action="login">' + (needs ? "create & sign in" : "sign in") + "</button>" +
      '<div class="tiny muted">Running MT5 on Linux? The terminal itself needs Wine + the Bridge agent — see the Bridge tab after signing in.</div>' +
      "</form></div>";
    document.getElementById("pass-input").addEventListener("keydown", function (e) {
      if (e.key === "Enter") { e.preventDefault(); A.login(); }
    });
    document.getElementById("pass-input").focus();
  };

  // ------------------------------------------------------------------ boot
  UI.boot = async function () {
    if (!S().token) { UI.renderAuth(); return; }
    try {
      const st = await UI.get("/state");
      UI.restoreShell();
      UI.applyState(st);
      UI.setAlgos(st.algos || []);
      const m = (location.hash || "").replace("#/", "");
      UI.state.view = ["overview", "markets", "trade", "studio", "positions", "bridge", "settings"].includes(m) ? m : "overview";
      UI.go(UI.state.view);
      UI.connectStream();
      UI.refreshTradeState(true).catch(function () { });
      UI.auditList().catch(function () { });
      if (UI._timer) clearInterval(UI._timer);
      UI._timer = setInterval(function () {
        if (document.hidden) return;
        UI.refreshStatus().catch(function () { });
        UI.auditList().catch(function () { });
      }, 20000);
      window.addEventListener("hashchange", function () {
        const v = (location.hash || "").replace("#/", "");
        if (v && v !== S().view) UI.go(v);
      });
    } catch (e) {
      if (String(e.message).includes("401") || String(e.message).includes("sign in")) { S().token = ""; sessionStorage.removeItem("m5tok"); }
      UI.renderAuth();
      UI.toast(e.message, "err");
    }
  };

  UI.restoreShell = function () {
    if (document.getElementById("app")) return;
    location.reload();
  };

  // start
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", UI.boot);
  else UI.boot();
})();
