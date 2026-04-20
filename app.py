import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import os
import json
import time
from datetime import datetime
import logging
from streamlit_autorefresh import st_autorefresh

# QuatSystem Imports
from core.exchange import CoinSwitchExchange
from database import Database
from core.data_processor import DataProcessor
from core.ai_engine import AIEngine
from core.indicators import Indicators
from core.asset_filter import AssetFilter
from core.news_filter import NewsFilter
from core.session_filter import SessionFilter
from core.regime_detector import RegimeDetector

# Page Config
st.set_page_config(
    page_title="QUAT SYSTEM | FUTURES PAPER TERMINAL",
    layout="wide",
    initial_sidebar_state="expanded"
)

# ── Institutional CSS ───────────────────────────────────────
st.markdown("""
    <style>
    @import url('https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@300;400;700&family=Inter:wght@400;700;900&display=swap');
    
    :root {
        --bg-color: #050505;
        --card-bg: #0a0a0a;
        --accent-green: #00ffaa;
        --accent-blue: #0088ff;
        --accent-red: #ff3333;
        --accent-amber: #ffaa00;
        --accent-purple: #aa66ff;
        --text-muted: #666666;
        --text-main: #ffffff;
        --border-color: #1a1a1a;
    }

    .stApp { background-color: var(--bg-color); color: var(--text-main); }
    footer { visibility: hidden !important; }
    [data-testid="stSidebarNav"] { visibility: hidden !important; }
    
    button[data-testid="stSidebarCollapseButton"] {
        color: var(--accent-blue) !important;
        visibility: visible !important;
    }
    
    .main .block-container { padding-top: 2rem; padding-bottom: 0rem; }
    
    div.stMarkdown, p, span, label { 
        font-family: 'Inter', sans-serif !important; 
        font-size: 13px;
    }

    .stTabs [data-baseweb="tab-list"] { gap: 20px; border-bottom: 1px solid var(--border-color); margin-bottom: 20px; }
    .stTabs [data-baseweb="tab"] { color: var(--text-muted) !important; font-family: 'JetBrains Mono', monospace !important; font-size: 11px !important; text-transform: uppercase; }
    .stTabs [aria-selected="true"] { color: var(--text-main) !important; border-bottom: 2px solid var(--accent-blue) !important; }

    [data-testid="stMetricValue"] { font-family: 'JetBrains Mono', monospace !important; font-weight: 700 !important; font-size: 24px !important; }
    
    .pipeline-wrapper { display: flex; justify-content: space-between; padding: 5px 0; border-top: 1px solid var(--border-color); border-bottom: 1px solid var(--border-color); margin: 5px 0; }
    .step { font-size: 9px !important; color: var(--text-muted); text-transform: uppercase; letter-spacing: 1px; }
    .step-active { color: var(--accent-green); font-weight: 700; }
    
    .stCodeBlock { background-color: #000 !important; border: 1px solid var(--border-color) !important; border-radius: 0px !important; }
    .stCodeBlock code { font-size: 11px !important; }

    section[data-testid="stSidebar"] {
        background-color: #080808 !important;
        border-right: 1px solid var(--border-color);
        padding-top: 0px !important;
    }

    .sidebar-status { padding: 10px; background-color: #000; border: 1px solid var(--border-color); margin-bottom: 15px; font-family: 'JetBrains Mono', monospace; font-size: 10px; letter-spacing: 1px; }
    .status-dot { height: 6px; width: 6px; border-radius: 50%; display: inline-block; margin-right: 8px; }
    .dot-live { background-color: var(--accent-green); box-shadow: 0 0 5px var(--accent-green); }

    .ai-container { font-family: 'JetBrains Mono', monospace; font-size: 11px; color: #888; background-color: #000; border: 1px solid #111; padding: 10px; height: 350px; overflow-y: auto; margin-bottom: 10px; }
    .log-entry { margin-bottom: 8px; line-height: 1.4; }
    .log-ts { color: #444; margin-right: 6px; }
    .log-user { color: var(--accent-blue); }
    .log-ai { color: #ccc; }

    div[data-testid="stChatInput"] { padding-bottom: 20px !important; }
    
    .event-row { display: flex; justify-content: space-between; padding: 4px 0; border-bottom: 1px solid #111; font-family: 'JetBrains Mono', monospace; font-size: 10px; }
    .event-desc { color: var(--accent-amber); }
    .event-countdown { color: var(--text-muted); }
    
    .pos-table { width: 100%; font-family: 'JetBrains Mono', monospace; font-size: 10px; border-collapse: collapse; }
    .pos-table th { text-align: left; color: var(--text-muted); padding: 4px 8px; border-bottom: 1px solid var(--border-color); text-transform: uppercase; letter-spacing: 1px; }
    .pos-table td { padding: 4px 8px; border-bottom: 1px solid #0d0d0d; }
    
    .regime-badge { display: inline-block; padding: 2px 8px; font-family: 'JetBrains Mono', monospace; font-size: 9px; letter-spacing: 1px; border: 1px solid var(--border-color); margin: 2px; }
    .regime-trending { color: var(--accent-green); border-color: #003322; }
    .regime-ranging { color: var(--accent-blue); border-color: #002244; }
    .regime-volatile { color: var(--accent-amber); border-color: #332200; }
    .regime-unknown { color: var(--text-muted); }
    
    .session-badge { display: inline-block; padding: 3px 10px; font-family: 'JetBrains Mono', monospace; font-size: 10px; letter-spacing: 1px; }
    .session-active { color: var(--accent-green); border: 1px solid #003322; }
    .session-blocked { color: var(--accent-red); border: 1px solid #330000; }
    </style>
""", unsafe_allow_html=True)

