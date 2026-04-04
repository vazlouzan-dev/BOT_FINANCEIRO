"""
Market Analyzer Module
Fetches OHLC data from yfinance and detects candlestick patterns
"""

import yfinance as yf
import pandas as pd
from typing import Dict, List, Tuple, Optional
from datetime import datetime, timedelta
import time
import pytz
from src.config import ASSETS, CANDLE_CONFIG, TIMEZONES
from src.utils import logger, validate_ohlc_data, safe_divide

# Simple in-memory OHLC cache to avoid redundant API calls within the same run
_ohlc_cache: Dict[str, Tuple[pd.DataFrame, float]] = {}
_CACHE_TTL_SECONDS = 300  # 5 minutes

# ============================================================================
# CANDLESTICK PATTERN DETECTION
# ============================================================================

def get_candle_metrics(ohlc_row) -> Dict[str, float]:
    """
    Calculate key metrics from OHLC data
    Returns: body size, upper wick, lower wick, body position, etc.
    """
    open_price = ohlc_row['Open']
    high_price = ohlc_row['High']
    low_price = ohlc_row['Low']
    close_price = ohlc_row['Close']
    
    range_price = high_price - low_price
    range_safe = max(range_price, 0.0001)  # Avoid division by zero
    
    # Body size (open to close)
    body_size = abs(close_price - open_price)
    body_pct = safe_divide(body_size, range_safe)
    
    # Wicks
    upper_wick = high_price - max(open_price, close_price)
    lower_wick = min(open_price, close_price) - low_price
    
    # Body position (where close relative to range)
    body_position = safe_divide((close_price - low_price), range_safe)
    
    return {
        'open': open_price,
        'high': high_price,
        'low': low_price,
        'close': close_price,
        'range': range_price,
        'body_size': body_size,
        'body_pct': body_pct,
        'upper_wick': upper_wick,
        'lower_wick': lower_wick,
        'body_position': body_position,
        'close_up': close_price > open_price,  # True = bullish candle
    }

def detect_bullish_engulfing(candle_prev: Dict, candle_curr: Dict) -> bool:
    """
    Bullish Engulfing: 
    - Prior candle bearish (close < open)
    - Current candle bullish (close > open)
    - Current close > Prior open AND Current open < Prior close
    """
    if not candle_prev['close_up'] and candle_curr['close_up']:
        if (candle_curr['high'] > candle_prev['open'] and 
            candle_curr['low'] < candle_prev['close']):
            return True
    return False

def detect_bearish_engulfing(candle_prev: Dict, candle_curr: Dict) -> bool:
    """
    Bearish Engulfing: 
    - Prior candle bullish
    - Current candle bearish
    - Current close < Prior open AND Current open > Prior close
    """
    if candle_prev['close_up'] and not candle_curr['close_up']:
        if (candle_curr['low'] < candle_prev['open'] and 
            candle_curr['high'] > candle_prev['close']):
            return True
    return False

def detect_hammer(candle: Dict) -> bool:
    """
    Hammer: Small body at top, long lower wick
    - Lower wick > hammer_threshold * body_size
    - Upper wick small
    """
    threshold = CANDLE_CONFIG["hammer_threshold"]
    if candle['body_size'] > 0:
        wick_ratio = safe_divide(candle['lower_wick'], candle['body_size'])
        return wick_ratio > threshold and candle['upper_wick'] < candle['body_size'] * 0.3
    return False

def detect_shooting_star(candle: Dict) -> bool:
    """
    Shooting Star: Small body at bottom, long upper wick
    - Upper wick > threshold * body_size
    - Lower wick small
    """
    threshold = CANDLE_CONFIG["hammer_threshold"]
    if candle['body_size'] > 0:
        wick_ratio = safe_divide(candle['upper_wick'], candle['body_size'])
        return wick_ratio > threshold and candle['lower_wick'] < candle['body_size'] * 0.3
    return False

def detect_doji(candle: Dict) -> bool:
    """
    Doji: Open and close nearly equal, long wicks
    - Body size < doji_threshold
    """
    threshold = CANDLE_CONFIG["doji_threshold"]
    return candle['body_pct'] < threshold

