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
# 📌 TELEGRAM SETTINGS
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
# 🔔 TELEGRAM POLLING (NO SPAM)
# ==============================
last_update_id = None
last_command_time = 0
command_cooldown = 60   # seconds

def check_telegram_commands():
    global last_update_id, last_command_time

    url = f"https://api.telegram.org/bot{TOKEN}/getUpdates"
    params = {"timeout": 5}

    if last_update_id:
        params["offset"] = last_update_id + 1

    try:
        res = requests.get(url, params=params).json()

        for update in res.get("result", []):
            last_update_id = update["update_id"]

            if "message" in update:
                text = update["message"].get("text", "")
                current_time = time.time()

                # prevent spam
                if current_time - last_command_time < command_cooldown:
                    return None

                if text in ["1", "2"]:
                    last_command_time = current_time
                    return text  # return "1" or "2" for manual check

    except Exception as e:
        print("Polling error:", e)

    return None

# ==============================
# 🏦 EXCHANGE
# ==============================
exchange = ccxt.okx()
symbol = 'BTC/USDT'

# ==============================
# 📈 DATA FUNCTION
# ==============================
def get_data(timeframe):
    ohlcv = exchange.fetch_ohlcv(symbol, timeframe=timeframe, limit=100)
    df = pd.DataFrame(ohlcv, columns=['time','open','high','low','close','volume'])

    df['ma5'] = df['close'].rolling(5).mean()
    df['ma10'] = df['close'].rolling(10).mean()
    df['ma30'] = df['close'].rolling(30).mean()
    df['rsi'] = ta.momentum.RSIIndicator(df['close'], window=14).rsi()

    return df

# ==============================
# 🧐 STRATEGY
# ==============================
def check_signals(df1m, df15m):
    last1 = df1m.iloc[-1]
    prev1 = df1m.iloc[-2]
    last15 = df15m.iloc[-1]

    # ENTRY (1m)
    buy_entry = (
        prev1['ma5'] < prev1['ma10'] and
        last1['ma5'] > last1['ma10'] and
        last1['rsi'] > 50
    )

    sell_entry = (
        prev1['ma5'] > prev1['ma10'] and
        last1['ma5'] < last1['ma10'] and
        last1['rsi'] < 50
    )

    # TREND (15m)
    trend_up = last15['close'] > last15['ma30']
    trend_down = last15['close'] < last15['ma30']

    buy = buy_entry and trend_up
    sell = sell_entry and trend_down

    price = last1['close']

    # SL / TP
    sl = price * 0.995
    tp = price * 1.01

    if sell:
        sl = price * 1.005
        tp = price * 0.99

    # Confidence
    confidence = 50

    if last1['rsi'] > 60 or last1['rsi'] < 40:
        confidence += 15

    if abs(last1['ma5'] - last1['ma10']) > 5:
        confidence += 15

    if trend_up or trend_down:
        confidence += 20

    accuracy = min(confidence, 90)

    return buy, sell, price, sl, tp, confidence, accuracy

# ==============================
# 🤖 BOT LOOP
# ==============================
def run_bot():
    print("Bot started...")
    send_telegram("✅ Bot LIVE (1m entry + 15m trend)")

    last_signal = ""

    while True:
        try:
            # 1️⃣ Check manual commands
            cmd = check_telegram_commands()  # returns "1", "2", or None

            # 2️⃣ Fetch latest data
            df1m = get_data('1m')
            df15m = get_data('15m')

            # 3️⃣ Check auto strategy signals
            buy, sell, price, sl, tp, confidence, accuracy = check_signals(df1m, df15m)

            # IST Time
            ist = pytz.timezone('Asia/Kolkata')
            now = datetime.now(ist).strftime("%Y-%m-%d %I:%M:%S %p")

            # 4️⃣ AUTO SIGNALS
            if buy and last_signal != "BUY":
                msg = f"""
💰 BUY SIGNAL

💰 Price: {price}
🎯 TP: {tp}
🛑 SL: {sl}

📊 Confidence: {confidence}%
📈 Accuracy: {accuracy}%

⏱ Time: {now}
📝 Entry TF: 1m
📊 Trend TF: 15m
"""
                send_telegram(msg)
                last_signal = "BUY"

            elif sell and last_signal != "SELL":
                msg = f"""
❌ SELL SIGNAL

💰 Price: {price}
🎯 TP: {tp}
🛑 SL: {sl}

📊 Confidence: {confidence}%
📈 Accuracy: {accuracy}%

⏱ Time: {now}
📝 Entry TF: 1m
📊 Trend TF: 15m
"""
                send_telegram(msg)
                last_signal = "SELL"

            # 5️⃣ MANUAL COMMANDS
            if cmd in ["1", "2"]:
                last1 = df1m.iloc[-1]
                prev1 = df1m.iloc[-2]
                last15 = df15m.iloc[-1]

                reasons = []

                if cmd == "1":  # Manual BUY
                    if not buy:
                        if not (prev1['ma5'] < prev1['ma10'] and last1['ma5'] > last1['ma10']):
                            reasons.append("MA crossover condition not met")
                        if not (last1['rsi'] > 50):
                            reasons.append(f"RSI too low ({last1['rsi']:.2f})")
                        if not (last15['close'] > last15['ma30']):
                            reasons.append("15m trend not bullish")
                    else:
                        reasons.append("All conditions met ✅")

                    msg = f"""
💰 MANUAL BUY CHECK

💰 Price: {price}
🎯 TP: {tp}
🛑 SL: {sl}

📊 Confidence: {confidence}%
📈 Accuracy: {accuracy}%

⚡ Conditions: {' | '.join(reasons)}

⏱ Time: {now}
📝 Entry TF: 1m
📊 Trend TF: 15m
"""
                    send_telegram(msg)

                elif cmd == "2":  # Manual SELL
                    if not sell:
                        if not (prev1['ma5'] > prev1['ma10'] and last1['ma5'] < last1['ma10']):
                            reasons.append("MA crossover condition not met")
                        if not (last1['rsi'] < 50):
                            reasons.append(f"RSI too high ({last1['rsi']:.2f})")
                        if not (last15['close'] < last15['ma30']):
                            reasons.append("15m trend not bearish")
                    else:
                        reasons.append("All conditions met ✅")

                    msg = f"""
❌ MANUAL SELL CHECK

💰 Price: {price}
🎯 TP: {tp}
🛑 SL: {sl}

📊 Confidence: {confidence}%
📈 Accuracy: {accuracy}%

⚡ Conditions: {' | '.join(reasons)}

⏱ Time: {now}
📝 Entry TF: 1m
📊 Trend TF: 15m
"""
                    send_telegram(msg)

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
# ▴ START
# ==============================
if __name__ == "__main__":
    threading.Thread(target=run_bot).start()
    app.run(host="0.0.0.0", port=10000)
