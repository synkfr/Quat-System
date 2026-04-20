# QuatSystem v5.1 — AI-Powered Futures Training Bot (Paper Edition)

QuatSystem is a high-performance quantitative trading framework now optimized for **Futures Paper Trading**. This edition is designed as a training ground for traders to master algorithmic execution in derivatives markets using real-time CoinSwitch market data without financial risk.

---

## ⚙️ How It Works (The Engine)

The core logic operates autonomously in a highly optimized loop powered by the central `bot.py` engine, now hardcoded for safety.

1. **Market Scanning:** Every minute, the system queries CoinSwitch for high-resolution 15m, 1h, and 4h OHLCV data across liquid USDT-margined futures contracts.
2. **Futures Signal Engine (`signal_engine.py`):** The system classifies market "Regimes" (Long/Short) and generates signals suitable for leveraged trading.
3. **Multi-Timeframe Validation:** High-resolution signals are cross-validated against macro trends to reduce noise and "fakeouts."
4. **Paper Execution Engine:** Survivor signals are processed through a virtual execution layer that mimics the constraints of a futures market (Leverage, Margin, Min Qty).
5. **Position Management:** Active paper positions are monitored for SL/TP hits and feature **ATR-based Trailing Stops** to simulate real-world profit locking.

---

## 🎓 The Training Framework (Futures-Only)

This version of QuatSystem has been specifically refined to remove Spot market logic and lock users into a safe Paper Trading environment.

### 1. USDT-Margined Futures Logic
The bot maps local Indian market pairs (e.g., BTC/INR) to their global USDT-margined counterparts (e.g., `btcusdt`) for deep data analysis and execution logic.

### 2. Leverage & Margin Simulation
* **Default Leverage:** Fixed at **5x** (configurable via `.env`).
* **Margin Checks:** The bot calculates the "Required Margin" (`Notional / Leverage`) and rejects virtual trades if your virtual capital is insufficient.
* **Exchange Minimums:** Enforces a minimum base quantity of `0.01` (standard for BTC/USDT futures) to prepare you for the constraints of live exchanges like Binance.

### 3. Safety-First (Hardcoded Paper Mode)
For training purposes, the live execution code has been **removed from the bot core**. Even if you provide API keys, the bot will only log virtual trades. This ensures you can calibrate your AI filters and strategies with zero risk of accidentally placing a real order.

---

## 🛠️ Setup Instructions

### 1. Prerequisites
- Python 3.10+
- **CoinSwitch Pro** API Keys (used for reading live market data).

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
# CoinSwitch PRO Keys (For Data Only)
COIN_SWITCH_API_KEY=your_key
COIN_SWITCH_SECRET_KEY=your_secret

# AI Settings
OPENROUTER_API_KEY=your_openrouter_key

# Training Config
INITIAL_CAPITAL=10000         # Start with virtual ₹10,000
LEVERAGE=5                    # 5x Multiplier
MAX_CONCURRENT_POSITIONS=3    # Master multitasking
```

### 3. Running the Trainer

**Terminal 1: The Bot Processor**
```bash
python -m core.bot
```

**Terminal 2: The Command Terminal**
```bash
streamlit run app.py
```

---

## 🚀 Next Steps
Once you have mastered your strategy in the QuatSystem Paper Terminal, the code is structurally ready for a **Binance Futures** migration!
