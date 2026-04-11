//+------------------------------------------------------------------+
//|                                              MetricsPublisher.mq5|
//|                                     Copyright 2024, TradingMonitor|
//+------------------------------------------------------------------+
#property copyright "TradingMonitor"
#property version   "2.01"

// Uses MT5 native socket API (no DLL required, available since build 2485)
// Enable "Allow DLL imports" is NOT needed for native sockets.

//--- Connection
input string   ServerHost    = "100.100.10.135"; // Python server IP
input int      ServerPort    = 5555;             // Must match start-ingestion port
input int      ConnectTimeout = 5000;            // Connection timeout (ms)

//--- Strategy identification
input int      MagicNumber   = 0;                // Magic number (0 = all strategies)

//--- Live publishing
input int      TimerInterval = 60;               // Equity publish interval (seconds)

//--- Historical export
input bool     SendHistoryOnInit = true;         // Send historical data on attach
input bool     SendHistoryDaily = true;          // Send the full history once per day
input int      DailyHistoryHour = 0;             // Server hour for the daily full history sync
input int      DailyHistoryMinute = 5;           // Server minute for the daily full history sync
input datetime HistoryStartDate  = D'2024.01.01'; // Initial date to search history

// Internal state for per-magic equity tracking (max 64 distinct strategies)
#define MAX_STRATEGIES 64
long   g_magic_ids[MAX_STRATEGIES];
double g_magic_balance[MAX_STRATEGIES];
int    g_magic_count = 0;

int    g_socket = INVALID_HANDLE;
int    g_last_daily_history_sync_day = -1;

string BuildRuntimeFieldsJson(long magic);
void   SendStrategyRuntime(long magic);

//+------------------------------------------------------------------+
int OnInit()
{
    g_socket = Connect();
    if(g_socket == INVALID_HANDLE)
    {
        Print("MetricsPublisher: failed to connect to ", ServerHost, ":", ServerPort, ". Will retry on next tick.");
    }
    else
    {
        Print("MetricsPublisher: connected to ", ServerHost, ":", ServerPort, " | Magic: ", MagicNumber);
    }

    if(SendHistoryOnInit)
    {
        if(SendHistoricalDeals())
            MarkDailyHistorySyncIfScheduledTimePassed(TimeCurrent());
    }

    EventSetTimer(TimerInterval);
    return(INIT_SUCCEEDED);
}

//+------------------------------------------------------------------+
void OnDeinit(const int reason)
{
    EventKillTimer();
    if(g_socket != INVALID_HANDLE)
    {
        SocketClose(g_socket);
        g_socket = INVALID_HANDLE;
    }
}

//+------------------------------------------------------------------+
//| Open a new TCP connection to the Python server                    |
//+------------------------------------------------------------------+
int Connect()
{
    int sock = SocketCreate();
    if(sock == INVALID_HANDLE)
    {
        Print("SocketCreate failed: ", GetLastError());
        return INVALID_HANDLE;
    }
    if(!SocketConnect(sock, ServerHost, ServerPort, ConnectTimeout))
    {
        Print("SocketConnect failed: ", GetLastError());
        SocketClose(sock);
        return INVALID_HANDLE;
    }
    return sock;
}

//+------------------------------------------------------------------+
//| Send a string message. Reconnects once if socket is dead.        |
//+------------------------------------------------------------------+
bool SendMessage(const string msg)
{
    // Reconnect if socket is gone
    if(g_socket == INVALID_HANDLE || !SocketIsConnected(g_socket))
    {
        if(g_socket != INVALID_HANDLE)
        {
            SocketClose(g_socket);
            g_socket = INVALID_HANDLE;
        }
        g_socket = Connect();
        if(g_socket == INVALID_HANDLE)
        {
            Print("SendMessage: reconnect failed, message dropped.");
            return false;
        }
        Print("SendMessage: reconnected to server.");
    }

    // Encode string to uchar array (UTF-8)
    uchar buf[];
    StringToCharArray(msg, buf, 0, StringLen(msg));

    int sent = SocketSend(g_socket, buf, ArraySize(buf));
    if(sent < 0)
    {
        Print("SocketSend failed: ", GetLastError(), " — message dropped.");
        SocketClose(g_socket);
        g_socket = INVALID_HANDLE;
        return false;
    }
    return true;
}

