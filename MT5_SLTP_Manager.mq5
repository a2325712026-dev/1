//+------------------------------------------------------------------+
//|                                                MT5_SLTP_Manager  |
//|                   SL/TP manager script (price/money/trailing)    |
//+------------------------------------------------------------------+
#property strict
#property script_show_inputs

#include <Trade/Trade.mqh>

enum ENUM_TP_MODE
  {
   TP_BY_PRICE = 0,   // TP 按价格
   TP_BY_MONEY = 1    // TP 按金额
  };

enum ENUM_SL_KIND
  {
   SL_NORMAL = 0,        // 普通止损
   SL_TRAILING_FIXED = 1 // 固定移动止损(点数)
  };

enum ENUM_SL_MODE
  {
   SL_BY_PRICE = 0, // SL 按价格
   SL_BY_MONEY = 1  // SL 按金额
  };

input bool         InpOnlyCurrentSymbol = false; // 仅处理当前图表品种
input ulong        InpTargetTicket      = 0;     // 指定持仓票号(0=全部)

input ENUM_TP_MODE InpTPMode            = TP_BY_PRICE; // TP 模式
input double       InpTPPrice           = 0.0;         // TP 价格(按价格模式)
input double       InpTPMoney           = 0.0;         // TP 金额(按金额模式)

input ENUM_SL_KIND InpSLKind            = SL_NORMAL;   // SL 类型
input ENUM_SL_MODE InpSLMode            = SL_BY_PRICE; // 普通 SL 模式
input double       InpSLPrice           = 0.0;         // SL 价格(普通-按价格)
input double       InpSLMoney           = 0.0;         // SL 金额(普通-按金额)
input int          InpTrailingPoints    = 0;           // 固定移动止损点数

input ulong        InpMagic             = 0;           // 可选: 按 Magic 过滤(0=不限制)

CTrade trade;

bool BuildTargets(const string symbol,
                  const ENUM_POSITION_TYPE posType,
                  const double volume,
                  const double openPrice,
                  const double currentPrice,
                  double &slOut,
                  double &tpOut)
  {
   int digits = (int)SymbolInfoInteger(symbol, SYMBOL_DIGITS);
   double point = SymbolInfoDouble(symbol, SYMBOL_POINT);
   if(point <= 0.0)
     {
      Print("点值无效: ", symbol);
      return false;
     }

   // TP 必填（价格/金额二选一）
   if(InpTPMode == TP_BY_PRICE)
     {
      if(InpTPPrice <= 0.0)
        {
         Print("TP 按价格模式下，InpTPPrice 必须 > 0");
         return false;
        }
      tpOut = NormalizeDouble(InpTPPrice, digits);
     }
   else
     {
      if(InpTPMoney <= 0.0)
        {
         Print("TP 按金额模式下，InpTPMoney 必须 > 0");
         return false;
        }
      double tpByMoney;
      if(!PriceByMoney(symbol, posType, volume, openPrice, InpTPMoney, true, tpByMoney))
         return false;
      tpOut = NormalizeDouble(tpByMoney, digits);
     }

   // SL 必填（普通:价格/金额二选一；固定移动:点数必填）
   if(InpSLKind == SL_NORMAL)
     {
      if(InpSLMode == SL_BY_PRICE)
        {
         if(InpSLPrice <= 0.0)
           {
            Print("普通止损-按价格模式下，InpSLPrice 必须 > 0");
            return false;
           }
         slOut = NormalizeDouble(InpSLPrice, digits);
        }
      else
        {
         if(InpSLMoney <= 0.0)
           {
            Print("普通止损-按金额模式下，InpSLMoney 必须 > 0");
            return false;
           }
         double slByMoney;
         if(!PriceByMoney(symbol, posType, volume, openPrice, InpSLMoney, false, slByMoney))
            return false;
         slOut = NormalizeDouble(slByMoney, digits);
        }
     }
   else
     {
      if(InpTrailingPoints <= 0)
        {
         Print("固定移动止损模式下，InpTrailingPoints 必须 > 0");
         return false;
        }

      double delta = InpTrailingPoints * point;
      if(posType == POSITION_TYPE_BUY)
         slOut = NormalizeDouble(currentPrice - delta, digits);
      else
         slOut = NormalizeDouble(currentPrice + delta, digits);
     }

   return true;
  }

