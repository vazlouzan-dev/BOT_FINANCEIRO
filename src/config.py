"""
Configuration file for Financial Market Bias Analyzer
Centralized settings for assets, timezones, API keys, and thresholds
"""

import os
from pathlib import Path
from dotenv import load_dotenv

# Absolute path to project root (works regardless of where the script is called from)
_PROJECT_ROOT = Path(__file__).resolve().parent.parent

# Load environment variables from .env file
load_dotenv()

# ============================================================================
# REGIME DETECTION (automatic macro regime classification)
# ============================================================================
REGIME_SCORE_INFLATION  =  2   # score >= this → "inflation_fight"
REGIME_SCORE_RECESSION  = -2   # score <= this → "recession_fear"

# Human-readable labels
REGIME_LABELS = {
    "inflation_fight": "Combate à Inflação",
    "recession_fear":  "Receio de Recessão",
    "neutral":         "Neutro",
}

# ============================================================================
# ASSETS TO MONITOR (9 assets across stocks, forex, commodities, crypto, bonds)
# ============================================================================
ASSETS = {
    # US Indices (Stocks)
    "SPY": {"ticker": "SPY", "name": "S&P 500", "type": "stock", "zone": "ny"},
    "QQQ": {"ticker": "QQQ", "name": "NASDAQ-100", "type": "stock", "zone": "ny"},
    "DIA": {"ticker": "DIA", "name": "Dow Jones", "type": "stock", "zone": "ny"},
    
    # Forex Pairs
    "EURUSD": {"ticker": "EURUSD=X", "name": "EUR/USD", "type": "forex", "zone": "london"},
    "GBPUSD": {"ticker": "GBPUSD=X", "name": "GBP/USD", "type": "forex", "zone": "london"},
    
    # Commodities
    "GOLD": {"ticker": "GC=F", "name": "XAU/USD (Gold)", "type": "commodity", "zone": "global"},
    "DXY": {"ticker": "DX-Y.NYB", "name": "US Dollar Index", "type": "commodity", "zone": "global"},
    
    # Crypto
    "BTC": {"ticker": "BTC-USD", "name": "Bitcoin", "type": "crypto", "zone": "global"},
    
    # US Bonds (Interest rates)
    "UST10Y": {"ticker": "^TNX", "name": "US Treasury 10Y Yield", "type": "bond", "zone": "global"},
}

# ============================================================================
# TIMEZONES (3 main sessions)
# ============================================================================
TIMEZONES = {
    "asia": "Asia/Tokyo",        # Asian session (closes 15:00 JST = 01:00 prev day NY)
    "london": "Europe/London",   # London session (closes 17:00 GMT = 12:00 same day NY)
    "ny": "America/New_York",    # New York (opens 09:30 AM = 14:30 GMT)
}

# ============================================================================
# API KEYS (User must register for FREE at FRED and Trading Economics)
# ============================================================================
FRED_API_KEY = os.getenv("FRED_API_KEY", "")
FINNHUB_API_KEY = os.getenv("FINNHUB_API_KEY", "")

# ============================================================================
# ANALYSIS THRESHOLDS
# ============================================================================
CONFIDENCE_THRESHOLD = 0.85  # 85% confidence required for valid signal
MIN_PATTERN_CONFIRMATION = 0.6  # 60% of candles must align for pattern
NY_SCORE_THRESHOLD = 0.15  # Minimum weighted score magnitude for a directional signal (vs NEUTRAL)

# ============================================================================
# MACRO EVENT WEIGHTS (Manual fixed weights for MVP)
# Total must sum to 1.0
# ============================================================================
MACRO_EVENT_WEIGHTS = {
    "NFP": 0.45,              # Non-Farm Payroll = 45% (highest USD volatility)
    "CPI": 0.20,              # Consumer Price Index
    "PCE": 0.10,              # Personal Consumption Expenditures (inflation)
    "PMI": 0.10,              # Purchasing Managers Index
    "jobless_claims": 0.08,   # Weekly Jobless Claims
    "other": 0.07,            # PPI, PBI, other indicators
}

# ============================================================================
# CANDLESTICK PATTERN DETECTION THRESHOLDS
# ============================================================================
CANDLE_CONFIG = {
    "body_size_threshold": 0.3,      # Min body size as % of total candle range
    "wick_ratio": 0.5,               # Max wick:body ratio for engulfing patterns
    "hammer_threshold": 0.6,         # Lower wick > 60% of body for hammer
    "doji_threshold": 0.1,           # Open-close diff < 10% of range = doji
}

# ============================================================================
# UPDATE INTERVALS
# ============================================================================
UPDATE_INTERVAL_SECONDS = 900  # 15 minutes (respects yfinance rate limits)
MARKET_HOURS = {
    "asia_open": "00:00",      # Asian market opens (UTC)
    "asia_close": "06:00",     # Asian market closes (UTC)
    "london_open": "08:00",    # London market opens (UTC)
    "london_close": "16:00",   # London market closes (UTC)
    "ny_open": "13:30",        # NY market opens (UTC)
    "ny_close": "20:00",       # NY market closes (UTC)
}

# ============================================================================
# BIAS CALCULATION WEIGHTS (Session influence on NY open)
# ============================================================================
SESSION_WEIGHTS = {
    "asia": 0.05,      # Asian close = 5% weight
    "london": 0.25,    # London close = 25% weight
    "macro": 0.70,     # Macro events = 70% weight
}

# ============================================================================
# LOGGING
# ============================================================================
LOG_FILE = str(_PROJECT_ROOT / "output" / "logs" / "bias_analyzer.log")
LOG_LEVEL = "INFO"  # DEBUG, INFO, WARNING, ERROR, CRITICAL

# ============================================================================
# OUTPUT
# ============================================================================
OUTPUT_JSON = str(_PROJECT_ROOT / "output" / "bias_report.json")
OUTPUT_CONSOLE = True  # Print to console
OUTPUT_FILE = True     # Save to JSON

# ============================================================================
# DEBUGGING / TESTING
# ============================================================================
USE_MOCK_DATA = False  # Set to True to test with synthetic data (no API calls)
BACKTEST_DAYS = 10     # Number of historical days to backtest
VERBOSE = True         # Detailed console logging