//+------------------------------------------------------------------+
//| Historical export — runs once on EA attach                        |
//+------------------------------------------------------------------+
bool SendHistoricalDeals()
{
    Print("Loading history from ", TimeToString(HistoryStartDate, TIME_DATE), " ...");

    if(!HistorySelect(HistoryStartDate, TimeCurrent()))
    {
        Print("HistorySelect failed.");
        return false;
    }

    int total = HistoryDealsTotal();
    int sent  = 0;

    for(int i = 0; i < total; i++)
    {
        ulong ticket = HistoryDealGetTicket(i);
        if(ticket == 0) continue;

        long dtype = HistoryDealGetInteger(ticket, DEAL_TYPE);
        if(dtype != DEAL_TYPE_BUY && dtype != DEAL_TYPE_SELL) continue;

        long magic = HistoryDealGetInteger(ticket, DEAL_MAGIC);

        // If MagicNumber input != 0, only send deals for that strategy
        if(MagicNumber != 0 && magic != MagicNumber) continue;

        string symbol     = HistoryDealGetString(ticket,  DEAL_SYMBOL);
        long   time_val   = HistoryDealGetInteger(ticket, DEAL_TIME);
        double volume     = HistoryDealGetDouble(ticket,  DEAL_VOLUME);
        double price      = HistoryDealGetDouble(ticket,  DEAL_PRICE);
        double profit     = HistoryDealGetDouble(ticket,  DEAL_PROFIT);
        double commission = HistoryDealGetDouble(ticket,  DEAL_COMMISSION);
        double swap       = HistoryDealGetDouble(ticket,  DEAL_SWAP);
        string type_str   = (dtype == DEAL_TYPE_BUY) ? "buy" : "sell";

        // --- DEAL message ---
        string runtime_fields = BuildRuntimeFieldsJson(magic);
        string deal_msg = StringFormat(
            "DEAL {\"time\": %d, \"ticket\": %d, \"magic\": %d, \"symbol\": \"%s\","
            " \"type\": \"%s\", \"volume\": %.2f, \"price\": %.5f,"
            " \"profit\": %.2f, \"commission\": %.2f, \"swap\": %.2f%s}\n",
            time_val, ticket, magic, symbol, type_str,
            volume, price, profit, commission, swap, runtime_fields
        );
        if(!SendMessage(deal_msg)) continue;

        // --- EQUITY snapshot — cumulative P&L from HistoryStartDate ---
        double net = profit + commission + swap;
        double cum = GetBalance(magic) + net;
        SetBalance(magic, cum);

        string eq_runtime_fields = BuildRuntimeFieldsJson(magic);
        string eq_msg = StringFormat(
            "EQUITY {\"time\": %d, \"magic\": %d, \"balance\": %.2f, \"equity\": %.2f%s}\n",
            time_val, magic, cum, cum, eq_runtime_fields
        );
        SendMessage(eq_msg);

        sent++;
    }

    Print("Historical export complete: ", sent, " deals sent.");

    // Send one STRATEGY_RUNTIME per exported magic after the full history is flushed
    if(MagicNumber != 0)
    {
        SendStrategyRuntime(MagicNumber);
    }
    else
    {
        for(int i = 0; i < g_magic_count; i++)
            SendStrategyRuntime(g_magic_ids[i]);
    }

    return true;
}