# ── Initialization ──────────────────────────────────────────
if 'exchange' not in st.session_state:
    st.session_state.exchange = CoinSwitchExchange()
if 'db' not in st.session_state:
    st.session_state.db = Database()
if 'ai' not in st.session_state:
    st.session_state.ai = AIEngine()
if 'indicators' not in st.session_state:
    st.session_state.indicators = Indicators()
if 'asset_filter' not in st.session_state:
    st.session_state.asset_filter = AssetFilter()
if 'news_filter' not in st.session_state:
    st.session_state.news_filter = NewsFilter()
if 'session_filter' not in st.session_state:
    st.session_state.session_filter = SessionFilter()
if 'regime_detector' not in st.session_state:
    st.session_state.regime_detector = RegimeDetector()
if 'chat_history' not in st.session_state:
    st.session_state.chat_history = []
if 'processor' not in st.session_state:
    st.session_state.processor = DataProcessor()

def load_bot_status():
    if os.path.exists(".bot_status.json"):
        try:
            with open(".bot_status.json", "r") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}

def stream_logs(placeholder, full=False):
    log_file = "logs/bot.log"
    if os.path.exists(log_file):
        with open(log_file, "r") as f:
            lines = f.readlines()
            count = 200 if full else 10
            placeholder.code("".join(lines[-count:]), language="text")

def write_env(key: str, value: str):
    env_path = os.path.join(os.path.dirname(__file__), ".env")
    if not os.path.exists(env_path):
        return
    with open(env_path, "r") as f:
        lines = f.readlines()
    updated = False
    for i, line in enumerate(lines):
        if line.strip().startswith(f"{key}="):
            lines[i] = f"{key}={value}\n"
            updated = True
            break
    if not updated:
        lines.append(f"{key}={value}\n")
    with open(env_path, "w") as f:
        f.writelines(lines)

def fetch_live_equity():
    """Returns virtual capital for training mode."""
    stats = st.session_state.db.get_win_rate()
    # Always prioritize virtual capital in Paper mode
    return stats.get("capital", 10000.0)

