//+------------------------------------------------------------------+
//| XAUUSD_EmaCross.mq5 — Pure EMA 9/12 Crossover (M15)               |
//| BUY when EMA9 crosses ABOVE EMA12, SELL on cross BELOW.          |
//| Opposite cross closes + reverses. Fixed lot. No SL/TP, no RSI,   |
//| no session filter — crossover ONLY.                              |
//| RENKO USE: generate a Renko-50 offline chart with a Renko        |
//| generator EA, then attach this EA to that offline chart.         |
//+------------------------------------------------------------------+
#property copyright "MetaTrader5 repo"
#property version   "2.00"
#property description "Pure EMA 9/12 crossover for XAUUSD M15. Attach to XAUUSD M15 chart."

#include <Trade/Trade.mqh>
CTrade trade;

//--- inputs
input int      InpEmaFast   = 9;        // EMA fast
input int      InpEmaSlow   = 12;       // EMA slow
input double   InpLots      = 0.10;     // Fixed lot
input double   InpMaxSpreadPoints = 60; // Max spread (points) safety
input long     InpMagic     = 20250302; // Magic number
input string   InpTradeComment = "EMAX"; // Order comment

//--- handles
int g_emaFast, g_emaSlow;
datetime g_lastBar = 0;

//+------------------------------------------------------------------+
//| Init                                                             |
//+------------------------------------------------------------------+
int OnInit()
  {
   g_emaFast = iMA(_Symbol, PERIOD_CURRENT, InpEmaFast, 0, MODE_EMA, PRICE_CLOSE);
   g_emaSlow = iMA(_Symbol, PERIOD_CURRENT, InpEmaSlow, 0, MODE_EMA, PRICE_CLOSE);
   if(g_emaFast == INVALID_HANDLE || g_emaSlow == INVALID_HANDLE)
     {
      Print("Indicator handle creation failed");
      return INIT_FAILED;
     }
   trade.SetExpertMagicNumber(InpMagic);
   trade.SetDeviationInPoints(20);
   return INIT_SUCCEEDED;
  }

//+------------------------------------------------------------------+
//| Tick — act once per new bar, on closed-bar crossover             |
//+------------------------------------------------------------------+
void OnTick()
  {
   datetime curBar = iTime(_Symbol, PERIOD_CURRENT, 0);
   if(curBar == g_lastBar) return;
   g_lastBar = curBar;

   double f[], s[];
   if(CopyBuffer(g_emaFast, 0, 1, 2, f) < 2) return;
   if(CopyBuffer(g_emaSlow, 0, 1, 2, s) < 2) return;

   bool crossUp = (f[1] <= s[1] && f[0] > s[0]);
   bool crossDn = (f[1] >= s[1] && f[0] < s[0]);
   if(!crossUp && !crossDn) return;

   long spread = SymbolInfoInteger(_Symbol, SYMBOL_SPREAD);
   if(spread > InpMaxSpreadPoints)
      return;

   ulong tk = FindPosition();
   long ptype = -1;
   if(tk != 0)
      ptype = PositionGetInteger(POSITION_TYPE);

   // same direction already open -> nothing to do
   if(crossUp && ptype == POSITION_TYPE_BUY) return;
   if(crossDn && ptype == POSITION_TYPE_SELL) return;

   // close opposite, then open new (reverse)
   if(tk != 0)
     {
      if(!trade.PositionClose(tk))
         return;
     }

   double vol = NormVolume(InpLots);
   if(vol <= 0) return;
   double ask = SymbolInfoDouble(_Symbol, SYMBOL_ASK);
   double bid = SymbolInfoDouble(_Symbol, SYMBOL_BID);

   if(crossUp)
      trade.Buy(vol, _Symbol, ask, 0, 0, InpTradeComment);
   else if(crossDn)
      trade.Sell(vol, _Symbol, bid, 0, 0, InpTradeComment);
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
//| Normalize lot to broker limits                                   |
//+------------------------------------------------------------------+
double NormVolume(double vol)
  {
   double vMin  = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MIN);
   double vMax  = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MAX);
   double vStep = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_STEP);
   vol = MathFloor(vol / vStep) * vStep;
   vol = MathMin(MathMax(vol, vMin), vMax);
   return NormalizeDouble(vol, 2);
  }
//+------------------------------------------------------------------+
