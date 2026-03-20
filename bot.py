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
# 📌 TELEGRAM SETTINGS (from ENV)
# ==============================
TOKEN = os.getenv("8714289158:AAHQinJdvslG9f8qwfdX748WIXDgiXuBd9c")
CHAT_ID = os.getenv("6094849602")

def send_telegram(msg):
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    try:
        res = requests.post(url, data={"chat_id": CHAT_ID, "text": msg})
        print("Telegram:", res.text)
    except Exception as e:
        print("Telegram Error:", e)

# ==============================
# 🏦 EXCHANGE
# ==============================
exchange = ccxt.okx()

# ==============================
# ⚙️ SETTINGS
# ==============================
port = int(os.getenv("RENDER_PORT", 10000))
sleep_time = int(os.getenv("BOT_SLEEP", 30))
no_signal_interval = int(os.getenv("NO_SIGNAL_INTERVAL", 900))  # seconds (15 min) per symbol

# ==============================
# 🔹 SYMBOLS LIST
# ==============================
symbols = [
    "ETC/USDT", "BTC/USDT", "XAU/USD", "NIFTY/50", "ETH/USDT", "ZEC/USDT",
    "ZEC/USDT Pro", "DASH/USDT", "US100", "XAG/USD Pro", "EUR/USD", "BTC/USDT Pro",
    "XRP/USDT Pro", "BNB/USDT Pro", "XLM/USDT", "USOIL", "TON/USDT", "TRUMP/USDT",
    "SUI/USDT", "HBAR/USDT", "ETH/USDT", "BNB/USDT", "SOL/USDT", "TRX/USDT Pro",
    "DOGE/USDT Pro", "SOL/USDT Pro", "DAX40", "DOT/USDT", "FIL/USDT", "TRX/USDT",
    "LTC/USDT", "ADA/USDT", "AVAX/USDT", "GBP/USD", "USD/JPY", "XRP/USDT", "DOGE/USDT",
    "AUD/USD", "USD/CAD", "USD/CHF", "EUR/AUD", "EUR/CAD", "AUD/NZD", "JP225",
    "XAU/USD Mini", "NEAR/USDT", "SHIB/USDT", "UKOIL", "PEPE/USDT"
]

# ==============================
# 📈 DATA FUNCTION
# ==============================
def get_data(symbol, timeframe):
    ohlcv = exchange.fetch_ohlcv(symbol, timeframe=timeframe, limit=100)
    df = pd.DataFrame(ohlcv, columns=['time','open','high','low','close','volume'])

    # Moving averages
    df['ma5'] = df['close'].rolling(5).mean()
    df['ma10'] = df['close'].rolling(10).mean()
    df['ma30'] = df['close'].rolling(30).mean()
    df['ema5'] = df['close'].ewm(span=5, adjust=False).mean()
    df['ema10'] = df['close'].ewm(span=10, adjust=False).mean()

    # RSI
    df['rsi'] = ta.momentum.RSIIndicator(df['close'], window=14).rsi()

    # MACD
    macd = ta.trend.MACD(df['close'], window_slow=26, window_fast=12, window_sign=9)
    df['macd'] = macd.macd()
    df['macd_signal'] = macd.macd_signal()

    # Bollinger Bands
    bb = ta.volatility.BollingerBands(df['close'], window=20, window_dev=2)
    df['bb_upper'] = bb.bollinger_hband()
    df['bb_lower'] = bb.bollinger_lband()
    df['bb_middle'] = bb.bollinger_mavg()

    # ATR for dynamic SL/TP
    df['atr'] = ta.volatility.AverageTrueRange(df['high'], df['low'], df['close'], window=14).average_true_range()

    # Stochastic
    stoch = ta.momentum.StochasticOscillator(df['high'], df['low'], df['close'], window=14, smooth_window=3)
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

    # ENTRY (1m)
    buy_entry = (
        prev1['ma5'] < prev1['ma10'] and
        last1['ma5'] > last1['ma10'] and
        last1['rsi'] > 50 and
        last1['macd'] > last1['macd_signal'] and
        last1['close'] > last1['bb_lower'] and
        last1['stoch_k'] > last1['stoch_d']
    )

    sell_entry = (
        prev1['ma5'] > prev1['ma10'] and
        last1['ma5'] < last1['ma10'] and
        last1['rsi'] < 50 and
        last1['macd'] < last1['macd_signal'] and
        last1['close'] < last1['bb_upper'] and
        last1['stoch_k'] < last1['stoch_d']
    )

    # TREND (15m)
    trend_up = last15['close'] > last15['ma30']
    trend_down = last15['close'] < last15['ma30']

    buy = buy_entry and trend_up
    sell = sell_entry and trend_down

    price = last1['close']
    atr = last1['atr'] if not pd.isna(last1['atr']) else 0

    # Dynamic SL / TP
    sl = price - atr if buy else price + atr
    tp = price + 2*atr if buy else price - 2*atr

    # Confidence calculation
    confidence = 50
    if last1['rsi'] > 60 or last1['rsi'] < 40:
        confidence += 15
    if abs(last1['ma5'] - last1['ma10']) > 5:
        confidence += 10
    if (last1['macd'] > last1['macd_signal'] and buy) or (last1['macd'] < last1['macd_signal'] and sell):
        confidence += 10
    if (last1['stoch_k'] > last1['stoch_d'] and buy) or (last1['stoch_k'] < last1['stoch_d'] and sell):
        confidence += 10
    if trend_up or trend_down:
        confidence += 15

    accuracy = min(confidence, 100)

    # Reason for no signal
    reason = ""
    if not buy and not sell:
        reason = "Conditions not met: "
        if not (prev1['ma5'] < prev1['ma10'] and last1['ma5'] > last1['ma10']):
            reason += "MA crossover not met. "
        if not (last1['rsi'] > 50 if buy_entry else last1['rsi'] < 50):
            reason += "RSI condition not met. "
        if not ((last1['macd'] > last1['macd_signal'] and buy_entry) or (last1['macd'] < last1['macd_signal'] and sell_entry)):
            reason += "MACD condition not met. "
        if not ((last1['stoch_k'] > last1['stoch_d'] and buy_entry) or (last1['stoch_k'] < last1['stoch_d'] and sell_entry)):
            reason += "Stochastic condition not met. "
        if not ((trend_up if buy_entry else trend_down)):
            reason += "Trend not aligned."

    return buy, sell, price, sl, tp, confidence, accuracy, reason

