import ccxt
import pandas as pd
import ta
import time
import requests
from flask import Flask
import threading
from datetime import datetime
import pytz
import os

# ==============================
# 📌 TELEGRAM SETTINGS
# ==============================
TOKEN = os.getenv("8714289158:AAHQinJdvslG9f8qwfdX748WIXDgiXuBd9c")
CHAT_ID = os.getenv("6094849602")

def send_telegram(msg):
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    try:
        requests.post(url, data={"chat_id": CHAT_ID, "text": msg})
    except Exception as e:
        print("Telegram Error:", e)

# ==============================
# 🏦 EXCHANGE
# ==============================
exchange = ccxt.okx()

# ==============================
# ⚙️ SETTINGS
# ==============================
sleep_time = int(os.getenv("BOT_SLEEP", 30))
no_signal_interval = int(os.getenv("NO_SIGNAL_INTERVAL", 900))

# ==============================
# 🔹 SYMBOLS
# ==============================
symbols = [
    "BTC/USDT", "ETH/USDT", "BNB/USDT", "SOL/USDT", "XRP/USDT",
    "DOGE/USDT", "ADA/USDT", "AVAX/USDT", "DOT/USDT", "TRX/USDT",
    "LTC/USDT", "FIL/USDT", "NEAR/USDT", "SHIB/USDT", "PEPE/USDT",
    "ETC/USDT", "ZEC/USDT", "DASH/USDT", "XLM/USDT", "HBAR/USDT",
    "TON/USDT", "SUI/USDT"
]

# ==============================
# 📈 DATA FUNCTION
# ==============================
def get_data(symbol, timeframe):
    ohlcv = exchange.fetch_ohlcv(symbol, timeframe=timeframe, limit=100)
    df = pd.DataFrame(ohlcv, columns=['time','open','high','low','close','volume'])

    df['ma5'] = df['close'].rolling(5).mean()
    df['ma10'] = df['close'].rolling(10).mean()
    df['ma30'] = df['close'].rolling(30).mean()

    df['rsi'] = ta.momentum.RSIIndicator(df['close'], window=14).rsi()

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
# 🧐 STRATEGY
# ==============================
def check_signals(df1m, df15m):
    last1 = df1m.iloc[-1]
    prev1 = df1m.iloc[-2]
    last15 = df15m.iloc[-1]

    buy = (
        prev1['ma5'] < prev1['ma10'] and
        last1['ma5'] > last1['ma10'] and
        last1['rsi'] > 50 and
        last1['macd'] > last1['macd_signal'] and
        last1['stoch_k'] > last1['stoch_d'] and
        last15['close'] > last15['ma30']
    )

    sell = (
        prev1['ma5'] > prev1['ma10'] and
        last1['ma5'] < last1['ma10'] and
        last1['rsi'] < 50 and
        last1['macd'] < last1['macd_signal'] and
        last1['stoch_k'] < last1['stoch_d'] and
        last15['close'] < last15['ma30']
    )

    price = last1['close']
    atr = last1['atr']

    sl = price - atr if buy else price + atr
    tp = price + 2*atr if buy else price - 2*atr

    confidence = 50
    if last1['rsi'] > 60 or last1['rsi'] < 40:
        confidence += 15
    if abs(last1['ma5'] - last1['ma10']) > 5:
        confidence += 10

    accuracy = min(confidence, 100)

    return buy, sell, price, sl, tp, confidence, accuracy

# ==============================
# 🤖 BOT LOOP
# ==============================
def run_bot():
    print("Bot started...")
    send_telegram("✅ Bot LIVE")

    last_signal = {s: "" for s in symbols}
    last_no_signal = {s: 0 for s in symbols}
    last_heartbeat = 0

    while True:
        try:
            current_time = time.time()

            # ✅ HEARTBEAT EVERY 15 MIN
            if current_time - last_heartbeat > 900:
                ist = pytz.timezone('Asia/Kolkata')
                now = datetime.now(ist).strftime("%Y-%m-%d %I:%M:%S %p")

                send_telegram(f"""
🟢 BOT STATUS: RUNNING

✅ Server OK
✅ Loop Active
📊 Symbols: {len(symbols)}

⏱ {now}
""")
                last_heartbeat = current_time

            for symbol in symbols:
                try:
                    df1 = get_data(symbol, '1m')
                    df15 = get_data(symbol, '15m')

                    buy, sell, price, sl, tp, conf, acc = check_signals(df1, df15)

                    ist = pytz.timezone('Asia/Kolkata')
                    now = datetime.now(ist).strftime("%I:%M:%S %p")

                    if buy and last_signal[symbol] != "BUY":
                        send_telegram(f"🟢 BUY {symbol}\nPrice: {price}\nTP: {tp}\nSL: {sl}")
                        last_signal[symbol] = "BUY"

                    elif sell and last_signal[symbol] != "SELL":
                        send_telegram(f"🔴 SELL {symbol}\nPrice: {price}\nTP: {tp}\nSL: {sl}")
                        last_signal[symbol] = "SELL"

                    elif not buy and not sell:
                        if current_time - last_no_signal[symbol] > no_signal_interval:
                            send_telegram(f"⚪ NO SIGNAL {symbol}")
                            last_no_signal[symbol] = current_time

                except Exception as e:
                    print(symbol, e)

            time.sleep(sleep_time)

        except Exception as e:
            print("Main Error:", e)
            time.sleep(10)

# ==============================
# 🌐 FLASK
# ==============================
app = Flask(__name__)

@app.route('/')
def home():
    return "Bot Running"

# ==============================
# ▶ START
# ==============================
if __name__ == "__main__":
    threading.Thread(target=run_bot).start()
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 10000)))
