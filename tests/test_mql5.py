"""MQL5 code generation, signal-file format and compile-log parsing."""

from __future__ import annotations

import pytest


def test_generated_ea_has_no_leftover_placeholders(isolated_env):
    from mt5web import MQL5

    rec = {
        "id": "algo_1", "name": "My Algo.1", "symbol": "EURUSD", "timeframe": "M5",
        "magic": 991, "volume": 0.02, "stop_loss_points": 250, "take_profit_points": 400,
        "allow_reverse": True, "comment": "my algo", "description": 'a "quoted" note',
    }
    src = MQL5.generate_ea(rec)
    assert "@@" not in src, "template placeholders were not all replaced"
    assert "MT5Web_My_Algo_1.mq5" in src
    assert 'input long    InpMagic           = 991;' in src
    assert 'InpSymbol          = "EURUSD"' in src
    assert "InpTimeframe       = 5" in src          # M5 -> 5 minutes
    assert "OnTick()" in src and "OnInit()" in src and "OnDeinit" in src
    assert "#include <Trade/Trade.mqh>" in src      # CTrade needs the include
    assert "CTrade trade;" in src
    assert "FileReadString(h)" in src
    assert src.count("OnTick") >= 1
    # balanced braces -> the mock/real compiler will be happy
    assert src.count("{") == src.count("}"), "unbalanced braces in generated source"
    assert "#property strict" not in src            # that directive is MQL4-only
    assert 'a "quoted" note'.replace('"', "'") in src


def test_mql5_source_passthrough_for_pure_eas(isolated_env):
    from mt5web import MQL5

    mine = "//+------------------------------------------------------------------+\nint OnInit(){return 0;}\nvoid OnTick(){}\n"
    out = MQL5.generate_ea({"id": "x", "name": "Pure", "symbol": "XAUUSD", "timeframe": "H1"}, mine)
    assert out == mine  # user EA code is deployed verbatim, never wrapped


def test_signal_file_roundtrip(isolated_env):
    from mt5web import MQL5

    rec = {
        "id": "a", "name": "Sized", "symbol": "XAUUSD", "timeframe": "M15", "volume": 0.05,
        "stop_loss_points": 400, "take_profit_points": 800, "trailing_points": 150,
        "max_spread_points": 35, "max_daily_loss_percent": 3.0, "max_open_positions": 2,
        "risk_percent": 1.5, "volume_from_risk": True, "magic": 4242,
    }
    text = MQL5.signal_payload(rec)
    parsed = MQL5.parse_signal_text(text)
    assert parsed["signal"] == "none"
    assert parsed["kill"] == "0"
    assert parsed["sl_points"] == "400" and parsed["tp_points"] == "800"
    assert parsed["trail_points"] == "150" and parsed["max_spread"] == "35"
    assert parsed["risk_percent"] == "1.5" and parsed["magic"] == "4242"
    assert parsed["max_positions"] == "2"
    assert int(parsed["updated"]) > 1_700_000_000


def test_signal_lines_explicit(isolated_env):
    from mt5web import MQL5

    text = MQL5.signal_lines("buy", volume=0.1, kill=True, note="manual from dashboard")
    parsed = MQL5.parse_signal_text(text)
    assert parsed["signal"] == "buy" and parsed["kill"] == "1" and parsed["volume"] == "0.1"
    assert parsed["note"] == "manual from dashboard"
    # unknown actions must never be written as a tradeable signal
    assert MQL5.parse_signal_text(MQL5.signal_lines("hodl"))["signal"] == "none"


def test_file_names_are_sandbox_safe(isolated_env):
    from mt5web import MQL5

    rec = {"name": "weird/../name!"}
    mq5, ex5, sig = MQL5.file_names(rec)
    assert ".." not in mq5 + ex5 + sig
    assert mq5 == "MQL5/Experts/MT5Web_weird____name_.mq5"
    assert ex5.endswith(".ex5") and sig.endswith(".txt") and sig.startswith("MQL5/Files/")


def test_compile_log_parsing(isolated_env):
    from mt5web import MQL5

    ok = "compilation log started\nResult: 0 warnings, 0 errors, 43 ms elapsed, cpu='X64 Regular'"
    parsed = MQL5.parse_compile_log(ok)
    assert parsed["errors"] == 0 and parsed["warnings"] == 0 and parsed["first_error"] == ""

    bad = (
        "MT5Web_X.mq5(12,3) : error : 'foo' - undeclared identifier\n"
        "MT5Web_X.mq5(20,1) : warning : possible loss of data\n"
        "Result: 1 warnings, 1 errors, 40 ms elapsed"
    )
    parsed = MQL5.parse_compile_log(bad)
    assert parsed["errors"] == 1 and parsed["warnings"] == 1
    assert "undeclared identifier" in parsed["first_error"]
    assert MQL5.parse_compile_log("")["errors"] == 0


@pytest.mark.parametrize("tf,minutes", [("M1", 1), ("M5", 5), ("M15", 15), ("H1", 60), ("H4", 240), ("D1", 1440)])
def test_timeframe_mapping(isolated_env, tf, minutes):
    from mt5web import MQL5

    src = MQL5.generate_ea({"id": "i", "name": "n", "symbol": "EURUSD", "timeframe": tf})
    assert f"InpTimeframe       = {minutes}" in src
