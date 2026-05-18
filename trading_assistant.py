import yfinance as yf
import pandas as pd
import requests, json, time, schedule
from datetime import datetime, date
from pathlib import Path

# ── Config ───────────────────────────────────────────
BOT_TOKEN   = "8842204156:AAFgee_fgCp0Dc6U4A78S6umApIehRL5fMg"
CHAT_ID     = "6549644382"
STOP_PCT    = 0.03    # 3% stop loss
RR_RATIO    = 2.5     # target = 2.5x the risk
SCAN_MINS   = 15      # scan every 15 minutes
POS_FILE    = "positions.json"

WATCHLIST = [
    "RELIANCE.NS", "TCS.NS", "INFY.NS",
    "HDFCBANK.NS", "ICICIBANK.NS", "WIPRO.NS",
    "AXISBANK.NS", "SBIN.NS", "TATAMOTORS.NS",
    "BAJFINANCE.NS", "HCLTECH.NS", "SUNPHARMA.NS",
    # add more NSE symbols with .NS suffix
]

# ── Telegram ─────────────────────────────────────────
def send(msg):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    try:
        requests.post(url, json={
            "chat_id": CHAT_ID,
            "text": msg,
            "parse_mode": "HTML"
        }, timeout=10)
    except Exception as e:
        print(f"  Telegram error: {e}")

# ── Position storage ──────────────────────────────────
def load_pos():
    f = Path(POS_FILE)
    return json.loads(f.read_text()) if f.exists() else {}

def save_pos(p):
    Path(POS_FILE).write_text(json.dumps(p, indent=2))

# ── Data & indicators ─────────────────────────────────
def get_data(sym):
    df = yf.download(sym, period="6mo", interval="1d",
                     progress=False, auto_adjust=True)
    df.columns = [c[0].lower() for c in df.columns]
    df["ema20"]   = df["close"].ewm(span=20, adjust=False).mean()
    df["ema50"]   = df["close"].ewm(span=50, adjust=False).mean()
    delta         = df["close"].diff()
    gain          = delta.clip(lower=0).rolling(14).mean()
    loss          = (-delta.clip(upper=0)).rolling(14).mean()
    df["rsi"]     = 100 - (100 / (1 + gain / loss))
    df["avg_vol"] = df["volume"].rolling(20).mean()
    return df

def get_signal(df):
    p, c = df.iloc[-2], df.iloc[-1]
    up   = p["ema20"] <= p["ema50"] and c["ema20"] > c["ema50"]
    down = p["ema20"] >= p["ema50"] and c["ema20"] < c["ema50"]
    rsi_ok = 45 <= c["rsi"] <= 63
    vol_ok = c["volume"] > c["avg_vol"] * 1.2
    if up and rsi_ok and vol_ok:
        return "BUY",  c
    if down:
        return "SELL", c
    return "HOLD", c

# ── Message builders ──────────────────────────────────
def buy_msg(sym, row):
    n      = sym.replace(".NS", "")
    px     = float(row["close"])
    sl     = round(px * (1 - STOP_PCT), 2)
    risk   = round(px - sl, 2)
    target = round(px + risk * RR_RATIO, 2)
    gain_p = round((target - px) / px * 100, 1)
    rsi    = round(float(row["rsi"]), 1)
    vol_x  = round(float(row["volume"]) / float(row["avg_vol"]), 1)
    return (
        f"🟢 <b>BUY SIGNAL — {n}</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"📌 Entry Price:  ₹{px:,.2f}\n"
        f"🛑 Stop Loss:    ₹{sl:,.2f}  (−{STOP_PCT*100:.0f}%)\n"
        f"🎯 Target:       ₹{target:,.2f}  (+{gain_p}%)\n"
        f"⏱ Est. Time:    3–5 weeks\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"📊 RSI: {rsi} | Vol: {vol_x}x avg\n"
        f"✅ 20 EMA crossed above 50 EMA\n"
        f"⚠️ Risk ₹{risk}/share → Reward ₹{round(risk*RR_RATIO,2)}/share"
    )