bool PriceByMoney(const string symbol,
                  const ENUM_POSITION_TYPE posType,
                  const double volume,
                  const double openPrice,
                  const double money,
                  const bool forTP,
                  double &targetPrice)
  {
   double point = SymbolInfoDouble(symbol, SYMBOL_POINT);
   int digits = (int)SymbolInfoInteger(symbol, SYMBOL_DIGITS);
   if(point <= 0.0)
     {
      Print("点值无效: ", symbol);
      return false;
     }
   if(money <= 0.0)
      return false;

   bool isBuy = (posType == POSITION_TYPE_BUY);
   ENUM_ORDER_TYPE orderType = isBuy ? ORDER_TYPE_BUY : ORDER_TYPE_SELL;

   double probeClose;
   int direction;
   if(forTP)
     {
      probeClose = isBuy ? (openPrice + point) : (openPrice - point);
      direction = isBuy ? 1 : -1;
     }
   else
     {
      probeClose = isBuy ? (openPrice - point) : (openPrice + point);
      direction = isBuy ? -1 : 1;
     }

   double probeProfit = 0.0;
   if(!OrderCalcProfit(orderType, symbol, volume, openPrice, probeClose, probeProfit))
     {
      Print("OrderCalcProfit 失败: ", symbol, ", err=", GetLastError());
      return false;
     }
   if(probeProfit == 0.0)
     {
      Print("按金额换算失败(每点收益为0): ", symbol);
      return false;
     }

   double pointsNeed = money / MathAbs(probeProfit);
   targetPrice = NormalizeDouble(openPrice + direction * pointsNeed * point, digits);
   return true;
  }

bool PositionMatch(const ulong ticket, const string symbol, const long magic)
  {
   if(InpTargetTicket > 0 && ticket != InpTargetTicket)
      return false;
   if(InpOnlyCurrentSymbol && symbol != _Symbol)
      return false;
   if(InpMagic > 0 && (ulong)magic != InpMagic)
      return false;
   return true;
  }

void OnStart()
  {
   int total = PositionsTotal();
   if(total <= 0)
     {
      Print("没有持仓");
      return;
     }

   int okCount = 0;
   int failCount = 0;

   for(int i = total - 1; i >= 0; --i)
     {
      ulong ticket = PositionGetTicket(i);
      if(ticket == 0 || !PositionSelectByTicket(ticket))
        {
         failCount++;
         continue;
        }

      string symbol = PositionGetString(POSITION_SYMBOL);
      long magic = PositionGetInteger(POSITION_MAGIC);
      if(!PositionMatch(ticket, symbol, magic))
         continue;

      ENUM_POSITION_TYPE posType = (ENUM_POSITION_TYPE)PositionGetInteger(POSITION_TYPE);
      double volume = PositionGetDouble(POSITION_VOLUME);
      double openPrice = PositionGetDouble(POSITION_PRICE_OPEN);
      double currentPrice = PositionGetDouble(POSITION_PRICE_CURRENT);
      double oldSL = PositionGetDouble(POSITION_SL);
      double oldTP = PositionGetDouble(POSITION_TP);

      double newSL = oldSL;
      double newTP = oldTP;
      if(!BuildTargets(symbol, posType, volume, openPrice, currentPrice, newSL, newTP))
        {
         failCount++;
         Print("参数或计算失败, ticket=", ticket);
         continue;
        }

      if(trade.PositionModify(ticket, newSL, newTP))
        {
         okCount++;
         Print("更新成功, ticket=", ticket, ", SL=", DoubleToString(newSL, 6), ", TP=", DoubleToString(newTP, 6));
        }
      else
        {
         failCount++;
         Print("更新失败, ticket=", ticket,
               ", retcode=", trade.ResultRetcode(),
               ", comment=", trade.ResultRetcodeDescription());
        }
     }

   Print("执行完成, 成功=", okCount, ", 失败=", failCount);
  }

