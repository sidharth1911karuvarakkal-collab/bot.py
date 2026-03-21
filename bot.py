import ccxt
import pandas as pd
import ta
import time
import requests
from flask import Flask
import threading
from datetime import datetime
import pytz
from textblob import TextBlob
import os

# ==============================
# 💬 TELEGRAM SETTINGS
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
# 📊 EXCHANGE DATA
# ==============================
exchange = ccxt.okx()
symbol = 'BTC/USDT'

# ==============================
# 📈 FETCH DATA & INDICATORS
# ==============================
def get_data(timeframe):
    ohlcv = exchange.fetch_ohlcv(symbol, timeframe=timeframe, limit=100)
    df = pd.DataFrame(ohlcv, columns=['time','open','high','low','close','volume'])

    # Main indicators
    df['ma5'] = df['close'].rolling(5).mean()
    df['ma10'] = df['close'].rolling(10).mean()
    df['ma30'] = df['close'].rolling(30).mean()
    df['rsi'] = ta.momentum.RSIIndicator(df['close'], window=14).rsi()

    # Sub indicators
    macd = ta.trend.MACD(df['close'], window_slow=26, window_fast=12, window_sign=9)
    df['macd'] = macd.macd()
    df['macd_signal'] = macd.macd_signal()

    bb = ta.volatility.BollingerBands(df['close'], window=20, window_dev=2)
    df['bb_high'] = bb.bollinger_hband()
    df['bb_low'] = bb.bollinger_lband()

    df['ema20'] = df['close'].ewm(span=20, adjust=False).mean()
    df['atr'] = ta.volatility.AverageTrueRange(df['high'], df['low'], df['close'], window=14).average_true_range()

    return df

# ==============================
# 📰 FREE NEWS SENTIMENT
# ==============================
def get_free_news_sentiment():
    try:
        url = "https://cryptocurrency.cv/api/news"
        res = requests.get(url).json()
        headlines = [post['title'] for post in res['data'] if "BTC" in post['title'] or "Bitcoin" in post['title']]
        if not headlines:
            return "Neutral"
        score = 0
        for title in headlines:
            analysis = TextBlob(title)
            score += analysis.sentiment.polarity
        avg_score = score / len(headlines)
        if avg_score > 0.05:
            return "Positive"
        elif avg_score < -0.05:
            return "Negative"
        else:
            return "Neutral"
    except:
        return "Neutral"

# ==============================
# REDDIT SENTIMENT via Pushshift.io
# ==============================
def get_reddit_sentiment():
    try:
        url = "https://api.pushshift.io/reddit/search/submission/?subreddit=Bitcoin&size=50"
        res = requests.get(url).json()
        posts = res.get('data', [])
        if not posts:
            return "Neutral"
        score = 0
        for post in posts:
            title = post.get('title','')
            score += TextBlob(title).sentiment.polarity
        avg_score = score / max(len(posts),1)
        if avg_score > 0.05:
            return "Bullish"
        elif avg_score < -0.05:
            return "Bearish"
        else:
            return "Neutral"
    except:
        return "Neutral"

# ==============================
# SIDEWAYS MARKET DETECTION
# ==============================
def is_sideways(df):
    last = df.iloc[-1]
    close = last['close']
    atr = last['atr'] if not pd.isna(last['atr']) else close*0.01
    bb_width = last['bb_high'] - last['bb_low']
    atr_percent = (atr / close) * 100
    bb_percent = (bb_width / close) * 100
    return atr_percent < 0.15 and bb_percent < 0.5