//+------------------------------------------------------------------+
//| Timer — live equity + account snapshot                            |
//+------------------------------------------------------------------+
void OnTimer()
{
    TrySendDailyHistoricalDeals();

    double balance     = AccountInfoDouble(ACCOUNT_BALANCE);
    double equity      = AccountInfoDouble(ACCOUNT_EQUITY);
    double free_margin = AccountInfoDouble(ACCOUNT_MARGIN_FREE);
    long   login       = AccountInfoInteger(ACCOUNT_LOGIN);
    string broker      = AccountInfoString(ACCOUNT_COMPANY);
    double deposits    = AccountInfoDouble(ACCOUNT_BALANCE); // placeholder
    double withdrawals = 0;

    // EQUITY — identifies which strategy via MagicNumber
    string runtime_fields = BuildRuntimeFieldsJson(MagicNumber);
    string eq_msg = StringFormat(
        "EQUITY {\"time\": %d, \"magic\": %d, \"balance\": %.2f, \"equity\": %.2f%s}\n",
        TimeCurrent(), MagicNumber, balance, equity, runtime_fields
    );
    SendMessage(eq_msg);
    Print("Published: EQUITY magic=", MagicNumber, " balance=", balance, " equity=", equity);

    // ACCOUNT — account-level snapshot
    string acc_msg = StringFormat(
        "ACCOUNT {\"time\": %d, \"magic\": %d, \"login\": %d, \"broker\": \"%s\","
        " \"balance\": %.2f, \"free_margin\": %.2f, \"deposits\": %.2f,"
        " \"withdrawals\": %.2f%s}\n",
        TimeCurrent(), MagicNumber, login, broker, balance, free_margin, deposits,
        withdrawals, runtime_fields
    );
    SendMessage(acc_msg);
    Print("Published: ACCOUNT login=", login, " broker=", broker);

}

//+------------------------------------------------------------------+
//| Live deal capture                                                 |
//+------------------------------------------------------------------+
void OnTradeTransaction(
    const MqlTradeTransaction& trans,
    const MqlTradeRequest& request,
    const MqlTradeResult& result)
{
    if(trans.type != TRADE_TRANSACTION_DEAL_ADD) return;

    ulong ticket = trans.deal;
    if(!HistoryDealSelect(ticket)) return;

    long deal_type = HistoryDealGetInteger(ticket, DEAL_TYPE);
    if(deal_type != DEAL_TYPE_BUY && deal_type != DEAL_TYPE_SELL) return;

    long   magic      = HistoryDealGetInteger(ticket, DEAL_MAGIC);
    string symbol     = HistoryDealGetString(ticket,  DEAL_SYMBOL);
    long   time_val   = HistoryDealGetInteger(ticket, DEAL_TIME);
    double volume     = HistoryDealGetDouble(ticket,  DEAL_VOLUME);
    double price      = HistoryDealGetDouble(ticket,  DEAL_PRICE);
    double profit     = HistoryDealGetDouble(ticket,  DEAL_PROFIT);
    double commission = HistoryDealGetDouble(ticket,  DEAL_COMMISSION);
    double swap       = HistoryDealGetDouble(ticket,  DEAL_SWAP);
    string type_str   = (deal_type == DEAL_TYPE_BUY) ? "buy" : "sell";

    string runtime_fields = BuildRuntimeFieldsJson(magic);
    string msg = StringFormat(
        "DEAL {\"time\": %d, \"ticket\": %d, \"magic\": %d, \"symbol\": \"%s\","
        " \"type\": \"%s\", \"volume\": %.2f, \"price\": %.5f,"
        " \"profit\": %.2f, \"commission\": %.2f, \"swap\": %.2f%s}\n",
        time_val, ticket, magic, symbol, type_str,
        volume, price, profit, commission, swap, runtime_fields
    );

    if(SendMessage(msg))
    {
        Print("Published: DEAL ticket=", ticket, " magic=", magic, " profit=", profit);
        if(magic != 0)
            SendStrategyRuntime(magic);
    }
}

//+------------------------------------------------------------------+
//| Helpers — track cumulative balance per magic number               |
//+------------------------------------------------------------------+
double GetBalance(long magic)
{
    for(int i = 0; i < g_magic_count; i++)
        if(g_magic_ids[i] == magic) return g_magic_balance[i];
    // First time seeing this magic: register it at 0
    if(g_magic_count < MAX_STRATEGIES)
    {
        g_magic_ids[g_magic_count]     = magic;
        g_magic_balance[g_magic_count] = 0;
        g_magic_count++;
    }
    return 0;
}

void SetBalance(long magic, double value)
{
    for(int i = 0; i < g_magic_count; i++)
        if(g_magic_ids[i] == magic) { g_magic_balance[i] = value; return; }
}

