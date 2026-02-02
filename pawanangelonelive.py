import streamlit as st
import pandas as pd
import numpy as np
import datetime, time, os, threading
import plotly.graph_objects as go
import math
import random
import pyttsx3
import pyotp
from SmartApi import SmartConnect
from SmartApi.smartWebSocketV2 import SmartWebSocketV2

# =========================================================
# 1. API CONFIG & DIRECTORY SETUP
# =========================================================
API_KEY      = "RKhSk9KM"
CLIENT_ID    = "p362706"
PASSWORD     = "5555"
TOTP_SECRET  = "SWO6GQESTOBCAWU5B5XAZ2U634"
EXP_JAN      = "29JAN26"
TIMEFRAME    = "5-Min"

APP_NAME = "PAWAN MASTER ALGO SYSTEM"
BASE_DIR = "pawan_master_data"
SCREENSHOT_DIR = os.path.join(BASE_DIR, "screenshots")
LOG_DIR = os.path.join(BASE_DIR, "logs")

os.makedirs(SCREENSHOT_DIR, exist_ok=True)
os.makedirs(LOG_DIR, exist_ok=True)

# =========================================================
# 2. UI STYLE (AngelOne Inspired)
# =========================================================
st.set_page_config(page_title=APP_NAME, layout="wide", initial_sidebar_state="expanded")

st.markdown("""
<style>
body { background-color:#0b1020; color:white; }
.sidebar .sidebar-content { background-color:#0f1630; }
.stButton>button { width:100%; height:45px; font-size:16px; border-radius:8px; }
</style>
""", unsafe_allow_html=True)

# =========================================================
# 3. SESSION STATE (Live Cache & User Settings)
# =========================================================
if "LIVE_LTP" not in st.session_state: st.session_state.LIVE_LTP = {}
if "MASTER_DF" not in st.session_state: st.session_state.MASTER_DF = None
if "ws_status" not in st.session_state: st.session_state.ws_status = "Disconnected"
if "mode" not in st.session_state: st.session_state.mode = "FUTURES"
if "panic" not in st.session_state: st.session_state.panic = False

# Risk & Trading State
for key, val in {
    "capital": 200000, "amt_per_trade": 10000, "max_trades_symbol": 2,
    "sound_on": True, "auto_exit": True, "orders": [], "positions": [],
    "verified_signals": [], "hot_signals": [],
    "pnl_stats": {"net_profit": 0, "total_profit": 0, "total_loss": 0, "roi": 0}
}.items():
    if key not in st.session_state: st.session_state[key] = val

if "alerts" not in st.session_state:
    st.session_state.alerts = {
        "heartbeat": True, "ws_reconnect": True, "hot_signal": True,
        "verified_signal": True, "order_placed": True, "slippage": True,
        "heatmap": True, "visual_validator": True
    }

# =========================================================
# 4. WEBSOCKET & DATA HANDLERS
# =========================================================
def on_data(wsapp, msg):
    if 'token' in msg and 'last_traded_price' in msg:
        st.session_state.LIVE_LTP[msg['token']] = msg['last_traded_price'] / 100

def on_open(wsapp):
    st.session_state.ws_status = "Connected"
    if os.path.exists("lean_scrip_master.csv"):
        st.session_state.MASTER_DF = pd.read_csv("lean_scrip_master.csv")
        tokens = st.session_state.MASTER_DF['token'].astype(str).head(190).tolist()
        sws.subscribe("titan_v5", 1, [{"exchangeType": 1, "tokens": tokens}])

def get_atm_strike(spot_price, name):
    interval = 100 if "BANK" in name else 50
    return round(spot_price / interval) * interval

# =========================================================
# 5. LIVE API INITIALIZATION
# =========================================================
if "obj" not in st.session_state:
    try:
        st.session_state.obj = SmartConnect(api_key=API_KEY)
        st.session_state.sess = st.session_state.obj.generateSession(CLIENT_ID, PASSWORD, pyotp.TOTP(TOTP_SECRET).now())
        obj = st.session_state.obj
        sws = SmartWebSocketV2(st.session_state.sess['data']['jwtToken'], API_KEY, CLIENT_ID, obj.getfeedToken())
        sws.on_open = on_open
        sws.on_data = on_data
        threading.Thread(target=sws.connect, daemon=True).start()
    except Exception as e:
        st.error(f"API Login Failed: {e}")

