import requests
import pandas as pd
import numpy as np
import time
import os
from threading import Thread
from flask import Flask

# ================= FLASK (FOR RENDER) =================
app = Flask(__name__)

@app.route("/")
def home():
    return "Bot is running ✅"

# ================= CONFIG =================
TOKEN = os.environ.get("8714289158:AAHQinJdvslG9f8qwfdX748WIXDgiXuBd9c")
CHAT_ID = os.environ.get("6094849602")
SYMBOL = "BTCUSDT"

BINANCE_URL = "https://api.binance.com/api/v3/klines"

last_update_id = None
trades = []

# ================= TELEGRAM =================
def send(msg):
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    requests.post(url, data={"chat_id": CHAT_ID, "text": msg})

def get_updates():
    global last_update_id
    url = f"https://api.telegram.org/bot{TOKEN}/getUpdates"
    params = {"timeout": 100}

    if last_update_id:
        params["offset"] = last_update_id + 1

    res = requests.get(url, params=params).json()
    return res.get("result", [])

# ================= DATA =================
def get_data(interval):
    data = requests.get(BINANCE_URL, params={
        "symbol": SYMBOL,
        "interval": interval,
        "limit": 200
    }).json()

    df = pd.DataFrame(data, columns=range(12))
    df = df[[0,1,2,3,4]]
    df.columns = ["time","open","high","low","close"]

    df["close"] = df["close"].astype(float)
    df["high"] = df["high"].astype(float)
    df["low"] = df["low"].astype(float)

    return df

# ================= INDICATORS =================
def indicators(df):
    df["ema20"] = df["close"].ewm(span=20).mean()
    df["ema50"] = df["close"].ewm(span=50).mean()

    ema12 = df["close"].ewm(span=12).mean()
    ema26 = df["close"].ewm(span=26).mean()
    df["macd"] = ema12 - ema26
    df["signal"] = df["macd"].ewm(span=9).mean()

    delta = df["close"].diff()
    gain = delta.clip(lower=0).rolling(14).mean()
    loss = (-delta.clip(upper=0)).rolling(14).mean()
    rs = gain / loss
    df["rsi"] = 100 - (100 / (1 + rs))

    df["bb_mid"] = df["close"].rolling(20).mean()
    df["bb_std"] = df["close"].rolling(20).std()
    df["bb_upper"] = df["bb_mid"] + 2 * df["bb_std"]
    df["bb_lower"] = df["bb_mid"] - 2 * df["bb_std"]

    return df

# ================= AI SIGNAL =================
def ai_signal():
    hf = indicators(get_data("1h"))
    mf = indicators(get_data("15m"))
    lf = indicators(get_data("1m"))

    score = 0
    reasons = []

    h = hf.iloc[-1]
    m = mf.iloc[-1]
    l = lf.iloc[-1]

    if h["ema20"] > h["ema50"]:
        score += 12; reasons.append("1h Bull")
    else:
        score -= 12; reasons.append("1h Bear")

    if m["ema20"] > m["ema50"]:
        score += 8; reasons.append("15m Bull")
    else:
        score -= 8; reasons.append("15m Bear")

    if m["rsi"] < 30:
        score += 7; reasons.append("15m Oversold")
    elif m["rsi"] > 70:
        score -= 7; reasons.append("15m Overbought")

    if l["rsi"] < 30:
        score += 6; reasons.append("1m Oversold")
    elif l["rsi"] > 70:
        score -= 6; reasons.append("1m Overbought")

    if l["close"] < l["bb_lower"]:
        score += 10; reasons.append("BB Buy")
    elif l["close"] > l["bb_upper"]:
        score -= 10; reasons.append("BB Sell")

    if l["macd"] > l["signal"]:
        score += 6; reasons.append("MACD Bull")
    else:
        score -= 6; reasons.append("MACD Bear")

    confidence = int((score + 50) * 100 / 100)
    confidence = max(0, min(100, confidence))

    if confidence >= 75:
        return "BUY", confidence, reasons
    elif confidence <= 25:
        return "SELL", confidence, reasons
    else:
        return None, confidence, reasons

# ================= LEVELS =================
def trade_levels(df, signal):
    price = df.iloc[-1]["close"]

    tr = np.maximum(df["high"] - df["low"],
                    np.maximum(abs(df["high"] - df["close"].shift()),
                               abs(df["low"] - df["close"].shift())))
    atr = tr.rolling(14).mean().iloc[-1]

    if signal == "BUY":
        return round(price,2), round(price - 1.5*atr,2), round(price + 2*atr,2)
    elif signal == "SELL":
        return round(price,2), round(price + 1.5*atr,2), round(price - 2*atr,2)

    return None, None, None

# ================= TRACKING =================
def check_trades():
    global trades
    df = get_data("1m")
    price = df.iloc[-1]["close"]

    for t in trades:
        if t["status"] == "open":

            if t["signal"] == "BUY":
                if price >= t["target"]:
                    t["status"] = "win"
                elif price <= t["sl"]:
                    t["status"] = "loss"

            elif t["signal"] == "SELL":
                if price <= t["target"]:
                    t["status"] = "win"
                elif price >= t["sl"]:
                    t["status"] = "loss"

def accuracy():
    wins = sum(1 for t in trades if t["status"] == "win")
    losses = sum(1 for t in trades if t["status"] == "loss")
    total = wins + losses
    return round((wins/total)*100,2) if total else 0

# ================= AUTO BOT =================
def auto_bot():
    last_signal = None

    while True:
        try:
            sig, conf, reasons = ai_signal()
            check_trades()

            if sig and sig != last_signal:
                df = get_data("1m")
                entry, sl, target = trade_levels(df, sig)

                trades.append({
                    "signal": sig,
                    "entry": entry,
                    "sl": sl,
                    "target": target,
                    "status": "open"
                })

                send(f"""🚨 AUTO SIGNAL
📊 {sig}
🔥 {conf}%

🎯 Entry: {entry}
🛑 SL: {sl}
💰 Target: {target}

📌 {', '.join(reasons)}
📊 Accuracy: {accuracy()}%
""")

                last_signal = sig

            time.sleep(60)

        except Exception as e:
            print("Auto Error:", e)
            time.sleep(60)

# ================= COMMAND BOT =================
def command_bot():
    global last_update_id

    while True:
        try:
            updates = get_updates()

            for u in updates:
                last_update_id = u["update_id"]

                if "message" in u:
                    text = u["message"].get("text", "")

                    if text == "1":
                        sig, conf, reasons = ai_signal()
                        df = get_data("1m")
                        entry, sl, target = trade_levels(df, sig)

                        send(f"""📊 {sig if sig else 'No Signal'}
🔥 {conf}%

🎯 Entry: {entry}
🛑 SL: {sl}
💰 Target: {target}

📌 {', '.join(reasons)}
📊 Accuracy: {accuracy()}%
""")

            time.sleep(2)

        except Exception as e:
            print("Cmd Error:", e)
            time.sleep(5)

# ================= START =================
if __name__ == "__main__":
    Thread(target=auto_bot).start()
    Thread(target=command_bot).start()

    # 🔥 THIS IS IMPORTANT (PORT BINDING)
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