# ── SIDEBAR ─────────────────────────────────────────────────
with st.sidebar:
    # Session info
    session_info = st.session_state.session_filter.get_session_info()
    session_class = "session-active" if session_info["can_trade"] else "session-blocked"
    session_label = session_info["current_session"]
    
    st.markdown(f"""
        <div class="sidebar-status">
            <span class="status-dot dot-live"></span>
            FUTURES PAPER
            <span style="float:right;" class="session-badge {session_class}">{session_label}</span>
        </div>
    """, unsafe_allow_html=True)

    all_pairs = st.session_state.asset_filter.get_allowed_pairs()
    symbol = st.selectbox("SYMBOL", all_pairs, index=all_pairs.index("BTC/INR") if "BTC/INR" in all_pairs else 0)
    
    st.divider()
    
    # Quat AI Command Log
    st.markdown("<div style='font-size:10px; color:#444; margin-bottom:10px;'>QUAT_AI</div>", unsafe_allow_html=True)
    
    chat_container = st.container(height=380, border=True)
    with chat_container:
        if not st.session_state.chat_history:
            st.chat_message("assistant", avatar="🤖").write("Ready. Ask me anything about markets, strategy, or the bot.")
        for msg in st.session_state.chat_history:
            avatar = "🤖" if msg["role"] == "assistant" else "👤"
            st.chat_message(msg["role"], avatar=avatar).write(msg["content"])
            
    if st.button("CLEAR HISTORY", use_container_width=True):
        st.session_state.chat_history = []
        st.rerun()

    # Native Chat Input
    if prompt := st.chat_input("Ask QuatAI..."):
        ts = datetime.now().strftime("%H:%M")
        st.session_state.chat_history.append({"role": "user", "content": prompt, "ts": ts})
        
        # Render the newly entered user prompt immediately
        with chat_container:
            st.chat_message("user", avatar="👤").write(prompt)
            
            # Show spinner while thinking
            with st.chat_message("assistant", avatar="🤖"):
                with st.spinner("Thinking..."):
                    status = load_bot_status()
                    context = f"Step: {status.get('step')}. Symbol: {symbol}. Session: {session_label}."
                    
                    try:
                        response = st.session_state.ai.chat(prompt, context=context)
                    except Exception as e:
                        response = f"Error: {e}"
                
                st.write(response)
        
        st.session_state.chat_history.append({"role": "assistant", "content": response, "ts": datetime.now().strftime("%H:%M")})

# ── HEADER STATISTICS ───────────────────────────────────────
status = load_bot_status()
stats = st.session_state.db.get_win_rate()

# Live equity from API
live_equity = fetch_live_equity()
if live_equity <= 0:
    live_equity = stats.get("capital", 0.0)

col1, col2, col3, col4 = st.columns(4)
col1.metric("TOTAL EQUITY", f"INR {live_equity:,.2f}")
col2.metric("DAILY PNL", f"{stats.get('total_pnl', 0):,.2f}")
wins, losses = stats.get('wins', 0), stats.get('losses', 0)
wr = (wins / (wins + losses) * 100) if (wins + losses) > 0 else 0
col3.metric("WIN RATE", f"{wr:.1f}%")
col4.metric("PHASE", status.get('step', 'IDLE'))

# ── MAIN TABS ───────────────────────────────────────────────
t_terminal, t_console, t_status, t_settings = st.tabs(["TERMINAL", "CONSOLE", "STATUS", "SETTINGS"])