def analyze_candlestick_pattern(df: pd.DataFrame) -> Tuple[str, float, str]:
    """
    Analyze last 5 candles to detect dominant pattern
    Returns: (pattern_name, confidence, direction)
    
    - pattern_name: "Bullish Engulfing", "Bearish Engulfing", "Hammer", "Shooting Star", "Doji", "Neutral"
    - confidence: 0.0-1.0 (how strong the pattern is)
    - direction: "BULLISH", "BEARISH", "NEUTRAL"
    """
    
    if len(df) < 2:
        return ("Insufficient Data", 0.0, "NEUTRAL")
    
    candles = df.tail(5).copy()
    metrics = []
    
    # Calculate metrics for all candles
    for idx, row in candles.iterrows():
        metrics.append(get_candle_metrics(row))
    
    # Analyze patterns (need at least 2 candles)
    if len(metrics) >= 2:
        # Check Engulfing patterns (last 2 candles)
        if detect_bullish_engulfing(metrics[-2], metrics[-1]):
            return ("Bullish Engulfing", 0.75, "BULLISH")
        
        if detect_bearish_engulfing(metrics[-2], metrics[-1]):
            return ("Bearish Engulfing", 0.75, "BEARISH")
    
    # Check current candle (last one)
    current_metric = metrics[-1]
    
    if detect_hammer(current_metric):
        return ("Hammer", 0.65, "BULLISH")
    
    if detect_shooting_star(current_metric):
        return ("Shooting Star", 0.65, "BEARISH")
    
    if detect_doji(current_metric):
        return ("Doji", 0.50, "NEUTRAL")
    
    # Default: Simple direction based on last candle
    if current_metric['close_up']:
        return ("Bullish Candle", 0.40, "BULLISH")
    else:
        return ("Bearish Candle", 0.40, "BEARISH")

# ============================================================================
# FETCH OHLC DATA
# ============================================================================

def fetch_ohlc_data(ticker: str, period: str = "5d", interval: str = "1d") -> Optional[pd.DataFrame]:
    """
    Fetch OHLC data from yfinance with in-memory cache (TTL=5min).

    Args:
        ticker: Stock ticker (e.g., "SPY", "EURUSD=X")
        period: Historical period ("5d", "1mo", "1y", etc.)
        interval: Candle interval ("1d", "1h", "15m", etc.)

    Returns:
        DataFrame with OHLC data or None if fetch fails
    """
    cache_key = f"{ticker}_{period}_{interval}"
    now = time.monotonic()

    # Return cached data if still fresh
    if cache_key in _ohlc_cache:
        cached_df, cached_at = _ohlc_cache[cache_key]
        if now - cached_at < _CACHE_TTL_SECONDS:
            logger.debug(f"Cache hit for {ticker}")
            return cached_df

    try:
        logger.debug(f"Fetching {ticker} data (period={period}, interval={interval})")
        data = yf.download(ticker, period=period, interval=interval, progress=False)

        if data.empty:
            logger.warning(f"No data returned for {ticker}")
            return None

        # yfinance >=0.2.x returns MultiIndex columns like ('Open', 'SPY').
        # Flatten to simple column names so row['Open'] returns a scalar.
        if isinstance(data.columns, pd.MultiIndex):
            data.columns = data.columns.get_level_values(0)

        _ohlc_cache[cache_key] = (data, now)
        return data

    except Exception as e:
        logger.error(f"Error fetching {ticker}: {e}")
        return None

def fetch_asset_ohlc(asset_key: str) -> Optional[pd.DataFrame]:
    """
    Fetch OHLC data for a specific asset from config
    
    Args:
        asset_key: Key in ASSETS dict (e.g., "SPY", "EURUSD")
    
    Returns:
        DataFrame or None
    """
    if asset_key not in ASSETS:
        logger.error(f"Asset {asset_key} not in config")
        return None
    
    asset = ASSETS[asset_key]
    return fetch_ohlc_data(asset['ticker'], period="5d", interval="1d")

# ============================================================================
# ANALYZE SESSION (ASIA or LONDON)
# ============================================================================

