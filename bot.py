import ccxt
import pandas as pd
import ta
import time
import requests
from flask import Flask
import threading

# ==============================
# 🔑 TELEGRAM SETTINGS
# ==============================
TOKEN = "8714289158:AAHQinJdvslG9f8qwfdX748WIXDgiXuBd9c"
CHAT_ID = "6094849602"

def send_telegram(msg):
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    requests.post(url, data={"chat_id": CHAT_ID, "text": msg})

# ==============================
# 📊 EXCHANGE (SAFE IN INDIA)
# ==============================
exchange = ccxt.okx()
symbol = 'BTC/USDT'
timeframe = '15m'

# ==============================
# 📈 GET DATA + INDICATORS
# ==============================
def get_data():
    ohlcv = exchange.fetch_ohlcv(symbol, timeframe=timeframe, limit=100)
    df = pd.DataFrame(ohlcv, columns=['time','open','high','low','close','volume'])

    df['ma5'] = df['close'].rolling(5).mean()
    df['ma10'] = df['close'].rolling(10).mean()
    df['ma30'] = df['close'].rolling(30).mean()
    df['rsi'] = ta.momentum.RSIIndicator(df['close'], window=14).rsi()

    return df

# ==============================
# 🤖 STRATEGY LOGIC
# ==============================
def check_signals(df):
    last = df.iloc[-1]
    prev = df.iloc[-2]

    # 🔥 BUY (EARLY + CONFIRMATION)
    buy = (
        prev['ma5'] < prev['ma10'] and   # crossover
        last['ma5'] > last['ma10'] and
        last['rsi'] > 45 and            # momentum
        last['close'] > last['ma30']    # trend filter
    )

    # 🔥 SELL (REVERSE)
    sell = (
        prev['ma5'] > prev['ma10'] and
        last['ma5'] < last['ma10'] and
        last['rsi'] < 55 and
        last['close'] < last['ma30']
    )

    return buy, sell, last['close']

# ==============================
# 🤖 BOT LOOP
# ==============================
def run_bot():
    print("Bot started...")
    send_telegram("✅ Bot is live and working!")

    last_signal = ""

    while True:
        try:
            df = get_data()
            buy, sell, price = check_signals(df)

            if buy and last_signal != "BUY":
                msg = f"🟢 BUY SIGNAL\nPrice: {price}"
                print(msg)
                send_telegram(msg)
                last_signal = "BUY"

            elif sell and last_signal != "SELL":
                msg = f"🔴 SELL SIGNAL\nPrice: {price}"
                print(msg)
                send_telegram(msg)
                last_signal = "SELL"

            time.sleep(60)

        except Exception as e:
            print("Error:", e)
            time.sleep(10)

# ==============================
# 🌐 FLASK (FOR RENDER FREE)
# ==============================
app = Flask(__name__)

@app.route('/')
def home():
    return "🚀 BTC Bot Running Successfully!"

# ==============================
# ▶️ START
# ==============================
if __name__ == "__main__":
    threading.Thread(target=run_bot).start()
    app.run(host="0.0.0.0", port=10000)