with t_terminal:
    # Pipeline tracker
    steps = ["NEWS", "SESSION", "RISK", "DATA", "REGIME", "SIGNAL", "AI", "EXEC", "MONITOR"]
    current_step = status.get("step", "IDLE")
    p_html = '<div class="pipeline-wrapper">'
    for i, s in enumerate(steps):
        active_class = "step-active" if s == current_step else ""
        p_html += f'<span class="step {active_class}">{s}</span>'
        if i < len(steps)-1: p_html += '<span class="step-divider"> | </span>'
    p_html += '</div>'
    st.markdown(p_html, unsafe_allow_html=True)

    c_left, c_right = st.columns([3, 1])
    
    with c_left:
        st.markdown("<div style='font-size:10px; color:#444;'>PRICE_ACTION</div>", unsafe_allow_html=True)
        try:
            raw_candles = st.session_state.exchange.get_candles(symbol, interval="15m", limit=100)
            df = st.session_state.processor.format_native_candles(raw_candles)
            
            if not df.empty and len(df) >= 30:
                ind = st.session_state.indicators.get_all_indicators(df)
                series = ind.get("_series", {})
                
                # Regime detection
                regime_info = st.session_state.regime_detector.get_regime_info(df, ind)
                regime = regime_info["regime"]
                regime_class = "regime-trending" if "TREND" in regime else \
                               "regime-volatile" if "VOLAT" in regime else \
                               "regime-ranging" if "RANG" in regime else "regime-unknown"
                strategy = regime_info["recommended_strategy"]
                
                st.markdown(f"""
                    <div style="margin-bottom:5px;">
                        <span class="regime-badge {regime_class}">{regime}</span>
                        <span class="regime-badge" style="color:#888;">STRATEGY: {strategy}</span>
                        <span class="regime-badge" style="color:#555;">ADX: {regime_info['adx']}</span>
                    </div>
                """, unsafe_allow_html=True)
                
                fig = make_subplots(
                    rows=3, cols=1, shared_xaxes=True,
                    vertical_spacing=0.02,
                    row_heights=[0.6, 0.2, 0.2],
                )

                fig.add_trace(go.Candlestick(
                    x=df["timestamp"], open=df["open"], high=df["high"],
                    low=df["low"], close=df["close"],
                    increasing_line_color="#00ffaa", decreasing_line_color="#ff3333",
                    increasing_fillcolor="#00ffaa", decreasing_fillcolor="#ff3333",
                    name="Price",
                ), row=1, col=1)

                if "ema_20" in series:
                    fig.add_trace(go.Scatter(
                        x=df["timestamp"], y=series["ema_20"],
                        line=dict(color="#0088ff", width=1), name="EMA 20",
                    ), row=1, col=1)
                if "ema_50" in series:
                    fig.add_trace(go.Scatter(
                        x=df["timestamp"], y=series["ema_50"],
                        line=dict(color="#ffaa00", width=1), name="EMA 50",
                    ), row=1, col=1)
                if "ema_200" in series and not series["ema_200"].isna().all():
                    fig.add_trace(go.Scatter(
                        x=df["timestamp"], y=series["ema_200"],
                        line=dict(color="#ff3333", width=1, dash="dot"), name="EMA 200",
                    ), row=1, col=1)

                if "bb" in series:
                    bb = series["bb"]
                    fig.add_trace(go.Scatter(
                        x=df["timestamp"], y=bb["upper"],
                        line=dict(color="#333", width=1), name="BB Upper", showlegend=False,
                    ), row=1, col=1)
                    fig.add_trace(go.Scatter(
                        x=df["timestamp"], y=bb["lower"],
                        line=dict(color="#333", width=1), fill="tonexty",
                        fillcolor="rgba(40,40,40,0.2)", name="BB Lower", showlegend=False,
                    ), row=1, col=1)

                if "rsi" in series:
                    fig.add_trace(go.Scatter(
                        x=df["timestamp"], y=series["rsi"],
                        line=dict(color="#0088ff", width=1), name="RSI",
                    ), row=2, col=1)
                    fig.add_hline(y=70, line_dash="dash", line_color="#333", row=2, col=1)
                    fig.add_hline(y=30, line_dash="dash", line_color="#333", row=2, col=1)

                if "macd" in series:
                    macd_data = series["macd"]
                    fig.add_trace(go.Scatter(
                        x=df["timestamp"], y=macd_data["macd"],
                        line=dict(color="#0088ff", width=1), name="MACD",
                    ), row=3, col=1)
                    fig.add_trace(go.Scatter(
                        x=df["timestamp"], y=macd_data["signal"],
                        line=dict(color="#ffaa00", width=1), name="Signal",
                    ), row=3, col=1)
                    colors = ["#00ffaa" if v >= 0 else "#ff3333" for v in macd_data["hist"]]
                    fig.add_trace(go.Bar(
                        x=df["timestamp"], y=macd_data["hist"],
                        marker_color=colors, name="Histogram", showlegend=False,
                    ), row=3, col=1)

                fig.update_layout(
                    template="plotly_dark",
                    paper_bgcolor="#050505",
                    plot_bgcolor="#050505",
                    height=500,
                    margin=dict(l=40, r=10, t=10, b=20),
                    font=dict(family="JetBrains Mono", size=10, color="#666"),
                    xaxis_rangeslider_visible=False,
                    showlegend=True,
                    legend=dict(
                        orientation="h", yanchor="bottom", y=1.02,
                        xanchor="right", x=1, font=dict(size=9),
                    ),
                )
                for axis_name in ['xaxis', 'xaxis2', 'xaxis3', 'yaxis', 'yaxis2', 'yaxis3']:
                    fig.update_layout(**{axis_name: dict(gridcolor="#111", zeroline=False)})

                st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})
            else:
                st.markdown("<div style='color:#444; text-align:center; padding:40px;'>NO CANDLE DATA</div>", unsafe_allow_html=True)

        except Exception as e:
            st.markdown(f"<div style='color:#ff3333; font-size:11px;'>Chart error: {e}</div>", unsafe_allow_html=True)

        st.markdown("<div style='font-size:10px; color:#444;'>LOGIC_HIGHLIGHT</div>", unsafe_allow_html=True)
        term_placeholder = st.empty()
        stream_logs(term_placeholder, full=False)

    with c_right:
        st.markdown("<div style='font-size:10px; color:#444;'>INTELLIGENCE</div>", unsafe_allow_html=True)
        st.markdown(f"<div style='color:var(--accent-blue); font-size:12px;'>{status.get('details', 'STANDBY')}</div>", unsafe_allow_html=True)
        
        try:
            ticker = st.session_state.exchange.get_ticker(symbol)
            ticker_data = ticker.get("data", {})
            price = float(ticker_data.get("lastPrice", 0))
            if price > 0:
                st.markdown(f"<div style='font-size:20px; font-family:JetBrains Mono; color:var(--accent-green); margin-top:10px;'>INR {price:,.2f}</div>", unsafe_allow_html=True)
                vol24h = float(ticker_data.get("volume", 0))
                high24h = float(ticker_data.get("highPrice", 0))
                low24h = float(ticker_data.get("lowPrice", 0))
                st.markdown(f"""
                    <div style='font-family:JetBrains Mono; font-size:10px; color:#666; margin-top:5px;'>
                    VOL: {vol24h:,.0f}<br>
                    24H: {low24h:,.0f} - {high24h:,.0f}
                    </div>
                """, unsafe_allow_html=True)
        except Exception:
            pass

        # Open positions
        st.markdown("<div style='font-size:10px; color:#444; margin-top:15px;'>OPEN POSITIONS</div>", unsafe_allow_html=True)
        open_pos = st.session_state.db.get_open_positions()
        if open_pos:
            pos_html = '<table class="pos-table"><tr><th>SYM</th><th>DIR</th><th>ENTRY</th><th>SL</th><th>TP</th></tr>'
            for p in open_pos[:5]:
                pos_html += f'<tr><td>{p.get("symbol","")[:6]}</td><td>{p.get("direction","")}</td><td>{p.get("entry_price",0):.0f}</td><td>{p.get("stop_loss",0):.0f}</td><td>{p.get("take_profit",0):.0f}</td></tr>'
            pos_html += '</table>'
            st.markdown(pos_html, unsafe_allow_html=True)
        else:
            st.markdown("<div style='color:#333; font-size:10px;'>NO OPEN POSITIONS</div>", unsafe_allow_html=True)

