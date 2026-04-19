# QuatSystem v5.0 — AI-Powered Quantitative Crypto Trading Bot

QuatSystem is a modern, modular, and fully automated quantitative trading framework. Originally built for crypto markets, it features deep, battle-tested integration with the **CoinSwitch Pro API**. The system brings institutional-grade risk management, dynamic regime filtering, and an AI-powered conversational dashboard to your personal portfolio.

---

## ⚙️ How It Works (The Engine)

The core logic operates autonomously in a highly optimized loop powered by the central `bot.py` engine.

1. **Market Scanning:** Every minute, the system aggressively queries CoinSwitch for high-resolution 15m, 1h, and 4h OHLCV (Open, High, Low, Close, Volume) candlestick data for 30+ liquid trading pairs.
2. **Signal Generation (`signal_engine.py`):** The system passes this raw data through advanced mathematical indicators (RSI, ADX, Bollinger Bands, EMAs, MACD) to classify the real-time market "Regime" (e.g., *Trending Bear*, *Ranging*, *Volatile Breakout*).
3. **Multi-Timeframe Validation:** A signal triggered on the 15m chart must be corroborated by long-term trend lines on the 1h and 4h charts (MTFA Gate) before proceeding.
4. **Strict Asset Filtering:** 
   - **Spread Check:** Drops pairs where the order-book spread is too wide (>1.5%) to protect against slippage.
   - **Liquidity Check:** Ensures there's actual trading volume so you aren't trapped in a dead coin.
5. **AI Veto (`OpenRouter/Gemini`):** Under certain configurations, passing signals are sent to an LLM via OpenRouter for a final contextual check ("Is this a false breakout?").
6. **Execution (`bot.py` & `exchange.py`):** If a signal survives the gauntlet, it reaches the execution engine.
7. **Position Management (`risk_manager.py`):** Active trades are dynamically monitored. As trades move into profit, the bot activates **ATR-based Trailing Stops** to lock in gains and minimize risk.

---

## 💸 How It Places Orders (Live Execution Logic)

Execution via the CoinSwitch Pro API is complex. QuatSystem employs several sophisticated bypasses and safeguards to ensure 100% reliable execution in a strict **Spot Market** environment.

### 1. Spot Market Naked Short Protection
CoinSwitch Pro is a **Spot-only** exchange. You cannot short-sell a coin you don't own. 
* When the bot detects a bearish regime and emits a `SELL` signal, it first checks the internal database. 
* If you **do not hold** an active exact long position for that coin, the bot recognizes it cannot short and intelligently **`SKIP`s** the signal.
* If you **do hold** the coin, the `SELL` signal acts as an aggressive early-close mechanism! It securely sells the *exact quantity* you currently hold, instantly realizing the profit/loss and returning capital to INR.

### 2. The Limit-Order Bypass
CoinSwitch's API backend contains a known validation bug where `market` orders circularly demand and reject the `price` field. 
To guarantee immediate execution ("Taker" behavior) without api-crashes, QuatSystem **forces all orders to `limit` types**. It fetches the exact millisecond current market price of the asset, injects it into the limit payload, and fires it—resulting in instant execution identical to a market order.

### 3. Affordability & Dynamic Sizing
Before buying, the bot asks: *"Do we have enough INR to execute the risk profile?"*
* If the required position exceeds your available capital, the bot dynamically scales the order down to utilize **90%** of your available balance (leaving a 5% buffer for exchange fees).
* It then validates that the final amount is greater than CoinSwitch's minimum order requirement (~₹100) before transmitting.

### 4. Ed25519 Cryptographic Layer
All orders sent to the API are cryptographically signed using the highly secure `Ed25519` curve. QuatSystem flawlessly computes epoch-stamps, manages payload-skipping rules for `POST` hashes required by CoinSwitch, and injects `X-AUTH-EPOCH` headers in real time.

---

## 🛠️ Setup Instructions

### 1. Prerequisites
- Python 3.10+
- A verified **CoinSwitch Pro** account with generated API Keys.

```bash
git clone https://github.com/your-username/quatsystem.git
cd quatsystem
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 2. Environment Configuration
Create a `.env` file in the root directory.

```env
# Exchange API Keys
COIN_SWITCH_API_KEY=your_cs_api_key_here
COIN_SWITCH_SECRET_KEY=your_cs_secret_key_here
COIN_SWITCH_BASE_URL=https://api-trading.coinswitch.co

# AI Configuration (Optional, uses OpenRouter)
OPENROUTER_API_KEY=sk-or-v1-...

# Trading Configuration
PAPER_TRADING=false           # Set to true for simulation mode
MAX_CONCURRENT_POSITIONS=1    # Limit simultaneous trades given low capital
INITIAL_CAPITAL=475.85        # Starting balance
MIN_ORDER_VALUE_INR=100

# Email Alerts
SMTP_EMAIL=your_email@gmail.com
SMTP_PASS=your_google_app_password
```

### 3. Running the System

You must start two processes simultaneously in separate terminals.

**Terminal 1: Start the Trading Bot Engine**
This process runs headless, scans markets, talks to the API, and executes trades autonomously.
```bash
./venv/bin/python -m core.bot
```

**Terminal 2: Start the Web Dashboard**
This hosts the beautiful Streamlit visual UI, allowing you to monitor Trades, PnL, logs, and talk to your QuatAI assistant.
```bash
./venv/bin/streamlit run app.py
```

---

## 🛑 Warning
If `PAPER_TRADING=false`, this system will execute **live financial transactions** using your exchange balance. Ensure your risk parameters are set conservatively until you are comfortable with the bot's execution speed and logic.
