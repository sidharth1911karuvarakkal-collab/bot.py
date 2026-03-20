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
# 🔹 SYMBOLS
# ==============================
symbols = [
    "BTC/USDT","ETH/USDT","BNB/USDT","SOL/USDT","XRP/USDT",
    "DOGE/USDT","ADA/USDT","AVAX/USDT","DOT/USDT","TRX/USDT"
]

# ==============================
# ⚙️ CONTROL
# ==============================
last_signal_time = {s: 0 for s in symbols}
last_signal_type = {s: "" for s in symbols}
cooldown = 300
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
# 🧠 SCORING STRATEGY
# ==============================
def check_signals(df1m, df15m):
    last = df1m.iloc[-1]
    prev = df1m.iloc[-2]
    trend = df15m.iloc[-1]

    score = 0
    reasons = []

    # MA crossover
    if prev['ma5'] < prev['ma10'] and last['ma5'] > last['ma10']:
        score += 1
        reasons.append("MA Bullish")
    elif prev['ma5'] > prev['ma10'] and last['ma5'] < last['ma10']:
        score += 1
        reasons.append("MA Bearish")

    # EMA
    if last['ema5'] > last['ema10']:
        score += 1
        reasons.append("EMA Bullish")
    else:
        score += 1
        reasons.append("EMA Bearish")

    # RSI relaxed
    if last['rsi'] > 45:
        score += 1
        reasons.append("RSI Strong")
    elif last['rsi'] < 55:
        score += 1
        reasons.append("RSI Weak")

    # MACD
    if last['macd'] > last['macd_signal']:
        score += 1
        reasons.append("MACD Bullish")
    else:
        score += 1
        reasons.append("MACD Bearish")

    # Stochastic
    if last['stoch_k'] > last['stoch_d']:
        score += 1
        reasons.append("Stoch Bullish")
    else:
        score += 1
        reasons.append("Stoch Bearish")

    # Bollinger (optional boost)
    if last['close'] < last['bb_lower']:
        score += 1
        reasons.append("BB Oversold")
    elif last['close'] > last['bb_upper']:
        score += 1
        reasons.append("BB Overbought")

    # Trend (mandatory)
    trend_up = trend['close'] > trend['ma30']
    trend_down = trend['close'] < trend['ma30']

    buy = score >= 4 and trend_up
    sell = score >= 4 and trend_down

    price = last['close']
    atr = last['atr']

    sl = price - atr if buy else price + atr
    tp = price + 2*atr if buy else price - 2*atr

    confidence = int((score / 7) * 100)

    return buy, sell, price, sl, tp, confidence, score, reasons

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

            buy, sell, price, sl, tp, conf, score, reasons = check_signals(df1, df15)

            now = time.time()

            if now - last_signal_time[symbol] < cooldown:
                continue

            ist = datetime.now(pytz.timezone('Asia/Kolkata')).strftime("%H:%M:%S")

            if buy and last_signal_type[symbol] != "BUY":
                msg = f"""
🟢 BUY {symbol}

Price: {price}
TP: {tp}
SL: {sl}

Confidence: {conf}%
Score: {score}/7

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
Score: {score}/7

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
# ❤️ HEARTBEAT
# ==============================
def heartbeat():
    while True:
        ist = pytz.timezone('Asia/Kolkata')
        now = datetime.now(ist).strftime("%I:%M %p")
        send_telegram(f"💓 Bot Alive - {now}")
        time.sleep(900)

# ==============================
# 🚀 MAIN BOT
# ==============================
def run_bot():
    send_telegram("🚀 SCORING BOT LIVE")

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
    return "🚀 Scoring Bot Running"

# ==============================
# ▶ START
# ==============================
if __name__ == "__main__":
    threading.Thread(target=run_bot).start()
    app.run(host="0.0.0.0", port=10000)
