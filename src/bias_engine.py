"""
Bias Engine Module
Core logic for calculating final NY session bias (focused on 9:30–10:30 NY opening window).

Flow:
  1. detect_market_regime()       → "inflation_fight" / "recession_fear" / "neutral"
  2. fetch_macro_calendar()       → events released at 08:30 NY (1h before open)
  3. calculate_macro_sentiment()  → regime-aware interpretation of macro data
  4. analyze_session_assets()     → Asia + London candlestick bias
  5. Weighted combination         → final NY opening bias
"""

from typing import Dict, Tuple, List
from datetime import datetime, timezone
import pytz
from src.config import SESSION_WEIGHTS, CONFIDENCE_THRESHOLD, MACRO_EVENT_WEIGHTS, NY_SCORE_THRESHOLD
from src.market_analyzer import analyze_session_assets, calculate_session_bias
from src.macro_calendar import fetch_macro_calendar, calculate_macro_sentiment
from src.regime_detector import detect_market_regime
from src.utils import logger

# ============================================================================
# BIAS CALCULATION ENGINE
# ============================================================================

def calculate_ny_bias() -> Dict:
    """
    Calculate final New York opening session bias (9:30–10:30 NY).

    Flow:
      1. Detect macro regime (inflation_fight / recession_fear / neutral)
      2. Fetch macro calendar (events released ~08:30 NY, 1h before open)
      3. Interpret macro data through the lens of the current regime
      4. Analyse Asia + London candlestick sessions
      5. Weighted combination → final bias

    Returns full report dict including regime, sessions, macro, and ny_bias.
    """

    logger.info("=" * 60)
    logger.info("STARTING NY OPENING BIAS CALCULATION (9:30–10:30 NY)")
    logger.info("=" * 60)

    report = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "target_window": "NY Opening 09:30–10:30 ET",
    }

    # ========================================================================
    # STEP 1 — REGIME DETECTION
    # ========================================================================
    logger.info("\n[REGIME] Detecting current macro regime...")
    regime_data = detect_market_regime()
    regime = regime_data["regime"]

    report["market_regime"] = regime_data
    logger.info(f"Regime: {regime.upper()} (score={regime_data['score']:+d})")

    # ========================================================================
    # STEP 2 — ASIA SESSION ANALYSIS
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
    # STEP 3 — LONDON SESSION ANALYSIS
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
    # STEP 4 — MACRO EVENTS (regime-aware interpretation)
    # ========================================================================
    logger.info(f"\n[MACRO EVENTS] Analyzing calendar with regime='{regime}'...")
    macro_calendar = fetch_macro_calendar()
    macro_sentiment, macro_confidence = calculate_macro_sentiment(
        macro_calendar,
        MACRO_EVENT_WEIGHTS,
        regime=regime,
    )

    report["macro_sentiment"] = {
        "sentiment": macro_sentiment,
        "confidence": macro_confidence,
        "regime_applied": regime,
        "upcoming_events": macro_calendar.get("upcoming_events", [])[:5],
        "weights": MACRO_EVENT_WEIGHTS,
        "data_sources": macro_calendar.get("data_sources", []),
    }
    
    logger.info(f"Macro Sentiment: {macro_sentiment} ({macro_confidence:.0%} confidence)")

    # ========================================================================
    # STEP 5 — FINAL NY BIAS CALCULATION (Weighted Average)
    # ========================================================================
    logger.info("\n[FINAL DECISION] Computing NY opening bias (9:30–10:30)...")
    
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
        ny_signal,
        regime,
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
    ny_signal: str,
    regime: str = "neutral",
) -> List[str]:
    """
    Generate human-readable explanation of bias decision
    """
    
    from src.config import REGIME_LABELS
    drivers = []

    # Regime activo
    regime_label = REGIME_LABELS.get(regime, regime)
    drivers.append(f"* Regime de mercado: {regime_label}")

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

    # Fator Macro (regime-contextualizado)
    if macro_sentiment == "BULLISH":
        if regime == "inflation_fight":
            drivers.append(f"* Macro: Dados fracos/dovish ({macro_conf:.0%}) — pressão sobre Fed alivia")
        else:
            drivers.append(f"* Macro: Dados fortes ({macro_conf:.0%}) — economia resiliente")
    elif macro_sentiment == "BEARISH":
        if regime == "inflation_fight":
            drivers.append(f"* Macro: Dados quentes ({macro_conf:.0%}) — Fed pode apertar mais")
        elif regime == "recession_fear":
            drivers.append(f"* Macro: Dados fracos ({macro_conf:.0%}) — recessão a ganhar força")
        else:
            drivers.append(f"* Macro: Contexto negativo ({macro_conf:.0%}) — ventos contrários")
    else:
        drivers.append(f"* Macro: Calendário neutro ({macro_conf:.0%})")

    # Conclusão
    if ny_signal == "BULLISH":
        drivers.append("* Conclusão: Tendência de alta para abertura NY (9:30–10:30)")
    elif ny_signal == "BEARISH":
        drivers.append("* Conclusão: Tendência de baixa para abertura NY (9:30–10:30)")
    else:
        drivers.append("* Conclusão: Sinais mistos — cautela em trades direcionais na abertura")

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
