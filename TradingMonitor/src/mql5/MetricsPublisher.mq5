//+------------------------------------------------------------------+
//|                                              MetricsPublisher.mq5|
//|                                     Copyright 2024, TradingMonitor|
//+------------------------------------------------------------------+
#property copyright "TradingMonitor"
#property version   "2.00"

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
input datetime HistoryStartDate  = D'2024.01.01'; // Initial date to search history

// Internal state for per-magic equity tracking (max 64 distinct strategies)
#define MAX_STRATEGIES 64
long   g_magic_ids[MAX_STRATEGIES];
double g_magic_balance[MAX_STRATEGIES];
int    g_magic_count = 0;

int    g_socket = INVALID_HANDLE;

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
        SendHistoricalDeals();

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
void SendHistoricalDeals()
{
    Print("Loading history from ", TimeToString(HistoryStartDate, TIME_DATE), " ...");

    if(!HistorySelect(HistoryStartDate, TimeCurrent()))
    {
        Print("HistorySelect failed.");
        return;
    }

    int total = HistoryDealsTotal();
    int sent  = 0;

    for(int i = 0; i < total; i++)
    {
        ulong ticket = HistoryDealGetTicket(i);
        if(ticket == 0) continue;

        long time_val = HistoryDealGetInteger(ticket, DEAL_TIME);
        if(time_val < (long)HistoryStartDate) continue;  // explicit guard — HistorySelect cache may include earlier deals

        long dtype = HistoryDealGetInteger(ticket, DEAL_TYPE);
        if(dtype != DEAL_TYPE_BUY && dtype != DEAL_TYPE_SELL) continue;

        long magic = HistoryDealGetInteger(ticket, DEAL_MAGIC);

        // If MagicNumber input != 0, only send deals for that strategy
        if(MagicNumber != 0 && magic != MagicNumber) continue;

        string symbol     = HistoryDealGetString(ticket,  DEAL_SYMBOL);
        double volume     = HistoryDealGetDouble(ticket,  DEAL_VOLUME);
        double price      = HistoryDealGetDouble(ticket,  DEAL_PRICE);
        double profit     = HistoryDealGetDouble(ticket,  DEAL_PROFIT);
        double commission = HistoryDealGetDouble(ticket,  DEAL_COMMISSION);
        double swap       = HistoryDealGetDouble(ticket,  DEAL_SWAP);
        string type_str   = (dtype == DEAL_TYPE_BUY) ? "buy" : "sell";

        // --- DEAL message ---
        string deal_msg = StringFormat(
            "DEAL {\"time\": %d, \"ticket\": %d, \"magic\": %d, \"symbol\": \"%s\","
            " \"type\": \"%s\", \"volume\": %.2f, \"price\": %.5f,"
            " \"profit\": %.2f, \"commission\": %.2f, \"swap\": %.2f}\n",
            time_val, ticket, magic, symbol, type_str,
            volume, price, profit, commission, swap
        );
        if(!SendMessage(deal_msg)) continue;

        // --- EQUITY snapshot — cumulative P&L from HistoryStartDate ---
        double net = profit + commission + swap;
        double cum = GetBalance(magic) + net;
        SetBalance(magic, cum);

        string eq_msg = StringFormat(
            "EQUITY {\"time\": %d, \"magic\": %d, \"balance\": %.2f, \"equity\": %.2f}\n",
            time_val, magic, cum, cum
        );
        SendMessage(eq_msg);

        sent++;
    }

    Print("Historical export complete: ", sent, " deals sent.");
}

//+------------------------------------------------------------------+
//| Timer — live equity + account snapshot                            |
//+------------------------------------------------------------------+
void OnTimer()
{
    double balance     = AccountInfoDouble(ACCOUNT_BALANCE);
    double equity      = AccountInfoDouble(ACCOUNT_EQUITY);
    double free_margin = AccountInfoDouble(ACCOUNT_MARGIN_FREE);
    long   login       = AccountInfoInteger(ACCOUNT_LOGIN);
    string broker      = AccountInfoString(ACCOUNT_COMPANY);
    double deposits    = AccountInfoDouble(ACCOUNT_BALANCE); // placeholder
    double withdrawals = 0;

    // EQUITY — identifies which strategy via MagicNumber
    string eq_msg = StringFormat(
        "EQUITY {\"time\": %d, \"magic\": %d, \"balance\": %.2f, \"equity\": %.2f}\n",
        TimeCurrent(), MagicNumber, balance, equity
    );
    SendMessage(eq_msg);
    Print("Published: EQUITY magic=", MagicNumber, " balance=", balance, " equity=", equity);

    // ACCOUNT — account-level snapshot
    string acc_msg = StringFormat(
        "ACCOUNT {\"login\": %d, \"broker\": \"%s\", \"balance\": %.2f,"
        " \"free_margin\": %.2f, \"deposits\": %.2f, \"withdrawals\": %.2f}\n",
        login, broker, balance, free_margin, deposits, withdrawals
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

    string msg = StringFormat(
        "DEAL {\"time\": %d, \"ticket\": %d, \"magic\": %d, \"symbol\": \"%s\","
        " \"type\": \"%s\", \"volume\": %.2f, \"price\": %.5f,"
        " \"profit\": %.2f, \"commission\": %.2f, \"swap\": %.2f}\n",
        time_val, ticket, magic, symbol, type_str,
        volume, price, profit, commission, swap
    );

    if(SendMessage(msg))
        Print("Published: DEAL ticket=", ticket, " magic=", magic, " profit=", profit);
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
//+------------------------------------------------------------------+