# ==============================
# 🤖 BOT LOOP WITH SPAM REDUCTION
# ==============================
def run_bot():
    print("Bot started...")
    send_telegram("✅ Upgraded Bot LIVE for all symbols")

    last_signal_dict = {symbol: "" for symbol in symbols}
    last_no_signal_time = {symbol: 0 for symbol in symbols}

    while True:
        try:
            for symbol in symbols:
                try:
                    df1m = get_data(symbol, '1m')
                    df15m = get_data(symbol, '15m')

                    buy, sell, price, sl, tp, confidence, accuracy, reason = check_signals(df1m, df15m)

                    ist = pytz.timezone('Asia/Kolkata')
                    now = datetime.now(ist).strftime("%Y-%m-%d %I:%M:%S %p")

                    last_signal = last_signal_dict[symbol]

                    if buy and last_signal != "BUY":
                        msg = f"""
💰 BUY SIGNAL ({symbol})

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
                        last_signal_dict[symbol] = "BUY"

                    elif sell and last_signal != "SELL":
                        msg = f"""
❌ SELL SIGNAL ({symbol})

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
                        last_signal_dict[symbol] = "SELL"

                    elif not buy and not sell:
                        current_time = time.time()
                        # Only send NO SIGNAL if interval passed
                        if current_time - last_no_signal_time[symbol] > no_signal_interval:
                            msg = f"""
⚪ NO SIGNAL ({symbol})

📊 Confidence: {confidence}%
📈 Accuracy: {accuracy}%
📝 Reason: {reason}

⏱ Time: {now}
"""
                            send_telegram(msg)
                            last_no_signal_time[symbol] = current_time

                except Exception as e_sym:
                    print(f"Error for {symbol}: {e_sym}")

            time.sleep(sleep_time)

        except Exception as e:
            print("Error in bot loop:", e)
            time.sleep(10)

# ==============================
# 🌐 FLASK
# ==============================
app = Flask(__name__)

@app.route('/')
def home():
    print("Ping received")
    return "🚀 Upgraded Multi-Symbol Bot Running!"

# ==============================
# ▴ START
# ==============================
if __name__ == "__main__":
    threading.Thread(target=run_bot).start()
    app.run(host="0.0.0.0", port=int(os.getenv("RENDER_PORT", 10000)))
