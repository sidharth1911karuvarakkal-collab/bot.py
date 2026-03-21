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
# 🔑 TELEGRAM SETTINGS
# ==============================
TOKEN = "8714289158:AAHQinJdvslG9f8qwfdX748WIXDgiXuBd9c"
CHAT_ID = "6094849602"

def send_telegram(msg):
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    try:
        res = requests.post(url, data={"chat_id": CHAT_ID, "text": msg})
        print("Telegram:", res.text)
    except Exception as e:
        print("Telegram Error:", e)

# ==============================
# 📊 EXCHANGE
# ==============================
exchange = ccxt.okx()
symbol = 'BTC/USDT'

# ==============================
# 📈 DATA FUNCTION
# ==============================
def get_data(timeframe):
    ohlcv = exchange.fetch_ohlcv(symbol, timeframe=timeframe, limit=100)
    df = pd.DataFrame(ohlcv, columns=['time','open','high','low','close','volume'])

    # Main Indicators
    df['ma5'] = df['close'].rolling(5).mean()
    df['ma10'] = df['close'].rolling(10).mean()
    df['ma30'] = df['close'].rolling(30).mean()
    df['rsi'] = ta.momentum.RSIIndicator(df['close'], window=14).rsi()

    # Sub Indicators
    # MACD
    macd = ta.trend.MACD(df['close'], window_slow=26, window_fast=12, window_sign=9)
    df['macd'] = macd.macd()
    df['macd_signal'] = macd.macd_signal()

    # Bollinger Bands
    bb = ta.volatility.BollingerBands(df['close'], window=20, window_dev=2)
    df['bb_high'] = bb.bollinger_hband()
    df['bb_low'] = bb.bollinger_lband()

    # EMA (20 period)
    df['ema20'] = df['close'].ewm(span=20, adjust=False).mean()

    return df

# ==============================
# 🤖 STRATEGY
# ==============================
def check_signals(df1m, df15m):
    last1 = df1m.iloc[-1]
    prev1 = df1m.iloc[-2]
    last15 = df15m.iloc[-1]

    used_indicators = []

    # =================
    # MAIN INDICATORS
    # =================
    buy_main = prev1['ma5'] < prev1['ma10'] and last1['ma5'] > last1['ma10'] and last1['rsi'] > 50
    sell_main = prev1['ma5'] > prev1['ma10'] and last1['ma5'] < last1['ma10'] and last1['rsi'] < 50

    if buy_main:
        used_indicators += ["MA", "RSI"]
    if sell_main:
        used_indicators += ["MA", "RSI"]

    # =================
    # TREND CONFIRMATION (15m)
    # =================
    trend_up = last15['close'] > last15['ma30']
    trend_down = last15['close'] < last15['ma30']

    # =================
    # SUB INDICATORS
    # =================
    sub_buy = False
    sub_sell = False

    # MACD
    if last1['macd'] > last1['macd_signal']:
        sub_buy = True
        used_indicators.append("MACD")
    elif last1['macd'] < last1['macd_signal']:
        sub_sell = True
        used_indicators.append("MACD")

    # Bollinger
    if last1['close'] < last1['bb_low']:
        sub_buy = True
        used_indicators.append("Bollinger")
    elif last1['close'] > last1['bb_high']:
        sub_sell = True
        used_indicators.append("Bollinger")

    # EMA
    if last1['close'] > last1['ema20']:
        sub_buy = True
        used_indicators.append("EMA")
    elif last1['close'] < last1['ema20']:
        sub_sell = True
        used_indicators.append("EMA")

    # =================
    # FINAL SIGNAL
    # =================
    buy_signal = buy_main and (sub_buy or trend_up)
    sell_signal = sell_main and (sub_sell or trend_down)

    price = last1['close']
    sl = price * 0.995 if buy_signal else price * 1.005
    tp = price * 1.01 if buy_signal else price * 0.99

    # Confidence (same logic)
    confidence = 50
    if last1['rsi'] > 60 or last1['rsi'] < 40:
        confidence += 15
    if abs(last1['ma5'] - last1['ma10']) > 5:
        confidence += 15
    if trend_up or trend_down:
        confidence += 20
    accuracy = min(confidence, 90)

    return buy_signal, sell_signal, price, sl, tp, confidence, accuracy, list(set(used_indicators))

# ==============================
# 🤖 BOT LOOP WITH HEARTBEAT
# ==============================
def run_bot():
    print("Bot started...")
    send_telegram("✅ Bot LIVE (1m entry + 15m trend)")

    last_signal = ""
    last_heartbeat = 0
    heartbeat_interval = 3600  # 1 hour

    while True:
        try:
            df1m = get_data('1m')
            df15m = get_data('15m')

            buy, sell, price, sl, tp, confidence, accuracy, used_indicators = check_signals(df1m, df15m)

            # IST TIME
            ist = pytz.timezone('Asia/Kolkata')
            now = datetime.now(ist).strftime("%Y-%m-%d %I:%M:%S %p")

            # 🔥 AUTO SIGNALS
            if buy and last_signal != "BUY":
                msg = f"""
🟢 BUY SIGNAL

💰 Price: {price}
🎯 TP: {tp}
🛑 SL: {sl}

📊 Confidence: {confidence}%
📈 Accuracy: {accuracy}%

📌 Indicators Used: {', '.join(used_indicators)}
⏱ Time: {now}
📉 Entry TF: 1m
📊 Trend TF: 15m
"""
                send_telegram(msg)
                last_signal = "BUY"

            elif sell and last_signal != "SELL":
                msg = f"""
🔴 SELL SIGNAL

💰 Price: {price}
🎯 TP: {tp}
🛑 SL: {sl}

📊 Confidence: {confidence}%
📈 Accuracy: {accuracy}%

📌 Indicators Used: {', '.join(used_indicators)}
⏱ Time: {now}
📉 Entry TF: 1m
📊 Trend TF: 15m
"""
                send_telegram(msg)
                last_signal = "SELL"

            # 💓 HEARTBEAT
            current_time = time.time()
            if current_time - last_heartbeat > heartbeat_interval:
                send_telegram(f"💓 Heartbeat: Bot alive at {now}")
                last_heartbeat = current_time

            time.sleep(30)

        except Exception as e:
            print("Error:", e)
            time.sleep(10)

# ==============================
# 🌐 FLASK
# ==============================
app = Flask(__name__)

@app.route('/')
def home():
    print("Ping received")
    return "🚀 BTC Bot Running!"

# ==============================
# ▶️ START
# ==============================
if __name__ == "__main__":
    threading.Thread(target=run_bot).start()
    app.run(host="0.0.0.0", port=10000)
