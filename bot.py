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
# 🏦 EXCHANGE
# ==============================
exchange = ccxt.okx({"enableRateLimit": True})

# ==============================
# 🔹 SYMBOLS (ONLY 2)
# ==============================
symbols = ["BTC/USDT", "ETH/USDT"]

# ==============================
# ⚙️ CONTROL
# ==============================
last_signal_time = {s: 0 for s in symbols}
last_signal_type = {s: "" for s in symbols}
cooldown = 300   # 5 min
api_delay = 1

# ==============================
# 📈 SAFE FETCH
# ==============================
def safe_fetch(symbol, timeframe):
    for _ in range(3):
        try:
            return exchange.fetch_ohlcv(symbol, timeframe, limit=100)
        except:
            time.sleep(2)
    return None

# ==============================
# 📊 INDICATORS
# ==============================
def get_data(symbol, tf):
    ohlcv = safe_fetch(symbol, tf)
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
# 🧠 SCORING STRATEGY (FIXED)
# ==============================
def check_signals(df1m, df15m):
    last = df1m.iloc[-1]
    prev = df1m.iloc[-2]
    trend = df15m.iloc[-1]

    buy_score = 0
    sell_score = 0
    reasons = []

    # MA crossover
    if prev['ma5'] < prev['ma10'] and last['ma5'] > last['ma10']:
        buy_score += 1
        reasons.append("MA Bullish")
    elif prev['ma5'] > prev['ma10'] and last['ma5'] < last['ma10']:
        sell_score += 1
        reasons.append("MA Bearish")

    # EMA
    if last['ema5'] > last['ema10']:
        buy_score += 1
        reasons.append("EMA Bullish")
    else:
        sell_score += 1
        reasons.append("EMA Bearish")

    # RSI
    if last['rsi'] > 55:
        buy_score += 1
        reasons.append("RSI Strong")
    elif last['rsi'] < 45:
        sell_score += 1
        reasons.append("RSI Weak")

    # MACD
    if last['macd'] > last['macd_signal']:
        buy_score += 1
        reasons.append("MACD Bullish")
    else:
        sell_score += 1
        reasons.append("MACD Bearish")

    # Stochastic
    if last['stoch_k'] > last['stoch_d']:
        buy_score += 1
        reasons.append("Stoch Bullish")
    else:
        sell_score += 1
        reasons.append("Stoch Bearish")

    # Bollinger
    if last['close'] < last['bb_lower']:
        buy_score += 1
        reasons.append("BB Oversold")
    elif last['close'] > last['bb_upper']:
        sell_score += 1
        reasons.append("BB Overbought")

    # Trend filter
    trend_up = trend['close'] > trend['ma30']
    trend_down = trend['close'] < trend['ma30']

    buy = buy_score >= 4 and trend_up
    sell = sell_score >= 4 and trend_down

    price = last['close']
    atr = last['atr']

    sl = price - atr if buy else price + atr
    tp = price + 2*atr if buy else price - 2*atr

    confidence = int((max(buy_score, sell_score) / 6) * 100)

    return buy, sell, price, sl, tp, confidence, buy_score, sell_score, reasons

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

            buy, sell, price, sl, tp, conf, b_score, s_score, reasons = check_signals(df1, df15)

            now = time.time()

            if now - last_signal_time[symbol] < cooldown:
                time.sleep(api_delay)
                continue

            ist = datetime.now(pytz.timezone('Asia/Kolkata')).strftime("%H:%M:%S")

            if buy and last_signal_type[symbol] != "BUY":
                msg = f"""
🟢 BUY {symbol}

Price: {price}
TP: {tp}
SL: {sl}

Confidence: {conf}%
Buy Score: {b_score}
Sell Score: {s_score}

Reason:
{', '.join(reasons)}

Time: {ist}
"""
                send_telegram(msg)
                last_signal_time[symbol] = now
                last_signal_type[symbol] = "BUY"

            elif sell and last_signal_type[symbol] != "SELL":
                msg = f"""
🔴 SELL {symbol}

Price: {price}
TP: {tp}
SL: {sl}

Confidence: {conf}%
Buy Score: {b_score}
Sell Score: {s_score}

Reason:
{', '.join(reasons)}

Time: {ist}
"""
                send_telegram(msg)
                last_signal_time[symbol] = now
                last_signal_type[symbol] = "SELL"

            time.sleep(api_delay)

        except Exception as e:
            print(symbol, e)
            time.sleep(5)

# ==============================
# ❤️ HEARTBEAT (15 min)
# ==============================
def heartbeat():
    while True:
        now = datetime.now(pytz.timezone('Asia/Kolkata')).strftime("%I:%M %p")
        send_telegram(f"💓 Bot Alive - {now}")
        time.sleep(900)

# ==============================
# 🚀 MAIN BOT
# ==============================
def run_bot():
    send_telegram("🚀 BTC + ETH BOT LIVE")

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
    return "🚀 Bot Running"

# ==============================
# ▶ START
# ==============================
if __name__ == "__main__":
    threading.Thread(target=run_bot).start()
    app.run(host="0.0.0.0", port=10000)
