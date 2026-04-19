import requests
import os
import json
from typing import Dict, Any, Optional
from dotenv import load_dotenv

load_dotenv()


class AIEngine:
    """
    AI-powered analysis via OpenRouter.
    Role: secondary confirmation layer (veto gate).
    Can block trades but CANNOT initiate them.
    """

    def __init__(self):
        self.api_key = os.getenv("OPENROUTER_API_KEY")
        self.model = os.getenv("AI_MODEL", "google/gemini-2.0-flash-001")
        self.base_url = "https://openrouter.ai/api/v1/chat/completions"
        self.temperature = float(os.getenv("AI_TEMPERATURE", 0.0))

    # ── Veto Layer (used by bot pipeline) ───────────────────

    def confirm_signal(self, direction: str, entry: float, stop_loss: float,
                       take_profit: float, confluence_factors: list,
                       indicators: Dict[str, Any],
                       market_context: str) -> Dict[str, Any]:
        """
        AI confirmation gate. Receives a fully-formed signal from the
        deterministic engine and decides whether to APPROVE or VETO.
        Cannot initiate trades — only confirm or reject.
        """
        # Filter out non-serializable indicator data
        clean_indicators = {k: v for k, v in indicators.items()
                           if k != "_series" and not k.startswith("_")}

        # Convert numpy/pandas types to native Python
        for k, v in clean_indicators.items():
            try:
                if hasattr(v, 'item'):
                    clean_indicators[k] = v.item()
                elif isinstance(v, list):
                    clean_indicators[k] = [float(x) if hasattr(x, 'item') else x for x in v]
            except (ValueError, TypeError):
                clean_indicators[k] = str(v)

        prompt = f"""A deterministic trading system has generated the following signal:

SIGNAL:
- Direction: {direction}
- Entry Price: {entry:.2f}
- Stop Loss: {stop_loss:.2f}
- Take Profit: {take_profit:.2f}
- Market Context: {market_context}

CONFLUENCE FACTORS THAT TRIGGERED THIS SIGNAL:
{json.dumps(confluence_factors, indent=2)}

CURRENT INDICATOR STATE:
{json.dumps(clean_indicators, indent=2, default=str)}

YOUR TASK:
You are a risk management AI. Review this signal and decide:
- APPROVE: The signal has valid technical backing and acceptable risk.
- VETO: The signal has a critical flaw (divergence, false signal risk, extreme conditions).

You must be conservative. Only VETO if you identify a genuine risk that the
deterministic system missed. Do NOT veto simply because you prefer a different trade.

RESPONSE FORMAT (JSON ONLY):
{{
  "approved": true/false,
  "reason": "Brief explanation (1-2 sentences)"
}}"""

        return self._call_api(
            system_msg="You are a conservative risk management AI for crypto trading. You review pre-formed signals and approve or veto them. Respond only in JSON.",
            user_msg=prompt,
            fallback={"approved": True, "reason": "AI unavailable, defaulting to approve"}
        )

    # ── Playground Analysis (used by UI only) ───────────────

    def analyze_market(self, symbol: str, market_data: Dict[str, Any],
                       indicators: Dict[str, Any]) -> Dict[str, Any]:
        """
        Full market analysis for the AI Playground tab.
        This is the original analysis method — kept for interactive use only.
        NOT used in the automated trading pipeline.
        """
        # Filter out series data
        clean_indicators = {k: v for k, v in indicators.items()
                           if k != "_series" and not k.startswith("_")}
        for k, v in clean_indicators.items():
            try:
                if hasattr(v, 'item'):
                    clean_indicators[k] = v.item()
            except (ValueError, TypeError):
                clean_indicators[k] = str(v)

        prompt = f"""Analyze the following crypto market data for {symbol} and provide a trading decision.

MARKET DATA:
- Current Price: {market_data.get('lastPrice')}
- 24h High: {market_data.get('highPrice')}
- 24h Low: {market_data.get('lowPrice')}
- 24h Volume: {market_data.get('volume')}

TECHNICAL INDICATORS:
{json.dumps(clean_indicators, indent=2, default=str)}

INSTRUCTIONS:
1. Evaluate the trend using EMA crossover, RSI, and MACD.
2. Consider market structure (bullish/bearish/ranging).
3. Check for confluence between multiple indicators.
4. Provide a clear decision: BUY, SELL, or HOLD.
5. Provide detailed reasoning.

RESPONSE FORMAT (JSON ONLY):
{{
  "decision": "BUY/SELL/HOLD",
  "reasoning": "Detailed explanation...",
  "confidence_score": 0.0-1.0
}}"""

        return self._call_api(
            system_msg="You are a professional crypto trading analyst. Provide structured JSON decisions based on technical data.",
            user_msg=prompt,
            fallback={
                "decision": "HOLD",
                "reasoning": "AI analysis unavailable",
                "confidence_score": 0.0
            }
        )

    # ── Sidebar Chat (conversational) ──────────────────────

    def chat(self, user_message: str, context: str = "") -> str:
        """
        General-purpose conversational query for the sidebar chat panel.
        Returns a plain-text response (not JSON).
        """
        if not self.api_key:
            return "AI is not configured. Set OPENROUTER_API_KEY in .env."

        system_msg = (
            "You are QuatSystem AI — a concise, expert crypto trading assistant. "
            "You have access to a live CoinSwitch Pro trading terminal. "
            "Answer questions about markets, strategies, indicators, portfolio management, and the bot's behaviour. "
            "Keep answers short (2-4 sentences max) unless the user asks for detail. "
            "If additional market context is provided, use it."
        )

        user_msg = user_message
        if context:
            user_msg = f"CURRENT MARKET CONTEXT:\n{context}\n\nUSER QUESTION:\n{user_message}"

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://github.com/sayan/quat_system",
            "X-Title": "QuatSystem Crypto Bot",
        }

        payload = {
            "model": self.model,
            "temperature": 0.4,
            "messages": [
                {"role": "system", "content": system_msg},
                {"role": "user", "content": user_msg},
            ],
        }

        try:
            response = requests.post(self.base_url, headers=headers,
                                     json=payload, timeout=30)
            response.raise_for_status()
            result = response.json()
            return result["choices"][0]["message"]["content"]
        except Exception as e:
            return f"AI request failed: {e}"

    # ── Internal API Caller ─────────────────────────────────

    def _call_api(self, system_msg: str, user_msg: str,
                  fallback: Dict[str, Any]) -> Dict[str, Any]:
        """Generic OpenRouter API call with error handling."""
        if not self.api_key:
            return fallback

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://github.com/sayan/quat_system",
            "X-Title": "QuatSystem Crypto Bot",
        }

        payload = {
            "model": self.model,
            "temperature": self.temperature,
            "messages": [
                {"role": "system", "content": system_msg},
                {"role": "user", "content": user_msg},
            ],
            "response_format": {"type": "json_object"},
        }

        try:
            response = requests.post(self.base_url, headers=headers,
                                     json=payload, timeout=30)
            response.raise_for_status()
            result = response.json()
            content = result["choices"][0]["message"]["content"]
            return json.loads(content)
        except Exception as e:
            print(f"AI API call failed: {e}")
            return fallback