def sell_msg(sym, row, entry):
    n     = sym.replace(".NS", "")
    px    = float(row["close"])
    pnl   = round(px - entry, 2)
    pnl_p = round(pnl / entry * 100, 1)
    action = "BOOK PROFIT ✅" if pnl > 0 else "EXIT — CUT LOSS ⚠️"
    sign   = "+" if pnl >= 0 else ""
    icon   = "📈" if pnl >= 0 else "📉"
    return (
        f"🔴 <b>SELL SIGNAL — {n}</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"💰 Sell Price: ₹{px:,.2f}\n"
        f"📌 Action:     {action}\n"
        f"{icon} P&L:       {sign}₹{pnl:,.2f}/share ({sign}{pnl_p}%)\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"20 EMA crossed below 50 EMA"
    )

def summary_msg(sym, entry, exit_px, entry_date):
    n     = sym.replace(".NS", "")
    pnl   = round(exit_px - entry, 2)
    pnl_p = round(pnl / entry * 100, 1)
    days  = (date.today() - date.fromisoformat(entry_date)).days
    res   = "PROFITABLE TRADE ✅" if pnl > 0 else "LOSS — REVIEW STRATEGY ⚠️"
    sign  = "+" if pnl >= 0 else ""
    icon  = "📈" if pnl >= 0 else "📉"
    return (
        f"📋 <b>TRADE SUMMARY — {n}</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"🟢 Bought at:  ₹{entry:,.2f}\n"
        f"🔴 Sold at:    ₹{exit_px:,.2f}\n"
        f"{icon} P&L:        {sign}₹{pnl:,.2f}/share\n"
        f"📊 Gain/Loss:  {sign}{pnl_p}%\n"
        f"⏱ Duration:   {days} days\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"<b>{res}</b>"
    )

# ── Scanner ───────────────────────────────────────────
def scan():
    now = datetime.now()
    if now.weekday() >= 5 or not (9 <= now.hour < 15):
        print(f"[{now:%H:%M}] Outside market hours — skipping.")
        return

    positions = load_pos()
    print(f"\n[{now:%H:%M}] Scanning {len(WATCHLIST)} stocks...")

    for sym in WATCHLIST:
        try:
            df = get_data(sym)
            signal, row = get_signal(df)

            if signal == "BUY" and sym not in positions:
                send(buy_msg(sym, row))
                positions[sym] = {
                    "entry": float(row["close"]),
                    "date":  str(date.today())
                }
                save_pos(positions)
                print(f"  BUY  → {sym} @ ₹{float(row['close']):.2f}")

            elif signal == "SELL" and sym in positions:
                entry  = positions[sym]["entry"]
                edate  = positions[sym]["date"]
                exit_p = float(row["close"])
                send(sell_msg(sym, row, entry))
                time.sleep(1)
                send(summary_msg(sym, entry, exit_p, edate))
                del positions[sym]
                save_pos(positions)
                print(f"  SELL → {sym} @ ₹{exit_p:.2f}")

            else:
                print(f"  HOLD   {sym}")

        except Exception as e:
            print(f"  ERR  → {sym}: {e}")

# ── Entry point ───────────────────────────────────────
if __name__ == "__main__":
    print("=" * 45)
    print("  Swing Trading Assistant — swingging_bot")
    print("=" * 45)
    send(
        "🤖 <b>Trading Assistant is LIVE</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━\n"
        f"📋 Watching {len(WATCHLIST)} stocks\n"
        f"🔍 Scanning every {SCAN_MINS} minutes\n"
        "⏰ Active: Mon–Fri, 9:15 AM – 3:00 PM IST\n"
        "━━━━━━━━━━━━━━━━━━━━━\n"
        "Strategy: 20 EMA × 50 EMA + RSI + Volume"
    )
    scan()  # run immediately on start
    schedule.every(SCAN_MINS).minutes.do(scan)
    while True:
        schedule.run_pending()
        time.sleep(30)