# =========================================================
# 6. SIGNAL LOGIC (Titan V5)
# =========================================================
def calculate_live_signal(df, ltp):
    if df is None or len(df) < 33: return None
    df['mid_bb'] = df['close'].rolling(20).mean()
    atr = (df['high'] - df['low']).rolling(10).mean()
    df['st_line'] = ((df['high'] + df['low']) / 2) - (3 * atr)
    
    delta = df['close'].diff()
    gain = delta.where(delta > 0, 0)
    loss = -delta.where(delta < 0, 0)
    avg_gain = gain.rolling(14).mean()
    avg_loss = loss.rolling(14).mean()
    df['rsi'] = 100 - (100 / (1 + (avg_gain / avg_loss)))
    
    curr = df.iloc[-1]
    if ltp > curr['st_line'] and curr['st_line'] > curr['mid_bb'] and curr['rsi'] >= 70: return "CE"
    if ltp < curr['st_line'] and curr['st_line'] < curr['mid_bb'] and curr['rsi'] <= 30: return "PE"
    return None

# =========================================================
# 7. LIVE ORDER PLACEMENT
# =========================================================
def place_live_order(symbol, token, side, ltp):
    try:
        order_params = {
            "variety": "NORMAL", "tradingsymbol": symbol, "symboltoken": token,
            "transactiontype": "BUY" if side == "CE" else "SELL",
            "exchange": "NSE", "ordertype": "MARKET", "producttype": "INTRADAY",
            "duration": "DAY", "quantity": "1"
        }
        order_id = st.session_state.obj.placeOrder(order_params)
        st.session_state.orders.append({
            "time": datetime.datetime.now().strftime("%H:%M:%S"),
            "symbol": symbol, "side": side, "status": "SUCCESS", "order_id": order_id, "price": ltp
        })
        return order_id
    except Exception as e:
        st.error(f"Order Failed: {e}")
        return None

# =========================================================
# 8. UI NAVIGATION & PAGES
# =========================================================
st.sidebar.title("📊 MENU")
page = st.sidebar.radio("", ["Dashboard", "Signal Validator", "Visual Validator", "Positions", "Order Book", "Profit & Loss", "Settings", "🚨 PANIC BUTTON"])

if page == "Dashboard":
    st.subheader("📌 Live Market Scanner (190 Tokens)")
    c1, c2, c3 = st.columns(3)
    c1.success(f"WebSocket: {st.session_state.ws_status}")
    c2.info(f"Mode: {st.session_state.mode}")
    
    if st.session_state.MASTER_DF is not None:
        display_data = []
        for _, row in st.session_state.MASTER_DF.head(20).iterrows():
            token = str(row['token'])
            ltp = st.session_state.LIVE_LTP.get(token)
            if ltp:
                display_data.append({"Symbol": row['name'], "LTP": ltp, "ATM": get_atm_strike(ltp, row['name'])})
        st.table(pd.DataFrame(display_data))

elif page == "Order Book":
    st.subheader("📘 Live Order Book")
    st.table(pd.DataFrame(st.session_state.orders))

elif page == "Settings":
    st.subheader("⚙️ System Settings")
    st.session_state.capital = st.number_input("Total Capital", value=st.session_state.capital)
    st.session_state.amt_per_trade = st.number_input("Amount Per Trade", value=st.session_state.amt_per_trade)

if page == "🚨 PANIC BUTTON":
    if st.button("🚨 EXIT ALL & STOP SYSTEM"):
        st.session_state.panic = True
        st.error("SYSTEM HALTED")
        st.stop()

