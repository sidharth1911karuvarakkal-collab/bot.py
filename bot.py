import requests
import pandas as pd
import numpy as np
import time
from flask import Flask, request

# ================= CONFIG =================
TOKEN = "8714289158:AAHQinJdvslG9f8qwfdX748WIXDgiXuBd9c"
CHAT_ID = "6094849602"
SYMBOL = "BTCUSDT"
INTERVAL = "1m"
CONFIDENCE_THRESHOLD = 75

BINANCE_URL = "https://api.binance.com/api/v3/klines"

app = Flask(__name__)
bot_running = False

# ================= TELEGRAM =================
def send_telegram(msg):
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    data = {"chat_id": CHAT_ID, "text": msg}
    requests.post(url, data=data)

# ================= DATA =================
def get_data(limit=200):
    params = {"symbol": SYMBOL, "interval": INTERVAL, "limit": limit}
    data = requests.get(BINANCE_URL, params=params).json()
    df = pd.DataFrame(data, columns=range(12))
    df = df[[0,1,2,3,4,5]]
    df.columns = ["time","open","high","low","close","volume"]
    df["close"] = df["close"].astype(float)
    return df

# ================= INDICATORS =================
def calculate_indicators(df):
    df["ema20"] = df["close"].ewm(span=20).mean()
    df["ema50"] = df["close"].ewm(span=50).mean()
    df["sma50"] = df["close"].rolling(50).mean()
    df["sma200"] = df["close"].rolling(200).mean()

    # RSI
    delta = df["close"].diff()
    gain = delta.clip(lower=0).rolling(14).mean()
    loss = (-delta.clip(upper=0)).rolling(14).mean()
    rs = gain / loss
    df["rsi"] = 100 - (100 / (1 + rs))

    # MACD
    ema12 = df["close"].ewm(span=12).mean()
    ema26 = df["close"].ewm(span=26).mean()
    df["macd"] = ema12 - ema26
    df["signal"] = df["macd"].ewm(span=9).mean()

    # Bollinger Bands
    df["sma20"] = df["close"].rolling(20).mean()
    df["std"] = df["close"].rolling(20).std()
    df["upper"] = df["sma20"] + (2 * df["std"])
    df["lower"] = df["sma20"] - (2 * df["std"])

    return df

# ================= SIGNAL GENERATION =================
def generate_signal(df):
    latest = df.iloc[-1]
    score = 0
    reasons = []

    # EMA Trend
    if latest["ema20"] > latest["ema50"]:
        score += 20
        reasons.append("EMA Bullish")
    else:
        score -= 20
        reasons.append("EMA Bearish")

    # SMA Trend
    if latest["sma50"] > latest["sma200"]:
        score += 10
        reasons.append("SMA Trend Bullish")
    else:
        score -= 10
        reasons.append("SMA Trend Bearish")

    # RSI
    if latest["rsi"] < 30:
        score += 20
        reasons.append("RSI Oversold")
    elif latest["rsi"] > 70:
        score -= 20
        reasons.append("RSI Overbought")

    # MACD
    if latest["macd"] > latest["signal"]:
        score += 15
        reasons.append("MACD Bullish")
    else:
        score -= 15
        reasons.append("MACD Bearish")

    # Bollinger
    if latest["close"] < latest["lower"]:
        score += 10
        reasons.append("Below BB (Reversal)")
    elif latest["close"] > latest["upper"]:
        score -= 10
        reasons.append("Above BB (Overbought)")

    # Price above EMA20
    if latest["close"] > latest["ema20"]:
        score += 10
    else:
        score -= 10

    confidence = max(0, min(100, score))

    if confidence >= CONFIDENCE_THRESHOLD:
        return "BUY", confidence, reasons
    elif confidence <= (100 - CONFIDENCE_THRESHOLD):
        return "SELL", confidence, reasons
    else:
        return None, confidence, reasons

# ================= RUN BOT LOOP =================
def run_bot():
    global bot_running
    send_telegram("🚀 Pro Bot Started 24/7")

    while bot_running:
        try:
            df = get_data()
            df = calculate_indicators(df)
            signal, confidence, reasons = generate_signal(df)

            if signal:
                price = df.iloc[-1]["close"]
                msg = f"""
📊 SIGNAL: {signal}
💰 Price: {price}
🔥 Confidence: {confidence}%

📌 Reasons: {', '.join(reasons)}
                """
                send_telegram(msg)

            time.sleep(60)

        except Exception as e:
            send_telegram(f"⚠️ Error: {str(e)}")
            time.sleep(60)

# ================= TELEGRAM WEBHOOK =================
@app.route("/webhook", methods=["POST"])
def webhook():
    global bot_running
    data = request.json

    if "message" in data:
        text = data["message"]["text"]

        if text == "1":  # One-time trigger
            df = get_data()
            df = calculate_indicators(df)
            signal, confidence, reasons = generate_signal(df)

            price = df.iloc[-1]["close"]
            msg = f"""
📊 SIGNAL: {signal if signal else 'No Signal'}
💰 Price: {price}
🔥 Confidence: {confidence}%

📌 Reasons: {', '.join(reasons)}
            """
            send_telegram(msg)
            return {"ok": True}

        if text.lower() == "start":  # 24/7 bot
            if not bot_running:
                bot_running = True
                run_bot()

    return {"ok": True}

# ================= START =================
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
