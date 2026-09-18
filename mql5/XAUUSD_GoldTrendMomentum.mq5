//+------------------------------------------------------------------+
//| XAUUSD_GoldTrendMomentum.mq5  — Gold Trend-Momentum v1 (M15)      |
//| Trend: Close > EMA20 > EMA50 -> LONG only (mirror for SHORT)     |
//| Trigger: RSI(14) crosses 50 in trend direction (closed bars)     |
//| Session: entries only StartHour-EndHour server time              |
//| SL = SL_ATR x ATR(14), TP = TP_ATR x ATR(14), 1 position, % risk  |
//+------------------------------------------------------------------+
#property copyright "MetaTrader5 repo"
#property version   "1.00"
#property description "Gold Trend-Momentum v1 for XAUUSD M15. Attach to XAUUSD M15 chart."

#include <Trade/Trade.mqh>
CTrade trade;

//--- inputs
input int      InpEmaFast    = 20;      // EMA fast
input int      InpEmaSlow    = 50;      // EMA slow
input int      InpRsiPeriod  = 14;      // RSI period
input double   InpRsiMid     = 50.0;    // RSI midline
input int      InpAtrPeriod  = 14;      // ATR period
input double   InpSL_ATR     = 2.0;     // SL = x ATR
input double   InpTP_ATR     = 4.0;     // TP = x ATR
input int      InpStartHour  = 7;       // Session start (server time hour)
input int      InpEndHour    = 21;      // Session end (server time hour)
input double   InpRiskPct    = 1.0;     // Risk per trade (% of balance)
input double   InpMaxSpreadPoints = 60; // Max spread (points) to allow entry
input long     InpMagic      = 20250301;// Magic number
input string   InpTradeComment = "GTMv1";// Order comment

//--- handles
int g_emaFast, g_emaSlow, g_rsi, g_atr;
datetime g_lastBar = 0;

//+------------------------------------------------------------------+
//| Init                                                             |
//+------------------------------------------------------------------+
int OnInit()
  {
   g_emaFast = iMA(_Symbol, PERIOD_CURRENT, InpEmaFast, 0, MODE_EMA, PRICE_CLOSE);
   g_emaSlow = iMA(_Symbol, PERIOD_CURRENT, InpEmaSlow, 0, MODE_EMA, PRICE_CLOSE);
   g_rsi     = iRSI(_Symbol, PERIOD_CURRENT, InpRsiPeriod, PRICE_CLOSE);
   g_atr     = iATR(_Symbol, PERIOD_CURRENT, InpAtrPeriod);
   if(g_emaFast == INVALID_HANDLE || g_emaSlow == INVALID_HANDLE ||
      g_rsi == INVALID_HANDLE || g_atr == INVALID_HANDLE)
     {
      Print("Indicator handle creation failed");
      return INIT_FAILED;
     }
   trade.SetExpertMagicNumber(InpMagic);
   trade.SetDeviationInPoints(20);
   return INIT_SUCCEEDED;
  }

