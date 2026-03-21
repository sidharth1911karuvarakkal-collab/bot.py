import ccxt, pandas as pd, ta, time, requests, threading, os, csv
from flask import Flask
from datetime import datetime
import pytz
from textblob import TextBlob

# ================= CONFIG =================
TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

CAPITAL = 100        # Total capital $
RISK_PER_TRADE = 0.01   # 1% risk

# ================= TELEGRAM =================
def send(msg):
    try:
        requests.post(
            f"https://api.telegram.org/bot{TOKEN}/sendMessage",
            data={"chat_id": CHAT_ID, "text": msg}
        )
    except:
        pass

# ================= EXCHANGE =================
exchange = ccxt.okx()
symbol = "BTC/USDT"

# ================= DATA =================
def get_df(tf):
    data = exchange.fetch_ohlcv(symbol, tf, limit=100)
    df = pd.DataFrame(data, columns=['t','o','h','l','c','v'])

    df['ema20'] = df['c'].ewm(span=20).mean()
    df['ema50'] = df['c'].ewm(span=50).mean()
    df['rsi'] = ta.momentum.RSIIndicator(df['c']).rsi()
    df['atr'] = ta.volatility.AverageTrueRange(df['h'],df['l'],df['c']).average_true_range()

    return df

# ================= SENTIMENT =================
def sentiment():
    try:
        news = requests.get("https://cryptocurrency.cv/api/news").json()['data'][:10]
        score = sum(TextBlob(n['title']).sentiment.polarity for n in news)/len(news)
    except:
        score = 0

    if score > 0.05:
        return "Bullish"
    elif score < -0.05:
        return "Bearish"
    return "Neutral"

# ================= POSITION SIZE =================
def position_size(price, sl):
    risk_amount = CAPITAL * RISK_PER_TRADE
    risk_per_unit = abs(price - sl)

    if risk_per_unit == 0:
        return 0

    qty = risk_amount / risk_per_unit
    return round(qty, 6)

# ================= SIGNAL =================
def check(df1, df15):
    last = df1.iloc[-1]
    prev = df1.iloc[-2]

    trend_up = df15['c'].iloc[-1] > df15['ema50'].iloc[-1]
    trend_down = df15['c'].iloc[-1] < df15['ema50'].iloc[-1]

    breakout_up = last['c'] > df1['h'].rolling(20).max().iloc[-2]
    breakout_down = last['c'] < df1['l'].rolling(20).min().iloc[-2]

    retest_up = prev['c'] < prev['ema20'] and last['c'] > last['ema20']
    retest_down = prev['c'] > prev['ema20'] and last['c'] < last['ema20']

    vol_ok = last['v'] > df1['v'].rolling(20).mean().iloc[-1]

    atr_percent = (last['atr']/last['c'])*100
    sideways = atr_percent < 0.2

    buy = breakout_up and retest_up and trend_up and vol_ok and not sideways
    sell = breakout_down and retest_down and trend_down and vol_ok and not sideways

    price = last['c']
    atr = last['atr']

    sl = price - atr if buy else price + atr
    tp = price + 2*atr if buy else price - 2*atr

    return buy, sell, price, sl, tp, sideways

# ================= TRADE LOG =================
def log_trade(data):
    with open("trades.csv", "a", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(data)

# ================= BOT =================
def run():
    send("🚀 PROFESSIONAL BOT LIVE")

    last_signal = "NONE"
    trades = 0
    wins = 0
    losses = 0
    last_heartbeat = 0

    while True:
        try:
            df1 = get_df('1m')
            df15 = get_df('15m')

            buy, sell, price, sl, tp, sideways = check(df1, df15)
            sent = sentiment()

            now = datetime.now(pytz.timezone('Asia/Kolkata')).strftime("%H:%M:%S")
            current_time = time.time()

            # POSITION SIZE
            qty = position_size(price, sl)

            # SIGNAL
            if buy and last_signal != "BUY":
                trades += 1
                send(f"""
🟢 BUY

Price: {price}
SL: {sl}
TP: {tp}
Qty: {qty}

Sentiment: {sent}
Time: {now}
""")
                log_trade([now, "BUY", price, sl, tp, qty])
                last_signal = "BUY"

            elif sell and last_signal != "SELL":
                trades += 1
                send(f"""
🔴 SELL

Price: {price}
SL: {sl}
TP: {tp}
Qty: {qty}

Sentiment: {sent}
Time: {now}
""")
                log_trade([now, "SELL", price, sl, tp, qty])
                last_signal = "SELL"

            # HEARTBEAT + PERFORMANCE
            if current_time - last_heartbeat > 3600:
                win_rate = (wins/trades*100) if trades > 0 else 0

                send(f"""
💓 BOT STATUS

Trades: {trades}
Wins: {wins}
Losses: {losses}
Win Rate: {round(win_rate,2)}%

Last Signal: {last_signal}
Sentiment: {sent}

Time: {now}
""")
                last_heartbeat = current_time

            time.sleep(30)

        except Exception as e:
            send(f"❌ Error: {e}")
            time.sleep(10)

# ================= SERVER =================
app = Flask(__name__)

@app.route('/')
def home():
    return "Professional Bot Running"

if __name__ == "__main__":
    threading.Thread(target=run, daemon=True).start()
    app.run(host="0.0.0.0", port=10000)
