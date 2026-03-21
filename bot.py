import ccxt, pandas as pd, ta, time, requests, threading, os, csv
from flask import Flask
from datetime import datetime
import pytz
from textblob import TextBlob

# ================= CONFIG =================
TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

print("🔑 TOKEN:", TOKEN)
print("💬 CHAT_ID:", CHAT_ID)

CAPITAL = 100
RISK_PER_TRADE = 0.01

# ================= TELEGRAM =================
def send(msg):
    print("📤 Sending message...")
    try:
        res = requests.post(
            f"https://api.telegram.org/bot{TOKEN}/sendMessage",
            data={"chat_id": CHAT_ID, "text": msg}
        )
        print("📩 Telegram response:", res.text)
    except Exception as e:
        print("❌ Telegram Error:", e)

# ================= EXCHANGE =================
exchange = ccxt.okx({
    'enableRateLimit': True
})
symbol = "BTC/USDT"

# ================= DATA =================
def get_df(tf):
    print(f"📊 Fetching data: {tf}")
    data = exchange.fetch_ohlcv(symbol, tf, limit=50)
    df = pd.DataFrame(data, columns=['t','o','h','l','c','v'])

    df['ema20'] = df['c'].ewm(span=20).mean()
    df['ema50'] = df['c'].ewm(span=50).mean()
    df['rsi'] = ta.momentum.RSIIndicator(df['c']).rsi()
    df['atr'] = ta.volatility.AverageTrueRange(df['h'],df['l'],df['c']).average_true_range()

    return df

# ================= SAFE FETCH =================
def safe_fetch(tf):
    try:
        return get_df(tf)
    except Exception as e:
        print("⚠️ Retry after error:", e)
        time.sleep(10)
        return get_df(tf)

# ================= SENTIMENT =================
def sentiment():
    try:
        news = requests.get("https://cryptocurrency.cv/api/news").json()['data'][:10]
        score = sum(TextBlob(n['title']).sentiment.polarity for n in news)/len(news)
    except Exception as e:
        print("⚠️ Sentiment error:", e)
        score = 0

    if score > 0.05: return "Bullish"
    elif score < -0.05: return "Bearish"
    return "Neutral"

# ================= POSITION SIZE =================
def position_size(price, sl):
    risk_amount = CAPITAL * RISK_PER_TRADE
    risk_per_unit = abs(price - sl)
    if risk_per_unit == 0:
        return 0
    return round(risk_amount / risk_per_unit, 6)

# ================= SIGNAL =================
def check(df1, df15):
    last = df1.iloc[-1]
    prev = df1.iloc[-2]

    trend_up = df15['c'].iloc[-1] > df15['ema50'].iloc[-1]
    trend_down = df15['c'].iloc[-1] < df15['ema50'].iloc[-1]

    breakout_up = last['c'] > df1['h'].rolling(10).max().iloc[-2]
    breakout_down = last['c'] < df1['l'].rolling(10).min().iloc[-2]

    retest_up = prev['c'] < prev['ema20'] and last['c'] > last['ema20']
    retest_down = prev['c'] > prev['ema20'] and last['c'] < last['ema20']

    vol_ok = last['v'] > df1['v'].rolling(10).mean().iloc[-1]

    atr_percent = (last['atr']/last['c'])*100
    sideways = atr_percent < 0.15

    buy = breakout_up and retest_up and trend_up and vol_ok and not sideways
    sell = breakout_down and retest_down and trend_down and vol_ok and not sideways

    price = last['c']
    atr = last['atr']

    sl = price - atr if buy else price + atr
    tp = price + 2*atr if buy else price - 2*atr

    return buy, sell, price, sl, tp, sideways

# ================= LOG =================
def log_trade(data):
    with open("trades.csv", "a", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(data)

# ================= BOT =================
def run():
    print("✅ RUN FUNCTION STARTED")
    send("🚀 BOT LIVE")

    last_signal = "NONE"

    while True:
        try:
            print("🔄 Loop running...")

            df1 = safe_fetch('1m')
            df15 = safe_fetch('15m')

            buy, sell, price, sl, tp, sideways = check(df1, df15)
            print(f"📈 Buy: {buy}, Sell: {sell}, Sideways: {sideways}")

            sent = sentiment()

            now = datetime.now(pytz.timezone('Asia/Kolkata')).strftime("%H:%M:%S")

            qty = position_size(price, sl)

            if buy and last_signal != "BUY":
                send(f"🟢 BUY\nPrice:{price}\nSL:{sl}\nTP:{tp}\nQty:{qty}\nSent:{sent}\nTime:{now}")
                log_trade([now,"BUY",price,sl,tp,qty])
                last_signal = "BUY"

            elif sell and last_signal != "SELL":
                send(f"🔴 SELL\nPrice:{price}\nSL:{sl}\nTP:{tp}\nQty:{qty}\nSent:{sent}\nTime:{now}")
                log_trade([now,"SELL",price,sl,tp,qty])
                last_signal = "SELL"

            time.sleep(60)

        except Exception as e:
            print("❌ ERROR OCCURRED:", e)
            send(f"❌ ERROR: {e}")
            time.sleep(15)

# ================= HEARTBEAT =================
def heartbeat():
    while True:
        try:
            now = datetime.now(pytz.timezone('Asia/Kolkata')).strftime("%H:%M:%S")
            send(f"💓 BOT ALIVE\nTime: {now}")
            print("💓 Heartbeat sent")
        except Exception as e:
            print("Heartbeat error:", e)

        time.sleep(3600)

# ================= FLASK =================
app = Flask(__name__)

@app.route('/')
def home():
    return "Bot Running"

# ================= START =================
if __name__ == "__main__":
    print("🚀 STARTING BOT")

    t1 = threading.Thread(target=run)
    t1.start()

    t2 = threading.Thread(target=heartbeat)
    t2.start()

    app.run(host="0.0.0.0", port=10000)
