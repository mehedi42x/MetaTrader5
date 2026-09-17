/* MT5 Web Console — Positions, History, Bridge agent, Settings pages + auth boot. */
(function () {
  "use strict";
  const UI = window.UI;
  const S = function () { return UI.state; };

  // ------------------------------------------------------------------ POSITIONS
  UI.views.positions = async function (host) {
    const st = S();
    await UI.refreshTradeState(true).catch(function () { });
    let hist = { deals: [], summary: {} };
    try { hist = await UI.get("/trade/history?days=7"); } catch (e) { hist.error = e.message; }
    const ts = st.tradeState;
    const info = ts.account || {};
    host.innerHTML =
      '<div class="grid cols-4">' +
      [["Balance", UI.num(info.balance)], ["Equity", UI.num(info.equity)],
      ["Margin level", info.margin_level ? UI.num(info.margin_level, 0) + "%" : "—"],
      ["Floating", UI.signed(ts.floating_profit || 0)]]
        .map(function (r) { return '<div class="card kpi"><span class="k-label">' + r[0] + '</span><span class="k-value">' + r[1] + "</span></div>"; }).join("") +
      "</div>" +
      '<div class="card"><div class="row between"><h3>Open positions &amp; pending orders</h3>' +
      "<div class='row'><button class='btn sm ghost' data-action='refresh-trade'>↻ refresh</button>" +
      "<button class='btn sm red' data-action='close-all'>close all</button></div></div>" +
      UI.positionTable(ts.positions || [], ts.orders || []) +
      (st.tradeStateError ? '<div class="warnbox tiny">' + UI.esc(st.tradeStateError) + "</div>" : "") + "</div>" +

      '<div class="split"><div class="card"><h3>Deals <small>last 7 days</small></h3>' +
      (hist.deals && hist.deals.length
        ? '<div class="tbl-wrap"><table class="tbl"><thead><tr><th>time</th><th>symbol</th><th>side</th><th>entry</th><th class="num">volume</th><th class="num">price</th><th class="num">P/L</th><th>comment</th></tr></thead><tbody>' +
        hist.deals.slice(0, 120).map(function (d) {
          return "<tr><td class='tiny mono muted nowrap'>" + UI.dt(d.time) + "</td><td class='sym'>" + UI.esc(d.symbol) + "</td>" +
            "<td><span class='badge " + (d.type === "buy" ? "run" : "err") + "'>" + d.type + "</span></td>" +
            "<td class='tiny mono'>" + d.entry + "</td><td class='num'>" + UI.num(d.volume, 2) + "</td>" +
            "<td class='num'>" + d.price + "</td><td class='num " + UI.cls(d.profit) + "'>" + UI.signed(d.profit) + "</td>" +
            "<td class='tiny muted'>" + UI.esc(d.comment || "") + "</td></tr>";
        }).join("") + "</tbody></table></div>"
        : '<div class="empty">' + (hist.error ? UI.esc(hist.error) : "no deals in this window") + "</div>") +
      "</div>" +
      '<div class="card"><h3>Summary</h3><dl class="kv">' +
      [["closed trades", hist.summary.closed || 0], ["wins", hist.summary.wins || 0], ["losses", hist.summary.losses || 0],
      ["win rate", (hist.summary.win_rate || 0) + "%"], ["net profit", UI.signed(hist.summary.net_profit || 0)],
      ["algo-trading allowed", (S().status && S().status.agents && S().status.agents[0] && S().status.agents[0].initialized) ? "yes" : "unknown"]]
        .map(function (r) { return "<dt>" + r[0] + "</dt><dd>" + UI.esc(r[1]) + "</dd>"; }).join("") +
      "</dl></div></div>";
  };

  // ------------------------------------------------------------------ BRIDGE
  UI.views.bridge = async function (host) {
    let b;
    try { b = await UI.get("/bridge"); } catch (e) { b = { error: e.message, agents: [] }; }
    let plat = null;
    try { plat = await UI.get("/platform"); } catch (e) { plat = null; }
    S().bridge = b;
    const local = (S().status || {});
    host.innerHTML =
      '<div class="card"><h3>Why a bridge? <small>MT5 is Windows-only</small></h3>' +
      '<div class="infox">The <b>MetaTrader5</b> python package ships Windows-only wheels — a Render (Ubuntu) service cannot import it, so it cannot ' +
      "drive the terminal directly. This web app is therefore split in two: the <b>control plane</b> you are using now, and a tiny <b>Bridge agent</b> that runs " +
      "next to your terminal and executes the MT5 calls on request (one outbound WebSocket, no ports opened).</div>" +
      (local.mt5_package_installed ? '<div class="okbox">This host can import MetaTrader5 directly — you can skip the agent and run the app on the same Windows machine.</div>' : "") +
      platformNote(plat) +
      "</div>" +

      '<div class="card"><h3>Running MT5 on a Linux box <small>official Wine bootstrap</small></h3>' +
      '<div class="infox">MetaQuotes do ship a Linux installer (<code>mt5linux.sh</code>), but it only bootstraps <b>Wine</b>: it installs ' +
      "<code>winehq-staging</code>, creates the <code>~/.mt5</code> prefix and then opens the normal <b>Windows</b> <code>mt5setup.exe</code> wizard (needs sudo, a desktop, and a reboot). " +
      "There is no native Linux build of MT5, and the python package still will not import under Linux <code>python3</code> — inside Wine you need Wine's own Windows python.</div>" +
      "<pre class='code wrap'># one-shot on your own Linux host (VM / VPS / home box) — not on Render\n" +
      "sudo apt-get install -y xvfb cabextract winetricks\n" +
      "bash agents/setup-mt5-wine.sh --run\n" +
      "# then: xvfb-run wine ~/.mt5/drive_c/Program\\ Files/MetaTrader\\ 5/terminal64.exe /config:mt5web.ini</pre>" +
      "<div class='tiny muted'>Use a Wine <b>11.x</b> build (MetaQuotes report Wine 10.0 and 11.0 do not work), enable " +
      "<i>Tools → Options → Expert Advisors → Allow algorithmic trading</i>, and start the agent with the Wine python: " +
      "<code>wine C:\\python312\\python.exe C:\\agent\\main.py --url … --key …</code>. Self-hosted Docker can bake all of this in: " +
      "<code>docker build --build-arg WITH_MT5=1 -t mt5web .</code></div>" +
      "</div>" +

      '<div class="split"><div class="card"><h3>1 · install &amp; run the agent</h3>' + steps(b) + "</div>" +
      '<div class="card"><h3>2 · agent status</h3>' + agentRows(b.agents || []) +
      "<div class='row'><button class='btn sm ghost' data-action='refresh'>↻ refresh</button>" +
      "<button class='btn sm ghost' data-action='rotate-key'>rotate bridge key</button>" +
      "<button class='btn sm ghost' data-action='download-agent'>⬇ agent bundle (.zip)</button></div></div></div>" +

      '<div class="card"><h3>Terminal log <small>streamed by the agent</small></h3><div class="log" id="mt5-log-box">' +
      ((S().logFeed || []).length ? "" : '<span class="muted">no log lines yet — the agent tails MQL5\\Logs and Logs\\ from your terminal</span>') +
      "</div></div>";
    UI.renderMt5Log();
  };

  function platformNote(plat) {
    if (!plat) return "";
    const s = plat.system || {};
    const bits = [];
    bits.push(s.is_windows ? "host: Windows (native MT5 possible)" : "host: " + (s.system || "?") + " " + (s.release || ""));
    bits.push(plat.mt5_package ? "MetaTrader5 package: importable" : "MetaTrader5 package: not importable here");
    bits.push("wine: " + (plat.wine_binary ? "found" : "absent"));
    bits.push("Xvfb: " + (plat.xvfb_binary ? "found" : "absent"));
    bits.push("MT5 prefix: " + (plat.mt5_in_prefix ? plat.wine_prefix : "none"));
    const cls = plat.can_run_mt5_natively ? "okbox" : "warnbox";
    return "<div class='" + cls + "'>" + UI.esc(plat.verdict || "") + "<div class='tiny muted' style='margin-top:6px'>" +
      bits.map(UI.esc).join(" · ") + "</div></div>";
  }

  function steps(b) {
    const snip = (b && b.install_snippets) || {};
    const key = (b && b.bridge_key) || "";
    const origin = (b && b.origin) || location.origin;
    return '<div class="steps">' +
      step(1, "Download the agent", "<div class='row'><button class='btn sm' data-action='download-agent'>mt5-bridge-agent.zip</button>" +
        "<span class='tiny muted'>contains agents/agent/main.py, requirements and a .bat launcher</span></div>") +
      step(2, "Install MT5 + python deps", "on the Windows machine that runs MetaTrader 5:<pre class='code wrap'>cd mt5-bridge-agent\npython -m pip install -r agent\\requirements.txt</pre>" +
        "<span class='tiny muted'>python 3.9–3.12 64-bit. If MT5 is not installed yet, run the installer with <code>--install-mt5</code>.</span>") +
      step(3, "Start it", "<pre class='code wrap'>" + UI.esc("python agent\\main.py --url " + origin + "/ws/agent --key " + key + " --name " + (navigator.platform || "pc")) + "</pre>" +
        "<div class='tiny muted'>Linux/Wine host: <code>wine C:\\python312\\python.exe C:\\agent\\main.py --url " + UI.esc(origin) + "/ws/agent --key " + UI.esc(key) + "</code></div>" +
        "<div class='row'><button class='btn xs ghost' data-action='copy' data-text='" + UI.esc("python agent\\main.py --url " + origin + "/ws/agent --key " + key) + "'>copy command</button>" +
        "<button class='btn xs ghost' data-action='copy' data-text='" + UI.esc(key) + "'>copy key only</button></div>") +
      step(4, "Bind your MT5 account", "open <b>Settings → MT5 account</b>, enter login / password / server and press connect — the credentials are forwarded to the agent, encrypted at rest here.") +
      "</div>";
  }
  function step(n, title, body) {
    return '<div class="step"><span class="n">' + n + '</span><div><b style="font-size:13px">' + title + "</b><div class='tiny muted' style='margin-top:4px'>" + body + "</div></div></div>";
  }
  function agentRows(agents) {
    if (!agents.length) return '<div class="warnbox">no agent connected yet. Start it and this panel turns green automatically.</div>';
    return agents.map(function (a) {
      return '<dl class="kv">' +
        [["agent", a.name], ["os", (a.os || "?") + " " + (a.os_release || "")], ["python", a.python],
        ["MT5 package", a.mt5_available ? "installed" : "MISSING (pip install MetaTrader5)"], ["terminal build", a.mt5_version || "—"],
        ["data folder", a.data_folder || "—"], ["logged in", a.initialized ? "yes" : "no"],
        ["rpc calls", (a.rpc_count || 0) + " (errors " + (a.rpc_errors || 0) + ")"], ["last seen", UI.ago(a.last_seen)]]
          .map(function (r) { return "<dt>" + r[0] + "</dt><dd>" + UI.esc(r[1]) + "</dd>"; }).join("") +
        "</dl>";
    }).join('<hr class="hr" />');
  }

  // ------------------------------------------------------------------ SETTINGS
  UI.views.settings = async function (host) {
    const st = S();
    let accounts = { items: [], default_account_id: null };
    try { accounts = await UI.get("/accounts"); } catch (e) { }
    const status = st.status || {};
    host.innerHTML =
      '<div class="split"><div class="card"><h3>MT5 account <small>login · password · server</small></h3>' +
      '<div id="acct-form">' + UI.accountForm((status.account || {})) + "</div>" +
      '<div class="row"><button class="btn green" data-action="save-account">save &amp; connect</button>' +
      (accounts.items.length ? "<button class='btn ghost' data-action='disconnect'>disconnect</button>" : "") +
      "<span class='spacer'></span><span class='tiny muted'>password is encrypted at rest (AES-CTR + HMAC)</span></div>" +
      '<div class="hr"></div><div class="tiny muted">saved accounts</div>' +
      accountList(accounts) + "</div>" +

      '<div class="stack"><div class="card"><h3>Symbols</h3>' +
      '<div class="chips">' + st.symbols.map(function (s) {
        return '<span class="chip">' + s.name + '<span class="x" data-action="del-symbol" data-symbol="' + s.name + '">×</span></span>';
      }).join("") + "</div>" +
      '<div class="row"><input class="input" id="new-syms" placeholder="EURJPY, NZDUSD, USOIL…" />' +
      "<button class='btn sm' data-action='add-symbols'>add</button></div>" +
      '<div class="tiny muted">Adding a symbol also selects it in the terminal Market Watch so quotes/candles start flowing.</div></div>' +

      '<div class="card"><h3>Trading limits</h3><div class="field-grid">' +
      "<div class='field'><label>Max lots per order</label><input class='input' id='max-lot' data-num='1' value='" + (status.max_lot || 5) + "' /></div>" +
      "<div class='field'><label>Poll interval (s)</label><input class='input' id='tick-int' data-num='1' step='0.5' value='" + ((status.tick_interval) || 1.5) + "' /></div>" +
      "<div class='field'><label>Chart timeframe</label><select class='input' id='chart-tf'>" +
      ["M1", "M5", "M15", "H1", "H4"].map(function (t) { return "<option " + (t === st.timeframe ? "selected" : "") + ">" + t + "</option>"; }).join("") + "</select></div>" +
      "</div>" +
      '<div class="row" style="margin-top:8px">' + toggle("allow_live", "allow live orders from this app", status.allow_live_trading !== false) +
      "<span class='spacer'></span><button class='btn sm green' data-action='save-settings'>apply</button></div></div>" +

      '<div class="card"><h3>App secret</h3><div class="tiny muted">Session tokens and stored passwords are derived from <code>MT5WEB_SECRET</code> (Render env var). ' +
      "Without it a random key is persisted in the data folder — set it if you attach a disk so tokens survive redeploys.</div>" +
      '<div class="row"><input class="input" id="new-pass" type="password" placeholder="change app passcode" /></div>' +
      '<div class="row"><button class="btn sm ghost" data-action="change-passcode">change passcode</button></div></div>' +
      "</div></div>";
  };

  function accountList(accounts) {
    if (!accounts.items.length) return '<div class="empty tiny">no MT5 account saved yet</div>';
    return '<div class="tbl-wrap" style="max-height:190px"><table class="tbl"><thead><tr><th>name</th><th>server</th><th>login</th><th>status</th><th></th></tr></thead><tbody>' +
      accounts.items.map(function (a) {
        return "<tr><td>" + UI.esc(a.name || "") + (a.is_default ? " <span class='badge info'>default</span>" : "") + "</td>" +
          "<td class='mono tiny'>" + UI.esc(a.server) + "</td><td class='mono'>" + a.login + "</td>" +
          "<td><span class='badge " + (a.status === "connected" ? "run" : a.status === "error" ? "err" : "stop") + "'>" + a.status + "</span>" +
          (a.last_error ? "<div class='tiny neg' style='max-width:220px'>" + UI.esc(a.last_error.slice(0, 90)) + "</div>" : "") + "</td>" +
          "<td class='nowrap'><button class='btn xs ghost' data-action='connect-account' data-id='" + a.id + "'>connect</button> " +
          "<button class='btn xs ghost' data-action='del-account' data-id='" + a.id + "'>delete</button></td></tr>";
      }).join("") + "</tbody></table></div>";
  }
})();