//+------------------------------------------------------------------+
//| Tick                                                             |
//+------------------------------------------------------------------+
void OnTick()
  {
   datetime curBar = iTime(_Symbol, PERIOD_CURRENT, 0);
   if(curBar == g_lastBar) return;   // act once per new bar
   g_lastBar = curBar;

   if(PositionSelectByTicket(FindPosition()))
      return;                        // one position at a time

   if(!InSession())
      return;

   long spread = SymbolInfoInteger(_Symbol, SYMBOL_SPREAD);
   if(spread > InpMaxSpreadPoints)
      return;

   double emaF[], emaS[], rsi[], atr[], close[];
   if(CopyBuffer(g_emaFast, 0, 1, 2, emaF) < 2) return;
   if(CopyBuffer(g_emaSlow, 0, 1, 2, emaS) < 2) return;
   if(CopyBuffer(g_rsi, 0, 1, 2, rsi) < 2) return;
   if(CopyBuffer(g_atr, 0, 1, 1, atr) < 1) return;
   if(CopyClose(_Symbol, PERIOD_CURRENT, 1, 1, close) < 1) return;

   bool uptrend   = (close[0] > emaF[0] && emaF[0] > emaS[0]);
   bool downtrend = (close[0] < emaF[0] && emaF[0] < emaS[0]);
   bool longSig   = uptrend && (rsi[1] < InpRsiMid && rsi[0] >= InpRsiMid);
   bool shortSig  = downtrend && (rsi[1] > InpRsiMid && rsi[0] <= InpRsiMid);
   if(!longSig && !shortSig) return;

   double slDist = InpSL_ATR * atr[0];
   double tpDist = InpTP_ATR * atr[0];
   double vol = CalcVolume(slDist);
   if(vol <= 0) return;

   double ask = SymbolInfoDouble(_Symbol, SYMBOL_ASK);
   double bid = SymbolInfoDouble(_Symbol, SYMBOL_BID);
   int digits = (int)SymbolInfoInteger(_Symbol, SYMBOL_DIGITS);

   if(longSig)
     {
      double sl = NormalizeDouble(ask - slDist, digits);
      double tp = NormalizeDouble(ask + tpDist, digits);
      trade.Buy(vol, _Symbol, ask, sl, tp, InpTradeComment);
     }
   else if(shortSig)
     {
      double sl = NormalizeDouble(bid + slDist, digits);
      double tp = NormalizeDouble(bid - tpDist, digits);
      trade.Sell(vol, _Symbol, bid, sl, tp, InpTradeComment);
     }
  }

//+------------------------------------------------------------------+
//| Session filter (server time). Adjust hours for broker GMT offset. |
//| Backtest used 07:00-21:00 GMT. E.g. GMT+2 broker -> 09-23.        |
//+------------------------------------------------------------------+
bool InSession()
  {
   MqlDateTime dt;
   TimeToStruct(TimeTradeServer(), dt);
   int h = dt.hour;
   if(InpStartHour <= InpEndHour)
      return (h >= InpStartHour && h < InpEndHour);
   return (h >= InpStartHour || h < InpEndHour);
  }

//+------------------------------------------------------------------+
//| Find our position                                                |
//+------------------------------------------------------------------+
ulong FindPosition()
  {
   for(int i = PositionsTotal() - 1; i >= 0; i--)
     {
      ulong tk = PositionGetTicket(i);
      if(tk == 0) continue;
      string sym = PositionGetString(POSITION_SYMBOL);
      long mg = PositionGetInteger(POSITION_MAGIC);
      if(sym == _Symbol && mg == InpMagic)
         return tk;
     }
   return 0;
  }

//+------------------------------------------------------------------+
//| % risk position sizing                                           |
//+------------------------------------------------------------------+
double CalcVolume(double slDistPrice)
  {
   if(slDistPrice <= 0) return 0;
   double balance  = AccountInfoDouble(ACCOUNT_BALANCE);
   double riskMoney = balance * InpRiskPct / 100.0;
   double tickVal  = SymbolInfoDouble(_Symbol, SYMBOL_TRADE_TICK_VALUE);
   double tickSize = SymbolInfoDouble(_Symbol, SYMBOL_TRADE_TICK_SIZE);
   if(tickVal <= 0 || tickSize <= 0) return 0;
   double lossPerLot = slDistPrice / tickSize * tickVal;
   if(lossPerLot <= 0) return 0;
   double vol = riskMoney / lossPerLot;

   double vMin  = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MIN);
   double vMax  = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MAX);
   double vStep = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_STEP);
   vol = MathFloor(vol / vStep) * vStep;
   vol = MathMin(MathMax(vol, vMin), vMax);
   return NormalizeDouble(vol, 2);
  }
//+------------------------------------------------------------------+