# ==============================
# SIGNAL LOGIC
# ==============================
def check_signals(df1m, df15m):
    last1 = df1m.iloc[-1]
    prev1 = df1m.iloc[-2]
    last15 = df15m.iloc[-1]

    confirmed, conflicting = [], []

    # MAIN
    buy_main = prev1['ma5'] < prev1['ma10'] and last1['ma5'] > last1['ma10'] and last1['rsi'] < 60
    sell_main = prev1['ma5'] > prev1['ma10'] and last1['ma5'] < last1['ma10'] and last1['rsi'] > 40
    if buy_main or sell_main:
        confirmed += ["MA","RSI"]

    # TREND (15m)
    trend_up = last15['close'] > last15['ma30']
    trend_down = last15['close'] < last15['ma30']

    # SUB
    sub_confirmed = 0
    if last1['macd'] > last1['macd_signal']: sub_confirmed += 1; confirmed.append("MACD")
    else: conflicting.append("MACD")
    if last1['close'] > last1['ema20']: sub_confirmed += 1; confirmed.append("EMA")
    else: conflicting.append("EMA")
    if last1['close'] < last1['bb_low'] or last1['close'] > last1['bb_high']: sub_confirmed += 1; confirmed.append("Bollinger")
    else: conflicting.append("Bollinger")

    # FINAL SIGNAL
    buy_signal = buy_main and (sub_confirmed >= 1 or trend_up)
    sell_signal = sell_main and (sub_confirmed >= 1 or trend_down)

    price = last1['close']
    atr = last1['atr'] if not pd.isna(last1['atr']) else price*0.01
    sl = price - atr if buy_signal else price + atr
    tp = price + 2*atr if buy_signal else price - 2*atr

    # Sentiment
    news = get_free_news_sentiment()
    reddit_s = get_reddit_sentiment()

    # Confidence
    confidence = 50
    if last1['rsi'] > 60 or last1['rsi'] < 40: confidence += 15
    if abs(last1['ma5']-last1['ma10']) > 5: confidence += 15
    if trend_up or trend_down: confidence += 20
    if news == "Positive" and buy_signal: confidence += 15
    if news == "Negative" and sell_signal: confidence += 15
    if reddit_s == "Bullish" and buy_signal: confidence += 10
    if reddit_s == "Bearish" and sell_signal: confidence += 10

    # Sideways adjustment
    sideways = is_sideways(df1m)
    if sideways:
        confidence -= 20

    accuracy = min(confidence, 90)
    return buy_signal, sell_signal, price, sl, tp, confidence, accuracy, confirmed, conflicting, news, reddit_s, sideways

# ==============================
# BOT LOOP
# ==============================
def run_bot():
    last_signal = ""
    last_heartbeat = 0
    heartbeat_interval = 3600
    print("Bot Started")
    send_telegram("✅ BTC Signal Bot LIVE (Free News + Indicators + Sideways Filter)")

    while True:
        try:
            df1m = get_data('1m')
            df15m = get_data('15m')
            buy, sell, price, sl, tp, confidence, accuracy, confirmed, conflicting, news, reddit_s, sideways = check_signals(df1m, df15m)

            ist = pytz.timezone('Asia/Kolkata')
            now = datetime.now(ist).strftime("%Y-%m-%d %I:%M:%S %p")
            current_time = time.time()

            volume_status = "Above Average" if df1m['volume'].iloc[-1] > df1m['volume'].rolling(20).mean().iloc[-1] else "Below Average"
            sideways_status = "Yes" if sideways else "No"

            if buy and last_signal != "BUY":
                msg = f"""
🟢 BUY SIGNAL

💰 Price: {price}
🎯 TP: {tp}
🛑 SL: {sl}

📊 Confidence: {confidence}%
📈 Accuracy: {accuracy}%

📌 Confirmed Indicators: {', '.join(confirmed)}
📌 Conflicting Indicators: {', '.join(conflicting)}
📌 News Sentiment: {news}
📌 Reddit Sentiment: {reddit_s}
📌 Volume: {volume_status}
📌 Sideways Market: {sideways_status}
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

📌 Confirmed Indicators: {', '.join(confirmed)}
📌 Conflicting Indicators: {', '.join(conflicting)}
📌 News Sentiment: {news}
📌 Reddit Sentiment: {reddit_s}
📌 Volume: {volume_status}
📌 Sideways Market: {sideways_status}
⏱ Time: {now}
📉 Entry TF: 1m
📊 Trend TF: 15m
"""
                send_telegram(msg)
                last_signal = "SELL"

            # Heartbeat
            if current_time - last_heartbeat > heartbeat_interval:
                send_telegram(f"💓 Heartbeat: Bot alive at {now}")
                last_heartbeat = current_time

            time.sleep(30)

        except Exception as e:
            print("Error:", e)
            send_telegram(f"❌ Bot error: {e}")
            time.sleep(10)

# ==============================
# FLASK
# ==============================
app = Flask(__name__)
@app.route('/')
def home():
    return "🚀 BTC Signal Bot Running!"

# ==============================
# START BOT
# ==============================
if __name__ == "__main__":
    threading.Thread(target=run_bot).start()
    app.run(host="0.0.0.0", port=10000)