def analyze_session_assets(session_type: str) -> Dict[str, Dict]:
    """
    Analyze all assets relevant to a session (Asia or London)
    
    Returns dict with structure:
    {
        "asset_key": {
            "name": "Asset Name",
            "bias": "BULLISH|BEARISH|NEUTRAL",
            "pattern": "Pattern Name",
            "confidence": 0.75,
            "last_close": 150.25,
        },
        ...
    }
    """
    session_assets = {}

    # Asset selection per session:
    #   Asia   → US indices (SPY/QQQ/DIA as previous-day proxy) + global (GOLD, BTC, UST10Y)
    #   London → Forex pairs (EURUSD, GBPUSD) + global assets
    # Global assets (zone="global") trade 24/7 and are relevant to both sessions.
    session_type_lower = session_type.lower()

    for asset_key, asset_info in ASSETS.items():
        asset_zone = asset_info.get("zone", "global")

        include = (
            asset_zone == "global"
            or (session_type_lower == "asia" and asset_zone == "ny")
            or (session_type_lower == "london" and asset_zone == "london")
        )
        if not include:
            continue

        df = fetch_asset_ohlc(asset_key)

        if df is not None and len(df) >= 2:
            pattern, confidence, direction = analyze_candlestick_pattern(df)
            last_close = df['Close'].iloc[-1]

            session_assets[asset_key] = {
                "name": asset_info.get("name", asset_key),
                "bias": direction,
                "pattern": pattern,
                "confidence": confidence,
                "last_close": float(last_close),
            }

            logger.info(f"{session_type} | {asset_key}: {direction} ({pattern}, {confidence:.0%})")
        else:
            logger.debug(f"Could not analyze {asset_key} for {session_type}")
    
    return session_assets

def calculate_session_bias(session_assets: Dict[str, Dict]) -> Tuple[str, float, str]:
    """
    Calculate overall session bias from individual assets.
    Confidence is the average pattern confidence of the winning side,
    scaled by the proportion of assets that agree (avoids inflating
    confidence when only one weak-pattern asset is present).

    Returns: (overall_bias, confidence, dominant_pattern)
    """
    if not session_assets:
        return ("NEUTRAL", 0.0, "No Data")

    bullish_assets = [a for a in session_assets.values() if a['bias'] == 'BULLISH']
    bearish_assets = [a for a in session_assets.values() if a['bias'] == 'BEARISH']
    total = len(session_assets)

    bullish_pct = len(bullish_assets) / total
    bearish_pct = len(bearish_assets) / total

    if bullish_pct > 0.5:
        bias = "BULLISH"
        avg_pattern_conf = sum(a['confidence'] for a in bullish_assets) / len(bullish_assets)
        confidence = avg_pattern_conf * bullish_pct
    elif bearish_pct > 0.5:
        bias = "BEARISH"
        avg_pattern_conf = sum(a['confidence'] for a in bearish_assets) / len(bearish_assets)
        confidence = avg_pattern_conf * bearish_pct
    else:
        bias = "NEUTRAL"
        confidence = 0.5

    # Find dominant pattern
    all_patterns = [a.get('pattern', 'Unknown') for a in session_assets.values()]
    dominant_pattern = max(set(all_patterns), key=all_patterns.count) if all_patterns else "Mixed"

    return (bias, confidence, dominant_pattern)

# ============================================================================
# TESTING / MOCK DATA
# ============================================================================

def generate_mock_ohlc(bars: int = 5, trend: str = "bullish") -> pd.DataFrame:
    """
    Generate mock OHLC data for testing (no API calls)
    
    Args:
        bars: Number of candles to generate
        trend: "bullish", "bearish", or "neutral"
    """
    import numpy as np
    
    dates = pd.date_range(end=datetime.now(), periods=bars, freq='D')
    data = []
    
    base_price = 150.0
    
    for i, date in enumerate(dates):
        if trend == "bullish":
            open_p = base_price + i * 2
            close_p = open_p + np.random.uniform(1, 3)
        elif trend == "bearish":
            open_p = base_price + (len(dates) - i) * 2
            close_p = open_p - np.random.uniform(1, 3)
        else:
            open_p = base_price + np.random.uniform(-1, 1)
            close_p = open_p + np.random.uniform(-1, 1)
        
        high_p = max(open_p, close_p) + np.random.uniform(0.5, 2)
        low_p = min(open_p, close_p) - np.random.uniform(0.5, 2)
        
        data.append({
            'Open': open_p,
            'High': high_p,
            'Low': low_p,
            'Close': close_p,
        })
    
    return pd.DataFrame(data, index=dates)
