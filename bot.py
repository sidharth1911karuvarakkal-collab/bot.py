import ccxt
import pandas as pd
import ta
import time
import requests
from flask import Flask
import threading
from datetime import datetime
import pytz
import numpy as np
from sklearn.ensemble import RandomForestClassifier, GradientBoostingClassifier
import joblib
import os

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
symbol = "BTC/USDT"

# ==============================
# ⚙️ CONTROL
# ==============================
last_signal_time = 0
last_signal_type = ""
cooldown = 300  # 5 min

# ==============================
# 🤖 AI MODELS
# ==============================
rf_model = RandomForestClassifier(n_estimators=100)
gb_model = GradientBoostingClassifier()

MODEL_FILE = "model.pkl"
model_trained = False
X_data = []
y_data = []

# ==============================
# 🧠 RL MEMORY
# ==============================
trade_memory = []

# ==============================
# 📦 MODEL SAVE/LOAD
# ==============================
def save_model():
    joblib.dump((rf_model, gb_model), MODEL_FILE)

def load_model():
    global model_trained, rf_model, gb_model
    if os.path.exists(MODEL_FILE):
        rf_model, gb_model = joblib.load(MODEL_FILE)
        model_trained = True

# ==============================
# 📈 SAFE FETCH
# ==============================
def safe_fetch(tf):
    for _ in range(3):
        try:
            return exchange.fetch_ohlcv(symbol, timeframe=tf, limit=100)
        except:
            time.sleep(2)
    return None

# ==============================
# 📊 INDICATORS
# ==============================
def get_data(tf):
    ohlcv = safe_fetch(tf)
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
# 🧠 FEATURES
# ==============================
def extract_features(df):
    last = df.iloc[-1]
    return [
        last['ma5'] - last['ma10'],
        last['ema5'] - last['ema10'],
        last['rsi'],
        last['macd'] - last['macd_signal'],
        last['stoch_k'] - last['stoch_d'],
        last['close'] - last['bb_lower'],
        last['bb_upper'] - last['close'],
        last['atr'],
        last['volume'],
        last['close'] - df['close'].mean()
    ]

# ==============================
# 📊 MARKET REGIME
# ==============================
def market_regime(df15):
    trend = df15.iloc[-1]
    strength = abs(trend['close'] - trend['ma30'])
    return "TREND" if strength > 80 else "SIDEWAYS"

# ==============================
# 🤖 ENSEMBLE PREDICTION
# ==============================
def ensemble_predict(features):
    rf_prob = rf_model.predict_proba([features])[0]
    gb_prob = gb_model.predict_proba([features])[0]
    return (max(rf_prob) + max(gb_prob)) / 2 * 100

# ==============================
# 🧠 STRATEGY SCORING
# ==============================
def check_signals(df1m, df15m):
    last = df1m.iloc[-1]
    prev = df1m.iloc[-2]
    trend = df15m.iloc[-1]

    buy_score = 0
    sell_score = 0
    reasons = []

    if prev['ma5'] < prev['ma10'] and last['ma5'] > last['ma10']:
        buy_score += 1; reasons.append("MA Bullish")
    elif prev['ma5'] > prev['ma10'] and last['ma5'] < last['ma10']:
        sell_score += 1; reasons.append("MA Bearish")

    if last['ema5'] > last['ema10']:
        buy_score += 1; reasons.append("EMA Bullish")
    else:
        sell_score += 1; reasons.append("EMA Bearish")

    if last['rsi'] > 55:
        buy_score += 1; reasons.append("RSI Strong")
    elif last['rsi'] < 45:
        sell_score += 1; reasons.append("RSI Weak")

    if last['macd'] > last['macd_signal']:
        buy_score += 1; reasons.append("MACD Bullish")
    else:
        sell_score += 1; reasons.append("MACD Bearish")

    if last['stoch_k'] > last['stoch_d']:
        buy_score += 1; reasons.append("Stoch Bullish")
    else:
        sell_score += 1; reasons.append("Stoch Bearish")

    if last['close'] < last['bb_lower']:
        buy_score += 1; reasons.append("BB Oversold")
    elif last['close'] > last['bb_upper']:
        sell_score += 1; reasons.append("BB Overbought")

    trend_up = trend['close'] > trend['ma30']
    trend_down = trend['close'] < trend['ma30']

    return buy_score, sell_score, reasons, trend_up, trend_down

