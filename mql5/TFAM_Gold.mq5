//+------------------------------------------------------------------+
//|  TFAM_Gold.mq5                                                    |
//|  Tick-Flow Absorption Momentum  -  XAUUSD 0.01 lot @ 800x         |
//|                                                                   |
//|  NO indicators. NO price action. NO candles.                      |
//|  Pure tick microstructure: flow, efficiency, intensity, spread.   |
//|  This is a 1:1 port of src/strategy.py (TFAM).                    |
//+------------------------------------------------------------------+
#property copyright "TFAM"
#property version   "1.00"
#property strict

#include <Trade\Trade.mqh>
CTrade trade;

//--- position / account
input double InpLot              = 0.01;
input long   InpMagic            = 880001;
input int    InpSlippagePoints   = 20;

//--- signal horizons (seconds)
input double TauFlow             = 3.0;
input double TauEff              = 6.0;
input double TauIntensFast       = 5.0;
input double TauIntensSlow       = 900.0;
input double TauVol              = 30.0;
input double TauSpread           = 300.0;
input double TauFlowVar          = 1800.0;

//--- entry thresholds
input double FlowZ               = 2.15;
input double EffMin              = 0.42;
input double IntensMult          = 1.55;
input double SpreadMult          = 1.25;
input double SpreadEdgeFrac      = 0.55;

//--- exits (multiples of live micro-volatility)
input double TP_K                = 26.0;
input double SL_K                = 18.0;
input double TrailArmK           = 14.0;
input double TrailK              = 8.0;
input double FlipZ               = 1.30;
input double MaxHoldSeconds      = 90.0;

//--- guards
input double CooldownSeconds     = 8.0;
input int    BlockHourFrom       = 21;   // server time
input int    BlockHourTo         = 22;
input double DailyLossStopPct    = 4.0;
input double DailyProfitStopPct  = 10.0;
input int    MaxTradesPerDay     = 400;
input double MinVol              = 0.004;
input int    WarmupTicks         = 5000;

//--- state
double  g_prevMid=0, g_prevTs=0;
double  g_flow=0, g_flowVar=1.0, g_net=0, g_disp=0;
double  g_iFast=0, g_iSlow=0, g_vol=0.02, g_spreadEwma=0.20;
long    g_warm=0;
double  g_lastExitTs=-1e18;
double  g_entryVol=0, g_best=0, g_trailLevel=0;
bool    g_trailActive=false;
double  g_dayStartEquity=0; int g_dayTrades=0; datetime g_day=0; bool g_dayLocked=false;

//+------------------------------------------------------------------+
int OnInit()
{
   trade.SetExpertMagicNumber(InpMagic);
   trade.SetDeviationInPoints(InpSlippagePoints);
   trade.SetTypeFillingBySymbol(_Symbol);
   g_dayStartEquity = AccountInfoDouble(ACCOUNT_EQUITY);
   Print("TFAM initialised on ", _Symbol);
   return INIT_SUCCEEDED;
}

//+------------------------------------------------------------------+
bool HasPos(int &dir, double &openPrice, datetime &openTime)
{
   for(int i=PositionsTotal()-1; i>=0; i--)
   {
      ulong tk = PositionGetTicket(i);
      if(tk==0) continue;
      if(!PositionSelectByTicket(tk)) continue;
      if(PositionGetString(POSITION_SYMBOL)!=_Symbol) continue;
      if(PositionGetInteger(POSITION_MAGIC)!=InpMagic) continue;
      dir = (PositionGetInteger(POSITION_TYPE)==POSITION_TYPE_BUY)? 1 : -1;
      openPrice = PositionGetDouble(POSITION_PRICE_OPEN);
      openTime  = (datetime)PositionGetInteger(POSITION_TIME);
      return true;
   }
   return false;
}

void CloseAll(string why)
{
   for(int i=PositionsTotal()-1; i>=0; i--)
   {
      ulong tk = PositionGetTicket(i);
      if(!PositionSelectByTicket(tk)) continue;
      if(PositionGetString(POSITION_SYMBOL)!=_Symbol) continue;
      if(PositionGetInteger(POSITION_MAGIC)!=InpMagic) continue;
      trade.PositionClose(tk);
      g_lastExitTs = (double)TimeCurrent();
      g_dayTrades++;
   }
}

