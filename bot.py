import ccxt
import pandas as pd
import ta
import time
import requests
from flask import Flask
import threading
from datetime import datetime
import pytz

# ==============================
# 🔐 TELEGRAM SETTINGS
# ==============================
TOKEN = "8714289158:AAHQinJdvslG9f8qwfdX748WIXDgiXuBd9c"
CHAT_ID = "6094849602"

def send_telegram(msg):
    try:
        requests.post(
            f"https://api.telegram.org/bot{TOKEN}/sendMessage",
            data={"chat_id": CHAT_ID, "text": msg}
        )
    except:
        pass

# ==============================
# 🏦 EXCHANGE (RATE LIMIT SAFE)
# ==============================
exchange = ccxt.okx({
    "enableRateLimit": True
})

# ==============================
# 🔹 SYMBOLS
# ==============================
symbols = [
    "BTC/USDT","ETH/USDT","BNB/USDT","SOL/USDT","XRP/USDT",
    "DOGE/USDT","ADA/USDT","AVAX/USDT","DOT/USDT","TRX/USDT"
]

# ==============================
# ⚙️ GLOBAL CONTROL
# ==============================
last_signal_time = {s: 0 for s in symbols}
last_signal_type = {s: "" for s in symbols}
cooldown = 300   # 5 min per symbol
api_delay = 1    # prevent rate limit

# ==============================
# 📈 SAFE DATA FETCH
# ==============================
def safe_fetch(symbol, timeframe):
    for _ in range(3):  # retry 3 times
        try:
            data = exchange.fetch_ohlcv(symbol, timeframe, limit=100)
            return data
        except Exception as e:
            print(f"Retry {symbol}:", e)
            time.sleep(2)
    return None

# ==============================
# 📊 INDICATORS
# ==============================
def get_data(symbol, timeframe):
    ohlcv = safe_fetch(symbol, timeframe)
    if ohlcv is None:
        return None

    df = pd.DataFrame(ohlcv, columns=['time','open','high','low','close','volume'])

    df['ma5'] = df['close'].rolling(5).mean()
    df['ma10'] = df['close'].rolling(10).mean()
    df['ma30'] = df['close'].rolling(30).mean()

    df['ema5'] = df['close'].ewm(span=5).mean()
    df['ema10'] = df['close'].ewm(span=10).mean()

    df['rsi'] = ta.momentum.RSIIndicator(df['close'], 14).rsi()

    macd = ta.trend.MACD(df['close'])
    df['macd'] = macd.macd()
    df['macd_signal'] = macd.macd_signal()

    bb = ta.volatility.BollingerBands(df['close'])
    df['bb_upper'] = bb.bollinger_hband()
    df['bb_lower'] = bb.bollinger_lband()

    df['atr'] = ta.volatility.AverageTrueRange(
        df['high'], df['low'], df['close']).average_true_range()

    stoch = ta.momentum.StochasticOscillator(
        df['high'], df['low'], df['close'])
    df['stoch_k'] = stoch.stoch()
    df['stoch_d'] = stoch.stoch_signal()

    return df

# ==============================
# 🧠 STRATEGY
# ==============================
def check_signals(df1m, df15m):
    last = df1m.iloc[-1]
    prev = df1m.iloc[-2]
    trend = df15m.iloc[-1]

    buy = (
        prev['ma5'] < prev['ma10'] and
        last['ma5'] > last['ma10'] and
        last['rsi'] > 50 and
        last['macd'] > last['macd_signal'] and
        last['ema5'] > last['ema10'] and
        last['stoch_k'] > last['stoch_d'] and
        last['close'] > last['bb_lower'] and
        trend['close'] > trend['ma30']
    )

    sell = (
        prev['ma5'] > prev['ma10'] and
        last['ma5'] < last['ma10'] and
        last['rsi'] < 50 and
        last['macd'] < last['macd_signal'] and
        last['ema5'] < last['ema10'] and
        last['stoch_k'] < last['stoch_d'] and
        last['close'] < last['bb_upper'] and
        trend['close'] < trend['ma30']
    )

    price = last['close']
    atr = last['atr']

    sl = price - atr if buy else price + atr
    tp = price + 2*atr if buy else price - 2*atr

    return buy, sell, price, sl, tp

# ==============================
# 🤖 PROCESS SYMBOL
# ==============================
def process_symbol(symbol):
    global last_signal_time, last_signal_type

    while True:
        try:
            df1 = get_data(symbol, '1m')
            df15 = get_data(symbol, '15m')

            if df1 is None or df15 is None:
                continue

            buy, sell, price, sl, tp = check_signals(df1, df15)

            now = time.time()

            # ⛔ COOLDOWN CONTROL
            if now - last_signal_time[symbol] < cooldown:
                continue

            # ⛔ DUPLICATE FILTER
            if buy and last_signal_type[symbol] != "BUY":
                send_telegram(f"🟢 BUY {symbol}\nPrice:{price}\nTP:{tp}\nSL:{sl}")
                last_signal_time[symbol] = now
                last_signal_type[symbol] = "BUY"

            elif sell and last_signal_type[symbol] != "SELL":
                send_telegram(f"🔴 SELL {symbol}\nPrice:{price}\nTP:{tp}\nSL:{sl}")
                last_signal_time[symbol] = now
                last_signal_type[symbol] = "SELL"

            time.sleep(api_delay)

        except Exception as e:
            print(symbol, e)
            time.sleep(5)

# ==============================
# ❤️ HEARTBEAT (15 MIN)
# ==============================
def heartbeat():
    while True:
        ist = pytz.timezone('Asia/Kolkata')
        now = datetime.now(ist).strftime("%I:%M %p")
        send_telegram(f"💓 Bot Alive - {now}")
        time.sleep(900)  # 15 min

# ==============================
# 🚀 MAIN BOT
# ==============================
def run_bot():
    send_telegram("🚀 PRO BOT LIVE")

    for sym in symbols:
        threading.Thread(target=process_symbol, args=(sym,), daemon=True).start()

    threading.Thread(target=heartbeat, daemon=True).start()

    while True:
        time.sleep(10)

# ==============================
# 🌐 FLASK
# ==============================
app = Flask(__name__)

@app.route('/')
def home():
    return "🚀 Production Bot Running"

# ==============================
# ▶ START
# ==============================
if __name__ == "__main__":
    threading.Thread(target=run_bot).start()
    app.run(host="0.0.0.0", port=10000)