# ==============================
# 🧠 RL ADAPTIVE MODE
# ==============================
def adjust_strategy():
    wins = [t for t in trade_memory if t.get("reward", 0) > 0]
    losses = [t for t in trade_memory if t.get("reward", 0) < 0]

    return "CONSERVATIVE" if len(losses) > len(wins) else "AGGRESSIVE"

# ==============================
# ❤️ HEARTBEAT (1 HOUR)
# ==============================
def heartbeat():
    while True:
        try:
            now = datetime.now(pytz.timezone('Asia/Kolkata')).strftime("%I:%M %p")
            send_telegram(f"💓 BTC Bot Alive - {now}")
        except:
            pass
        time.sleep(3600)  # 1 hour

# ==============================
# 🤖 BOT LOOP
# ==============================
def run_bot():
    global last_signal_time, last_signal_type, model_trained

    load_model()
    send_telegram("🚀 INSTITUTIONAL BTC BOT LIVE")

    while True:
        try:
            df1 = get_data('1m')
            df15 = get_data('15m')

            if df1 is None or df15 is None:
                continue

            features = extract_features(df1)

            if len(df1) > 5:
                label = 1 if df1.iloc[-1]['close'] > df1.iloc[-5]['close'] else 0
                X_data.append(features)
                y_data.append(label)

            if len(X_data) > 150 and not model_trained:
                rf_model.fit(X_data, y_data)
                gb_model.fit(X_data, y_data)
                save_model()
                model_trained = True
                send_telegram("🤖 AI TRAINED")

            ai_prob = ensemble_predict(features) if model_trained else 0

            buy_score, sell_score, reasons, trend_up, trend_down = check_signals(df1, df15)

            regime = market_regime(df15)
            mode = adjust_strategy()

            required_score = 5 if mode == "CONSERVATIVE" else 4
            required_ai = 75 if mode == "CONSERVATIVE" else 65

            if regime == "SIDEWAYS":
                continue

            if model_trained and ai_prob < required_ai:
                continue

            now = time.time()
            if now - last_signal_time < cooldown:
                continue

            price = df1.iloc[-1]['close']
            atr = df1.iloc[-1]['atr']

            sl = price - (1.5 * atr)
            tp = price + (2.5 * atr)

            ist = datetime.now(pytz.timezone('Asia/Kolkata')).strftime("%H:%M:%S")

            if buy_score >= required_score and trend_up:
                send_telegram(f"""🟢 BUY BTC/USDT

Price: {price}
TP: {tp}
SL: {sl}

AI: {ai_prob:.2f}%
Mode: {mode}
Market: {regime}

Buy Score: {buy_score}
Sell Score: {sell_score}

Reason:
{', '.join(reasons)}

Time: {ist}
""")
                last_signal_time = now
                last_signal_type = "BUY"

            elif sell_score >= required_score and trend_down:
                send_telegram(f"""🔴 SELL BTC/USDT

Price: {price}
TP: {tp}
SL: {sl}

AI: {ai_prob:.2f}%
Mode: {mode}
Market: {regime}

Buy Score: {buy_score}
Sell Score: {sell_score}

Reason:
{', '.join(reasons)}

Time: {ist}
""")
                last_signal_time = now
                last_signal_type = "SELL"

            time.sleep(10)

        except Exception as e:
            print("Error:", e)
            time.sleep(5)

# ==============================
# 🌐 FLASK
# ==============================
app = Flask(__name__)

@app.route('/')
def home():
    return "🚀 Institutional Bot Running"

# ==============================
# ▶ START
# ==============================
if __name__ == "__main__":
    threading.Thread(target=run_bot).start()
    threading.Thread(target=heartbeat).start()  # ✅ added
    app.run(host="0.0.0.0", port=10000)