with t_console:
    st.markdown("<div style='font-size:10px; color:#444; margin-bottom:10px;'>FULL_LOG_STREAM</div>", unsafe_allow_html=True)
    console_placeholder = st.empty()
    stream_logs(console_placeholder, full=True)

with t_status:
    s1, s2, s3 = st.columns(3)
    
    with s1:
        st.markdown("### SYSTEM")
        st.write(f"VERSION: `5.1.0` (Futures Paper Only)")
        st.write(f"MODE: `FUTURES PAPER TRADING`")
        st.write(f"SCAN: `{'MULTI-PAIR' if os.getenv('MULTI_PAIR_SCAN', 'true') == 'true' else 'SINGLE'}`")
        
        session = st.session_state.session_filter.get_session_info()
        sc = "ACTIVE" if session["can_trade"] else "BLOCKED"
        st.write(f"SESSION: `{session['current_session']}` ({sc})")
        if not session["can_trade"]:
            st.write(f"NEXT WINDOW: `{session['next_trading_window']}`")
    
    with s2:
        st.markdown("### DATABASE")
        st.write(f"TRADES: `{stats.get('total', 0)}`")
        st.write(f"WIN: `{stats.get('wins', 0)}` | LOSS: `{stats.get('losses', 0)}`")
        open_count = len(st.session_state.db.get_open_positions())
        max_pos = int(os.getenv("MAX_CONCURRENT_POSITIONS", 3))
        st.write(f"OPEN: `{open_count}/{max_pos}`")
    
    with s3:
        st.markdown("### API")
        try:
            cs_ok = st.session_state.exchange.ping()
            cs_status = "CONNECTED" if cs_ok else "UNREACHABLE"
        except Exception:
            cs_status = "ERROR"
        or_status = "CONFIGURED" if os.getenv("OPENROUTER_API_KEY") else "MISSING"
        st.write(f"COINSWITCH: `{cs_status}`")
        st.write(f"OPENROUTER: `{or_status}`")
        st.write(f"EQUITY: `INR {live_equity:,.2f}`")

    # Macro events
    st.divider()
    st.markdown("### MACRO EVENTS (NEXT 48H)")
    try:
        upcoming = st.session_state.news_filter.get_upcoming_events(hours_ahead=48)
        if upcoming:
            for evt in upcoming:
                st.markdown(f"""
                    <div class="event-row">
                        <span class="event-desc">{evt['description']}</span>
                        <span class="event-countdown">{evt['countdown']}</span>
                    </div>
                """, unsafe_allow_html=True)
        else:
            st.markdown("<div style='color:#333; font-size:11px;'>No events in next 48h.</div>", unsafe_allow_html=True)
    except Exception:
        pass

    # Equity curve
    st.divider()
    st.markdown("### EQUITY CURVE")
    portfolio_history = st.session_state.db.get_portfolio_history(limit=100)
    if portfolio_history:
        ph_df = pd.DataFrame(portfolio_history)
        ph_df["timestamp"] = pd.to_datetime(ph_df["timestamp"])
        ph_df = ph_df.sort_values("timestamp")
        
        fig_equity = go.Figure()
        fig_equity.add_trace(go.Scatter(
            x=ph_df["timestamp"], y=ph_df["capital"],
            mode="lines", line=dict(color="#0088ff", width=1.5),
            fill="tozeroy", fillcolor="rgba(0,136,255,0.05)",
        ))
        fig_equity.update_layout(
            template="plotly_dark",
            paper_bgcolor="#050505", plot_bgcolor="#050505",
            height=200, margin=dict(l=40, r=10, t=10, b=20),
            font=dict(family="JetBrains Mono", size=10, color="#666"),
            xaxis=dict(gridcolor="#111"), yaxis=dict(gridcolor="#111"),
            showlegend=False,
        )
        st.plotly_chart(fig_equity, use_container_width=True, config={"displayModeBar": False})
    else:
        st.markdown("<div style='color:#333; font-size:11px;'>No portfolio history yet.</div>", unsafe_allow_html=True)