# =========================================================
# 9. VISUAL VALIDATOR (Chart with Live Overlays)
# =========================================================
def visual_validator_chart(symbol, data, df_candles):
    fig = go.Figure()
    fig.add_trace(go.Candlestick(
        x=df_candles.index,
        open=df_candles['open'],
        high=df_candles['high'],
        low=df_candles['low'],
        close=df_candles['close'],
        name="Market"
    ))

    fig.add_trace(go.Scatter(x=df_candles.index, y=df_candles['bb_upper'], name="BB Upper", line=dict(color='gray', dash='dash')))
    fig.add_trace(go.Scatter(x=df_candles.index, y=df_candles['mid_bb'], name="BB Middle", line=dict(color='pink')))
    fig.add_trace(go.Scatter(x=df_candles.index, y=df_candles['bb_lower'], name="BB Lower", line=dict(color='gray', dash='dash')))
    
    fig.add_trace(go.Scatter(
        x=[df_candles.index[-1]], y=[data["spot"]],
        mode="markers", marker=dict(size=14, symbol="diamond", color="green"),
        name="💎 Signal"
    ))

    fig.update_layout(template="plotly_dark", xaxis_rangeslider_visible=False)
    st.plotly_chart(fig, use_container_width=True)

    img_path = os.path.join(SCREENSHOT_DIR, f"{symbol}_{datetime.datetime.now().strftime('%H%M%S')}.png")
    fig.write_image(img_path)
    return img_path

# =========================================================
# 10. LIVE ORDER EXECUTION & POSITION TRACKING
# =========================================================
def place_order(symbol, token, side, qty, price):
    order_id = place_live_order(symbol, token, side, price)
    
    if order_id:
        st.session_state.positions.append({
            "symbol": symbol,
            "token": token,
            "qty": qty,
            "avg": price,
            "ltp": price,
            "pnl": 0,
            "sl": price - 100, 
            "tp": price + 150, 
            "side": side,
            "entry_time": datetime.datetime.now().strftime("%H:%M:%S")
        })
        
        if st.session_state.alerts["order_placed"]:
            st.toast(f"✅ Order Placed: {symbol} at {price}")
    return order_id

# =========================================================
# 11. PNL & RISK MANAGEMENT
# =========================================================
def calculate_pnl():
    total_pnl = 0
    for pos in st.session_state.positions:
        current_ltp = st.session_state.LIVE_LTP.get(pos['token'], pos['avg'])
        pos['ltp'] = current_ltp
        
        if pos['side'] == "CE" or pos['side'] == "BUY":
            pos['pnl'] = (current_ltp - pos['avg']) * pos['qty']
        else:
            pos['pnl'] = (pos['avg'] - current_ltp) * pos['qty']
        
        total_pnl += pos['pnl']

    st.session_state.pnl_stats["net_profit"] = total_pnl
    if st.session_state.capital > 0:
        st.session_state.pnl_stats["roi"] = (total_pnl / st.session_state.capital) * 100
    
    return total_pnl

# =========================================================
# 12. DYNAMIC PAGES INTEGRATION
# =========================================================
if page == "Signal Validator":
    st.subheader("🧠 Titan V5 Signal Validator")
    symbol_to_check = st.selectbox("Select Active Token", list(st.session_state.LIVE_LTP.keys()))
    st.info(f"Monitoring Shield Gates for {symbol_to_check}...")

elif page == "Visual Validator":
    st.subheader("👁 Visual Confirmation")
    if not st.session_state.verified_signals:
        st.warning("Waiting for Verified Signals...")
    else:
        for sig in st.session_state.verified_signals:
            st.write(f"Validating Signal for {sig}")
            if st.button(f"Confirm & Execute {sig}"):
                token = "Lookup_Token" 
                place_order(sig, token, "CE", 50, st.session_state.LIVE_LTP[token])

elif page == "Profit & Loss":
    st.subheader("📈 Real-Time Performance")
    net_pnl = calculate_pnl()
    c1, c2, c3 = st.columns(3)
    c1.metric("Net P&L", f"₹{net_pnl:,.2f}", delta=f"{st.session_state.pnl_stats['roi']:.2f}%")
    if st.session_state.positions:
        st.table(pd.DataFrame(st.session_state.positions))

st.markdown("<hr><center>© Pawan Master Algo System | Live Mode Active</center>", unsafe_allow_html=True)