int GetOpenTradesCount(long magic)
{
    int count = 0;
    int total = PositionsTotal();
    for(int i = 0; i < total; i++)
    {
        string symbol = PositionGetSymbol(i);
        if(symbol == "") continue;

        long position_magic = PositionGetInteger(POSITION_MAGIC);
        if(magic == 0 || position_magic == magic)
            count++;
    }
    return count;
}

double GetOpenProfit(long magic)
{
    double total_profit = 0.0;
    int total = PositionsTotal();
    for(int i = 0; i < total; i++)
    {
        string symbol = PositionGetSymbol(i);
        if(symbol == "") continue;

        long position_magic = PositionGetInteger(POSITION_MAGIC);
        if(magic != 0 && position_magic != magic)
            continue;

        total_profit += PositionGetDouble(POSITION_PROFIT);
        total_profit += PositionGetDouble(POSITION_SWAP);
    }
    return total_profit;
}

int GetPendingOrdersCount(long magic)
{
    int count = 0;
    int total = OrdersTotal();
    for(int i = 0; i < total; i++)
    {
        ulong ticket = OrderGetTicket(i);
        if(ticket == 0) continue;

        long order_magic = OrderGetInteger(ORDER_MAGIC);
        if(magic == 0 || order_magic == magic)
            count++;
    }
    return count;
}

void SendStrategyRuntime(long magic)
{
    if(magic == 0) return;

    double open_profit    = GetOpenProfit(magic);
    int    open_trades    = GetOpenTradesCount(magic);
    int    pending_orders = GetPendingOrdersCount(magic);

    string msg = StringFormat(
        "STRATEGY_RUNTIME {\"time\": %d, \"magic\": %d, \"open_profit\": %.2f,"
        " \"open_trades_count\": %d, \"pending_orders_count\": %d}\n",
        TimeCurrent(), magic, open_profit, open_trades, pending_orders
    );
    SendMessage(msg);
    Print("Published: STRATEGY_RUNTIME magic=", magic,
          " open_profit=", open_profit,
          " open_trades=", open_trades,
          " pending_orders=", pending_orders);
}

string BuildRuntimeFieldsJson(long magic)
{
    double open_profit = GetOpenProfit(magic);
    int open_trades = GetOpenTradesCount(magic);
    int pending_orders = GetPendingOrdersCount(magic);

    return StringFormat(
        ", \"open_profit\": %.2f, \"open_trades_count\": %d,"
        " \"pending_orders_count\": %d",
        open_profit, open_trades, pending_orders
    );
}

int GetDayId(datetime value)
{
    MqlDateTime parts;
    TimeToStruct(value, parts);
    return parts.year * 10000 + parts.mon * 100 + parts.day;
}

int GetMinutesOfDay(datetime value)
{
    MqlDateTime parts;
    TimeToStruct(value, parts);
    return parts.hour * 60 + parts.min;
}

int GetScheduledHistorySyncMinute()
{
    int hour = DailyHistoryHour;
    int minute = DailyHistoryMinute;

    if(hour < 0) hour = 0;
    if(hour > 23) hour = 23;
    if(minute < 0) minute = 0;
    if(minute > 59) minute = 59;

    return hour * 60 + minute;
}

void MarkDailyHistorySyncIfScheduledTimePassed(datetime now)
{
    if(!SendHistoryDaily)
        return;

    if(GetMinutesOfDay(now) < GetScheduledHistorySyncMinute())
        return;

    g_last_daily_history_sync_day = GetDayId(now);
}

void TrySendDailyHistoricalDeals()
{
    if(!SendHistoryDaily)
        return;

    datetime now = TimeCurrent();
    int today = GetDayId(now);
    if(g_last_daily_history_sync_day == today)
        return;

    if(GetMinutesOfDay(now) < GetScheduledHistorySyncMinute())
        return;

    Print("MetricsPublisher: starting scheduled daily historical export.");
    if(SendHistoricalDeals())
        g_last_daily_history_sync_day = today;
}
//+------------------------------------------------------------------+
