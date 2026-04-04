"""
Bias Engine Module
Core logic for calculating final NY session bias
"""

from typing import Dict, Tuple, List
from datetime import datetime, timezone
import pytz
from src.config import SESSION_WEIGHTS, CONFIDENCE_THRESHOLD, MACRO_EVENT_WEIGHTS, NY_SCORE_THRESHOLD
from src.market_analyzer import analyze_session_assets, calculate_session_bias
from src.macro_calendar import fetch_macro_calendar, calculate_macro_sentiment
from src.utils import logger

# ============================================================================
# BIAS CALCULATION ENGINE
# ============================================================================

def calculate_ny_bias() -> Dict:
    """
    Calculate final New York session bias based on:
    - Asia session close (30%)
    - London session close (40%)
    - Macro events (30%)
    
    Returns:
    {
        "timestamp": "2026-04-02T12:30:00Z",
        "asia_session": {
            "overall_bias": "BULLISH",
            "confidence": 0.75,
            "dominant_pattern": "Bullish Engulfing",
            "assets": {...}
        },
        "london_session": {
            "overall_bias": "BEARISH",
            "confidence": 0.65,
            "dominant_pattern": "Bearish Candle",
            "assets": {...}
        },
        "macro_sentiment": {
            "sentiment": "BULLISH",
            "confidence": 0.60,
            "upcoming_events": [...]
        },
        "ny_bias": {
            "signal": "BULLISH",
            "confidence": 0.72,  # >= 85% = valid signal
            "key_drivers": ["Asia neutral", "London weakness", "Macro dovish"],
            "is_valid_signal": False
        }
    }
    """
    
    logger.info("=" * 60)
    logger.info("STARTING NY BIAS CALCULATION")
    logger.info("=" * 60)
    
    report = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    
    # ========================================================================
    # ASIA SESSION ANALYSIS
    # ========================================================================
    logger.info("\n[ASIA SESSION] Analyzing...")
    asia_assets = analyze_session_assets("asia")
    asia_bias, asia_confidence, asia_pattern = calculate_session_bias(asia_assets)
    
    report["asia_session"] = {
        "overall_bias": asia_bias,
        "confidence": asia_confidence,
        "dominant_pattern": asia_pattern,
        "assets": asia_assets,
    }
    
    logger.info(f"Asia Bias: {asia_bias} ({asia_confidence:.0%} confidence)")
    
    # ========================================================================
    # LONDON SESSION ANALYSIS
    # ========================================================================
    logger.info("\n[LONDON SESSION] Analyzing...")
    london_assets = analyze_session_assets("london")
    london_bias, london_confidence, london_pattern = calculate_session_bias(london_assets)
    
    report["london_session"] = {
        "overall_bias": london_bias,
        "confidence": london_confidence,
        "dominant_pattern": london_pattern,
        "assets": london_assets,
    }
    
    logger.info(f"London Bias: {london_bias} ({london_confidence:.0%} confidence)")
    
    # ========================================================================
    # MACRO EVENTS ANALYSIS
    # ========================================================================
    logger.info("\n[MACRO EVENTS] Analyzing calendar...")
    macro_calendar = fetch_macro_calendar()
    macro_sentiment, macro_confidence = calculate_macro_sentiment(
        macro_calendar,
        MACRO_EVENT_WEIGHTS
    )
    
    report["macro_sentiment"] = {
        "sentiment": macro_sentiment,
        "confidence": macro_confidence,
        "upcoming_events": macro_calendar.get("upcoming_events", [])[:5],  # Top 5
        "weights": MACRO_EVENT_WEIGHTS,
    }
    
    logger.info(f"Macro Sentiment: {macro_sentiment} ({macro_confidence:.0%} confidence)")
    
    # ========================================================================
    # FINAL NY BIAS CALCULATION (Weighted Average)
    # ========================================================================
    logger.info("\n[FINAL DECISION] Computing NY opening bias...")
    
    # Convert BULLISH/BEARISH/NEUTRAL to numeric score (-1, 0, +1)
    def sentiment_to_score(sentiment: str, confidence: float) -> float:
        """Convert sentiment + confidence to numeric score"""
        if sentiment == "BULLISH":
            return confidence
        elif sentiment == "BEARISH":
            return -confidence
        else:
            return 0.0
    
    asia_score = sentiment_to_score(asia_bias, asia_confidence)
    london_score = sentiment_to_score(london_bias, london_confidence)
    macro_score = sentiment_to_score(macro_sentiment, macro_confidence)
    
    # Weighted average
    asia_weight = SESSION_WEIGHTS["asia"]
    london_weight = SESSION_WEIGHTS["london"]
    macro_weight = SESSION_WEIGHTS["macro"]
    
    ny_score = (
        asia_score * asia_weight +
        london_score * london_weight +
        macro_score * macro_weight
    )
    
    # Convert score back to signal + confidence
    if ny_score > NY_SCORE_THRESHOLD:
        ny_signal = "BULLISH"
        ny_confidence = min(abs(ny_score), 1.0)
    elif ny_score < -NY_SCORE_THRESHOLD:
        ny_signal = "BEARISH"
        ny_confidence = min(abs(ny_score), 1.0)
    else:
        ny_signal = "NEUTRAL"
        ny_confidence = 0.5
    
    # Determine validity (>= 85% confidence)
    is_valid = ny_confidence >= CONFIDENCE_THRESHOLD
    
    # Key drivers explanation
    key_drivers = _explain_bias(
        asia_bias, asia_confidence,
        london_bias, london_confidence,
        macro_sentiment, macro_confidence,
        ny_signal
    )
    
    report["ny_bias"] = {
        "signal": ny_signal,
        "confidence": ny_confidence,
        "weighted_score": ny_score,
        "is_valid_signal": is_valid,
        "confidence_threshold": CONFIDENCE_THRESHOLD,
        "key_drivers": key_drivers,
    }
    
    logger.info(f"\n{'*' * 60}")
    logger.info(f"NY OPENING BIAS: {ny_signal}")
    logger.info(f"Confidence: {ny_confidence:.1%}")
    logger.info(f"Valid Signal: {'YES' if is_valid else 'NO'} (threshold: {CONFIDENCE_THRESHOLD:.0%})")
    logger.info(f"{'*' * 60}\n")
    
    for driver in key_drivers:
        logger.info(f"  | {driver}")
    
    return report