with t_settings:
    st.markdown("### CONFIGURATION")
    st.markdown("<div style='font-size:10px; color:#444; margin-bottom:10px;'>Changes persist to .env on save.</div>", unsafe_allow_html=True)
    
    with st.form("settings_form"):
        st.markdown("**RISK MANAGEMENT**")
        c1, c2, c3 = st.columns(3)
        risk = c1.number_input("MAX RISK (%)", value=float(os.getenv("MAX_RISK_PER_TRADE", 2.0)), step=0.5)
        min_rr = c2.number_input("MIN R:R", value=float(os.getenv("MIN_RR_RATIO", 2.0)), step=0.5)
        daily_limit = c3.number_input("DAILY LOSS (%)", value=float(os.getenv("DAILY_LOSS_LIMIT_PCT", 5.0)), step=1.0)
        
        c4, c5, c6 = st.columns(3)
        max_pos = c4.number_input("MAX POSITIONS", value=int(os.getenv("MAX_CONCURRENT_POSITIONS", 3)), step=1)
        cooldown = c5.number_input("COOLDOWN CYCLES", value=int(os.getenv("COOLDOWN_CYCLES_AFTER_SL", 2)), step=1)
        interval = c6.number_input("INTERVAL (MIN)", value=int(os.getenv("TRADING_INTERVAL_MINUTES", 1)), step=1)
        
        st.markdown("**TRAILING STOP**")
        c7, c8, c9 = st.columns(3)
        trailing_enabled = c7.checkbox("ENABLED", value=os.getenv("TRAILING_STOP_ENABLED", "true") == "true")
        trailing_r = c8.number_input("ACTIVATION (R)", value=float(os.getenv("TRAILING_ACTIVATION_R", 1.25)), step=0.25)
        trailing_atr = c9.number_input("ATR MULT", value=float(os.getenv("TRAILING_ATR_MULTIPLIER", 1.75)), step=0.25)
        
        st.markdown("**SCANNING & SESSIONS**")
        c10, c11, c12 = st.columns(3)
        multi_scan = c10.checkbox("MULTI-PAIR", value=os.getenv("MULTI_PAIR_SCAN", "true") == "true")
        max_signals = c11.number_input("MAX SIGNALS", value=int(os.getenv("MAX_SIGNALS_PER_CYCLE", 3)), step=1)
        session_enabled = c12.checkbox("SESSION FILTER", value=os.getenv("SESSION_FILTER_ENABLED", "true") == "true")
        
        c13, c14, c15 = st.columns(3)
        weekend = c13.checkbox("WEEKEND PAUSE", value=os.getenv("WEEKEND_PAUSE", "false") == "true")
        spread_max = c14.number_input("MAX SPREAD (%)", value=float(os.getenv("MAX_SPREAD_PCT", 0.5)), step=0.1)

        st.markdown("**AI ENGINE**")
        ai_model = st.text_input("AI MODEL", value=os.getenv("AI_MODEL", "google/gemini-2.0-flash-001"))
        
        if st.form_submit_button("SAVE TO .ENV", use_container_width=True):
            write_env("MAX_RISK_PER_TRADE", str(risk))
            write_env("MIN_RR_RATIO", str(min_rr))
            write_env("DAILY_LOSS_LIMIT_PCT", str(daily_limit))
            write_env("MAX_CONCURRENT_POSITIONS", str(int(max_pos)))
            write_env("COOLDOWN_CYCLES_AFTER_SL", str(int(cooldown)))
            write_env("TRADING_INTERVAL_MINUTES", str(int(interval)))
            write_env("TRAILING_STOP_ENABLED", "true" if trailing_enabled else "false")
            write_env("TRAILING_ACTIVATION_R", str(trailing_r))
            write_env("TRAILING_ATR_MULTIPLIER", str(trailing_atr))
            write_env("MULTI_PAIR_SCAN", "true" if multi_scan else "false")
            write_env("MAX_SIGNALS_PER_CYCLE", str(int(max_signals)))
            write_env("SESSION_FILTER_ENABLED", "true" if session_enabled else "false")
            write_env("WEEKEND_PAUSE", "true" if weekend else "false")
            write_env("MAX_SPREAD_PCT", str(spread_max))
            write_env("AI_MODEL", ai_model)
            st.success("SAVED (restart bot to apply)")

# Auto-refresh
st_autorefresh(interval=30000, key="datarefresh")