//+------------------------------------------------------------------+
void OnTick()
{
   MqlTick t;
   if(!SymbolInfoTick(_Symbol,t)) return;
   double bid=t.bid, ask=t.ask;
   if(bid<=0 || ask<=bid) return;

   double ts  = (double)t.time_msc/1000.0;
   double mid = 0.5*(bid+ask);
   double spread = ask-bid;

   //--- day roll
   MqlDateTime dt; TimeToStruct(t.time, dt);
   datetime dkey = t.time - (t.time % 86400);
   if(dkey != g_day)
   {
      g_day = dkey;
      g_dayStartEquity = AccountInfoDouble(ACCOUNT_EQUITY);
      g_dayTrades = 0;
      g_dayLocked = false;
   }

   if(g_prevMid<=0){ g_prevMid=mid; g_prevTs=ts; g_spreadEwma=spread; return; }

   double dts = MathMax(1e-4, ts-g_prevTs);
   double dmid = mid-g_prevMid;
   double s = (dmid>1e-9)?1.0:((dmid<-1e-9)?-1.0:0.0);

   double a  = MathExp(-dts/TauFlow);        g_flow    = a*g_flow + s;
   double av = MathExp(-dts/TauFlowVar);     g_flowVar = av*g_flowVar + (1-av)*g_flow*g_flow;
   double ae = MathExp(-dts/TauEff);         g_net     = ae*g_net + dmid;
                                             g_disp    = ae*g_disp + MathAbs(dmid);
   double inst = 1.0/dts;
   double af = MathExp(-dts/TauIntensFast);  g_iFast = af*g_iFast + (1-af)*inst;
   double al = MathExp(-dts/TauIntensSlow);  g_iSlow = al*g_iSlow + (1-al)*inst;
   double avv= MathExp(-dts/TauVol);         g_vol   = avv*g_vol + (1-avv)*MathAbs(dmid);
   double asp= MathExp(-dts/TauSpread);      g_spreadEwma = asp*g_spreadEwma + (1-asp)*spread;

   g_prevMid=mid; g_prevTs=ts; g_warm++;
   if(g_warm < WarmupTicks) return;

   double fz = g_flow / MathMax(0.6, MathSqrt(g_flowVar));

   //================= manage open position =========================
   int dir; double openPrice; datetime openTime;
   if(HasPos(dir, openPrice, openTime))
   {
      double px   = (dir>0)? bid : ask;
      double move = (px-openPrice)*dir;
      if(move>g_best) g_best=move;

      if(!g_trailActive && g_best >= TrailArmK*g_entryVol) g_trailActive=true;
      if(g_trailActive)
      {
         double lvl = g_best - TrailK*g_entryVol;
         if(lvl>g_trailLevel) g_trailLevel=lvl;
      }

      if(move <= -SL_K*g_entryVol)                        { CloseAll("stop_loss");  return; }
      if(move >=  TP_K*g_entryVol)                        { CloseAll("take_profit");return; }
      if(g_trailActive && move <= g_trailLevel)           { CloseAll("trail");      return; }
      if(fz*dir <= -FlipZ)                                { CloseAll("flow_flip");  return; }
      if(ts - (double)openTime >= MaxHoldSeconds)         { CloseAll("time_stop");  return; }
      return;
   }

   //================= entry filters ================================
   if(g_dayLocked) return;
   double eq = AccountInfoDouble(ACCOUNT_EQUITY);
   double dd = (eq-g_dayStartEquity)/MathMax(1e-9,g_dayStartEquity)*100.0;
   if(dd <= -DailyLossStopPct || dd >= DailyProfitStopPct || g_dayTrades>=MaxTradesPerDay)
   { g_dayLocked=true; return; }

   if(dt.hour>=BlockHourFrom && dt.hour<=BlockHourTo) return;
   if(ts - g_lastExitTs < CooldownSeconds) return;
   if(g_vol < MinVol) return;
   if(MathAbs(fz) < FlowZ) return;

   double eff = MathAbs(g_net)/MathMax(1e-9,g_disp);
   if(eff < EffMin) return;
   if((g_net>0) != (fz>0)) return;
   if(g_iSlow<=0 || g_iFast < IntensMult*g_iSlow) return;

   double target = TP_K*g_vol;
   if(spread > SpreadMult*g_spreadEwma) return;
   if(spread > SpreadEdgeFrac*target)   return;

   //--- margin check for 800x
   double needMargin=0;
   int side = (fz>0)? 1 : -1;
   ENUM_ORDER_TYPE ot = (side>0)? ORDER_TYPE_BUY : ORDER_TYPE_SELL;
   OrderCalcMargin(ot,_Symbol,InpLot,(side>0)?ask:bid,needMargin);
   if(needMargin > AccountInfoDouble(ACCOUNT_MARGIN_FREE)*0.5) return;

   //================= fire ==========================================
   g_entryVol   = MathMax(g_vol, MinVol);
   g_best       = 0;
   g_trailLevel = -1e18;
   g_trailActive= false;

   if(side>0) trade.Buy(InpLot,_Symbol,0,0,0,"TFAM");
   else       trade.Sell(InpLot,_Symbol,0,0,0,"TFAM");
}
//+------------------------------------------------------------------+