# ============================================================================
# EXPLAIN BIAS (KEY DRIVERS)
# ============================================================================

def _explain_bias(
    asia_bias: str, asia_conf: float,
    london_bias: str, london_conf: float,
    macro_sentiment: str, macro_conf: float,
    ny_signal: str
) -> List[str]:
    """
    Generate human-readable explanation of bias decision
    """
    
    drivers = []
    
    # Fator Ásia
    if asia_bias == "BULLISH":
        drivers.append(f"* Ásia: Fecho em alta ({asia_conf:.0%}) — momentum positivo para Londres")
    elif asia_bias == "BEARISH":
        drivers.append(f"* Ásia: Fecho em baixa ({asia_conf:.0%}) — fraqueza a alimentar Londres")
    else:
        drivers.append(f"* Ásia: Consolidação neutra ({asia_conf:.0%})")

    # Fator Londres
    if london_bias == "BULLISH":
        drivers.append(f"* Londres: Movimento em alta ({london_conf:.0%}) — força para abertura NY")
    elif london_bias == "BEARISH":
        drivers.append(f"* Londres: Pressão em baixa ({london_conf:.0%}) — risco na abertura NY")
    else:
        drivers.append(f"* Londres: Range neutro ({london_conf:.0%})")

    # Fator Macro
    if macro_sentiment == "BULLISH":
        drivers.append(f"* Macro: Contexto positivo/dovish ({macro_conf:.0%}) — otimismo económico")
    elif macro_sentiment == "BEARISH":
        drivers.append(f"* Macro: Contexto negativo/hawkish ({macro_conf:.0%}) — ventos contrários")
    else:
        drivers.append(f"* Macro: Calendário neutro ({macro_conf:.0%})")

    # Conclusão
    if ny_signal == "BULLISH":
        drivers.append("* Conclusão: Tendência de alta para abertura NY")
    elif ny_signal == "BEARISH":
        drivers.append("* Conclusão: Tendência de baixa para abertura NY")
    else:
        drivers.append("* Conclusão: Sinais mistos — cautela em trades direcionais")
    
    return drivers

# ============================================================================
# VALIDATION & CHECKS
# ============================================================================

def validate_report(report: Dict) -> bool:
    """Validate report structure and required fields"""
    required_keys = [
        "timestamp",
        "asia_session",
        "london_session",
        "macro_sentiment",
        "ny_bias",
    ]
    
    for key in required_keys:
        if key not in report:
            logger.error(f"Missing required field in report: {key}")
            return False
    
    return True
