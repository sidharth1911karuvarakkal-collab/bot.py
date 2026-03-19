import requests
import pandas as pd
import numpy as np
import time
import os
from flask import Flask, request

# ================= CONFIG =================
TOKEN = os.environ.get("8714289158:AAHQinJdvslG9f8qwfdX748WIXDgiXuBd9c")      # Telegram bot token
CHAT_ID = os.environ.get("6094849602")  # Telegram chat ID
SYMBOL = os.environ.get("SYMBOL", "BTCUSDT")
CONFIDENCE_THRESHOLD = 75

BINANCE_URL = "https://api.binance.com/api/v3/klines"

app = Flask(__name__)
bot_running = False

# ================= ROOT ROUTE =================
@app.route("/", methods=["GET"])
def home():
    return "Bot is running! ✅"

# ================= TELEGRAM =================
def send_telegram(msg):
    try:
        url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
        requests.post(url, data={"chat_id": CHAT_ID, "text": msg})
    except Exception as e:
        print("Telegram Error:", e)

# ================= DATA FETCH =================
def get_data(interval="1m", limit=200):
    params = {"symbol": SYMBOL, "interval": interval, "limit": limit}
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

    delta = df["close"].diff()
    gain = delta.clip(lower=0).rolling(14).mean()
    loss = (-delta.clip(upper=0)).rolling(14).mean()
    rs = gain / loss
    df["rsi"] = 100 - (100 / (1 + rs))

    ema12 = df["close"].ewm(span=12).mean()
    ema26 = df["close"].ewm(span=26).mean()
    df["macd"] = ema12 - ema26
    df["signal"] = df["macd"].ewm(span=9).mean()
    return df

# ================= SIGNAL GENERATION =================
def generate_signal(hf, mf, lf):
    score = 0
    reasons = []

    # High timeframe
    latest = hf.iloc[-1]
    if latest["ema20"] > latest["ema50"]:
        score += 8; reasons.append("1h EMA Bull")
    else: score -= 8; reasons.append("1h EMA Bear")
    if latest["sma50"] > latest["sma200"]:
        score += 4; reasons.append("1h SMA Bull")
    else: score -= 4; reasons.append("1h SMA Bear")
    if latest["macd"] > latest["signal"]:
        score += 3; reasons.append("1h MACD Bull")
    else: score -= 3; reasons.append("1h MACD Bear")

    # Medium timeframe
    latest = mf.iloc[-1]
    if latest["ema20"] > latest["ema50"]:
        score += 6; reasons.append("15m EMA Bull")
    else: score -= 6; reasons.append("15m EMA Bear")
    if latest["sma50"] > latest["sma200"]:
        score += 4; reasons.append("15m SMA Bull")
    else: score -= 4; reasons.append("15m SMA Bear")
    if latest["macd"] > latest["signal"]:
        score += 3; reasons.append("15m MACD Bull")
    else: score -= 3; reasons.append("15m MACD Bear")

    # Low timeframe
    latest = lf.iloc[-1]
    if latest["close"] > latest["ema20"]:
        score += 5; reasons.append("1m Price>EMA20")
    else: score -= 5; reasons.append("1m Price<EMA20")
    if latest["macd"] > latest["signal"]:
        score += 3; reasons.append("1m MACD Bull")
    else: score -= 3; reasons.append("1m MACD Bear")

    confidence = max(0, min(100, int(score*2.5)))
    if confidence >= CONFIDENCE_THRESHOLD:
        return "BUY", confidence, reasons
    elif confidence <= (100-CONFIDENCE_THRESHOLD):
        return "SELL", confidence, reasons
    else:
        return None, confidence, reasons

# ================= BOT LOOP =================
def run_bot():
    global bot_running
    send_telegram("🚀 Bot Started 24/7 (1h+15m+1m)")
    while bot_running:
        try:
            hf = calculate_indicators(get_data("1h",200))
            mf = calculate_indicators(get_data("15m",200))
            lf = calculate_indicators(get_data("1m",200))
            sig, conf, reason = generate_signal(hf, mf, lf)
            if sig:
                price = lf.iloc[-1]["close"]
                send_telegram(f"📊 SIGNAL: {sig}\n💰 Price: {price}\n🔥 Confidence: {conf}%\n📌 Reasons: {', '.join(reason)}")
            time.sleep(60)
        except Exception as e:
            send_telegram(f"⚠️ Error: {e}")
            time.sleep(60)

# ================= TELEGRAM WEBHOOK =================
@app.route("/webhook", methods=["POST"])
def webhook():
    global bot_running
    data = request.json
    if "message" in data:
        text = data["message"]["text"]
        hf = calculate_indicators(get_data("1h",200))
        mf = calculate_indicators(get_data("15m",200))
        lf = calculate_indicators(get_data("1m",200))
        sig, conf, reason = generate_signal(hf, mf, lf)
        price = lf.iloc[-1]["close"]
        if text=="1":
            send_telegram(f"📊 SIGNAL: {sig if sig else 'No Signal'}\n💰 Price: {price}\n🔥 Confidence: {conf}%\n📌 Reasons: {', '.join(reason)}")
        elif text.lower()=="start" and not bot_running:
            bot_running = True
            run_bot()
    return {"ok": True}

# ================= START =================
if __name__=="__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
