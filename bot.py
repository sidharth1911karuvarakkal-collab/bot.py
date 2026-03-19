import requests
import pandas as pd
import numpy as np
import time
import os
from flask import Flask, request

# ================= CONFIG =================
TOKEN = os.environ.get("8714289158:AAHQinJdvslG9f8qwfdX748WIXDgiXuBd9c")  # Telegram bot token
CHAT_ID = os.environ.get("6094849602")  # Your Telegram chat ID
SYMBOL = os.environ.get("SYMBOL", "BTCUSDT")
CONFIDENCE_THRESHOLD = 75

BINANCE_URL = "https://api.binance.com/api/v3/klines"

app = Flask(__name__)
bot_running = False

# ================= TELEGRAM =================
def send_telegram(msg):
    try:
        url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
        data = {"chat_id": CHAT_ID, "text": msg}
        requests.post(url, data=data)
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
def generate_signal(hf_df, mf_df, lf_df):
    score = 0
    reasons = []

    # 1h Trend (High timeframe) - weight 40%
    latest_hf = hf_df.iloc[-1]
    hf_score = 0
    if latest_hf["ema20"] > latest_hf["ema50"]:
        hf_score += 20
        reasons.append("1h EMA Bullish")
    else:
        hf_score -= 20
        reasons.append("1h EMA Bearish")
    if latest_hf["sma50"] > latest_hf["sma200"]:
        hf_score += 10
        reasons.append("1h SMA Bullish")
    else:
        hf_score -= 10
        reasons.append("1h SMA Bearish")
    if latest_hf["macd"] > latest_hf["signal"]:
        hf_score += 10
        reasons.append("1h MACD Bullish")
    else:
        hf_score -= 10
        reasons.append("1h MACD Bearish")
    score += hf_score * 0.4

    # 15m Trend (Medium timeframe) - weight 35%
    latest_mf = mf_df.iloc[-1]
    mf_score = 0
    if latest_mf["ema20"] > latest_mf["ema50"]:
        mf_score += 15
        reasons.append("15m EMA Bullish")
    else:
        mf_score -= 15
        reasons.append("15m EMA Bearish")
    if latest_mf["sma50"] > latest_mf["sma200"]:
        mf_score += 10
        reasons.append("15m SMA Bullish")
    else:
        mf_score -= 10
        reasons.append("15m SMA Bearish")
    if latest_mf["macd"] > latest_mf["signal"]:
        mf_score += 10
        reasons.append("15m MACD Bullish")
    else:
        mf_score -= 10
        reasons.append("15m MACD Bearish")
    score += mf_score * 0.35

    # 1m Entry (Low timeframe) - weight 25%
    latest_lf = lf_df.iloc[-1]
    lf_score = 0
    if latest_lf["close"] > latest_lf["ema20"]:
        lf_score += 15
        reasons.append("1m Price above EMA20")
    else:
        lf_score -= 15
        reasons.append("1m Price below EMA20")
    if latest_lf["macd"] > latest_lf["signal"]:
        lf_score += 10
        reasons.append("1m MACD Bullish")
    else:
        lf_score -= 10
        reasons.append("1m MACD Bearish")
    score += lf_score * 0.25

    confidence = max(0, min(100, int(score)))

    if confidence >= CONFIDENCE_THRESHOLD:
        return "BUY", confidence, reasons
    elif confidence <= (100 - CONFIDENCE_THRESHOLD):
        return "SELL", confidence, reasons
    else:
        return None, confidence, reasons

# ================= BOT LOOP =================
def run_bot():
    global bot_running
    send_telegram("🚀 Multi-Timeframe Bot Started (1h+15m+1m) 24/7")

    while bot_running:
        try:
            hf_df = calculate_indicators(get_data("1h", 200))
            mf_df = calculate_indicators(get_data("15m", 200))
            lf_df = calculate_indicators(get_data("1m", 200))

            signal, confidence, reasons = generate_signal(hf_df, mf_df, lf_df)

            if signal:
                price = lf_df.iloc[-1]["close"]
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

        if text == "1":  # One-time multi-timeframe signal
            hf_df = calculate_indicators(get_data("1h", 200))
            mf_df = calculate_indicators(get_data("15m", 200))
            lf_df = calculate_indicators(get_data("1m", 200))

            signal, confidence, reasons = generate_signal(hf_df, mf_df, lf_df)
            price = lf_df.iloc[-1]["close"]
            msg = f"""
📊 SIGNAL: {signal if signal else 'No Signal'}
💰 Price: {price}
🔥 Confidence: {confidence}%

📌 Reasons: {', '.join(reasons)}
            """
            send_telegram(msg)
            return {"ok": True}

        if text.lower() == "start":  # Start 24/7
            if not bot_running:
                bot_running = True
                run_bot()

    return {"ok": True}

# ================= START =================
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))  # Railway dynamic port
    app.run(host="0.0.0.0", port=port)
