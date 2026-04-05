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
from src.news_analyzer import fetch_all_news, calculate_news_sentiment
from src.historical_patterns import get_historical_context, build_history, _db_needs_rebuild
from src.utils import logger

# ============================================================================
# DYNAMIC WEIGHT TABLES
# Axes: news impact level × history availability
# History layer has fixed 15% when data is available (≥5 events),
# else redistributed to macro + sessions.
# ============================================================================
_DYNAMIC_WEIGHTS = {
    #                sessions  macro  news   history
    "high_hist":   {"sessions": 0.15, "macro": 0.15, "news": 0.55, "history": 0.15},
    "medium_hist": {"sessions": 0.25, "macro": 0.25, "news": 0.35, "history": 0.15},
    "low_hist":    {"sessions": 0.30, "macro": 0.35, "news": 0.20, "history": 0.15},
    "none_hist":   {"sessions": 0.35, "macro": 0.45, "news": 0.05, "history": 0.15},
    # Without history data:
    "high":        {"sessions": 0.20, "macro": 0.20, "news": 0.60, "history": 0.00},
    "medium":      {"sessions": 0.35, "macro": 0.30, "news": 0.35, "history": 0.00},
    "low":         {"sessions": 0.40, "macro": 0.40, "news": 0.20, "history": 0.00},
    "none":        {"sessions": 0.45, "macro": 0.50, "news": 0.05, "history": 0.00},
}

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
    # STEP 5 — NEWS ANALYSIS (SPY/QQQ + Magnificent 7, regime-aware)
    # ========================================================================
    logger.info(f"\n[NEWS] Fetching headlines for SPY, QQQ + Magnificent 7...")
    news_items  = fetch_all_news()
    news_result = calculate_news_sentiment(news_items, regime=regime)
    news_bias   = news_result["bias"]
    news_conf   = news_result["confidence"]
    news_impact = news_result["impact_level"]
    volatility  = news_result["volatility_flag"]

    report["news_sentiment"] = news_result
    logger.info(
        f"News Bias: {news_bias} ({news_conf:.0%} conf) | "
        f"Impact: {news_impact} | Volatilidade: {volatility}"
    )

    # ========================================================================
    # STEP 6 — HISTORICAL PATTERNS (base rates for current conditions)
    # ========================================================================
    logger.info(f"\n[HISTORY] Querying historical base rates (regime={regime})...")
    upcoming_events = macro_calendar.get("upcoming_events", [])
    hist_context    = get_historical_context(regime, upcoming_events)

    report["historical_context"] = hist_context
    if hist_context.get("available"):
        logger.info(
            f"Historical Bias: {hist_context['overall_bias']} "
            f"({hist_context['overall_conf']:.0%}) | "
            f"{hist_context['total_samples']} samples across "
            f"{len(hist_context['per_event'])} events"
        )
    else:
        logger.info("[HISTORY] No historical data available — run with --build-history first")

    # ========================================================================
    # STEP 7 — DYNAMIC WEIGHTS + FINAL CALCULATION
    # News impact level determines how much each layer contributes.
    # No news → macro dominates. High-impact news → news can override macro.
    # ========================================================================
    logger.info(f"\n[FINAL DECISION] Computing NY opening bias (9:30-10:30)...")

    hist_available = hist_context.get("available", False)
    weight_key     = f"{news_impact}_hist" if hist_available else news_impact
    weights        = _DYNAMIC_WEIGHTS.get(weight_key, _DYNAMIC_WEIGHTS[news_impact])
    w_sessions     = weights["sessions"]
    w_macro        = weights["macro"]
    w_news         = weights["news"]
    w_history      = weights["history"]

    logger.info(
        f"  Weights -> Sessions: {w_sessions:.0%} | Macro: {w_macro:.0%} | "
        f"Noticias: {w_news:.0%} | Historico: {w_history:.0%}"
    )

    def _to_score(sentiment: str, confidence: float) -> float:
        if sentiment == "BULLISH":
            return confidence
        elif sentiment == "BEARISH":
            return -confidence
        return 0.0

    # Sessions layer: Asia + London weighted internally (30/40 split)
    asia_w   = SESSION_WEIGHTS["asia"]   / (SESSION_WEIGHTS["asia"] + SESSION_WEIGHTS["london"])
    london_w = SESSION_WEIGHTS["london"] / (SESSION_WEIGHTS["asia"] + SESSION_WEIGHTS["london"])
    session_score = (
        _to_score(asia_bias, asia_confidence)    * asia_w +
        _to_score(london_bias, london_confidence) * london_w
    )

    macro_score   = _to_score(macro_sentiment, macro_confidence)
    news_score    = _to_score(news_bias, news_conf)
    history_score = _to_score(
        hist_context.get("overall_bias", "NEUTRAL"),
        hist_context.get("overall_conf", 0.0),
    ) if hist_available else 0.0

    ny_score = (
        session_score  * w_sessions +
        macro_score    * w_macro +
        news_score     * w_news +
        history_score  * w_history
    )

    if ny_score > NY_SCORE_THRESHOLD:
        ny_signal     = "BULLISH"
        ny_confidence = min(abs(ny_score), 1.0)
    elif ny_score < -NY_SCORE_THRESHOLD:
        ny_signal     = "BEARISH"
        ny_confidence = min(abs(ny_score), 1.0)
    else:
        ny_signal     = "NEUTRAL"
        ny_confidence = 0.5

    is_valid = ny_confidence >= CONFIDENCE_THRESHOLD

    key_drivers = _explain_bias(
        asia_bias, asia_confidence,
        london_bias, london_confidence,
        macro_sentiment, macro_confidence,
        news_bias, news_conf, news_impact,
        hist_context,
        ny_signal, regime, volatility, weights,
    )

    report["ny_bias"] = {
        "signal":               ny_signal,
        "confidence":           ny_confidence,
        "weighted_score":       round(ny_score, 4),
        "is_valid_signal":      is_valid,
        "confidence_threshold": CONFIDENCE_THRESHOLD,
        "volatility_expected":  volatility,
        "weights_used":         weights,
        "key_drivers":          key_drivers,
    }

    logger.info(f"\n{'*' * 60}")
    logger.info(f"NY OPENING BIAS: {ny_signal}")
    logger.info(f"Confidence: {ny_confidence:.1%}")
    logger.info(f"Volatilidade esperada: {volatility}")
    logger.info(f"Valid Signal: {'YES' if is_valid else 'NO'} (threshold: {CONFIDENCE_THRESHOLD:.0%})")
    logger.info(f"{'*' * 60}\n")
    for driver in key_drivers:
        logger.info(f"  | {driver}")

    return report

# ============================================================================
# EXPLAIN BIAS (KEY DRIVERS)
# ============================================================================

def _explain_bias(
    asia_bias: str,    asia_conf: float,
    london_bias: str,  london_conf: float,
    macro_sentiment: str, macro_conf: float,
    news_bias: str,    news_conf: float, news_impact: str,
    hist_context: Dict,
    ny_signal: str,
    regime: str = "neutral",
    volatility: str = "BAIXA",
    weights: Dict = None,
) -> List[str]:
    """Generate human-readable explanation of the bias decision."""
    from src.config import REGIME_LABELS
    if weights is None:
        weights = {"sessions": 0.40, "macro": 0.45, "news": 0.15}

    drivers = []

    # Regime + volatilidade
    regime_label = REGIME_LABELS.get(regime, regime)
    drivers.append(f"* Regime de mercado: {regime_label}")
    drivers.append(f"* Volatilidade esperada: {volatility}")

    # Pesos dinâmicos usados
    drivers.append(
        f"* Pesos: DXY/Sessoes {weights['sessions']:.0%} | "
        f"Macro {weights['macro']:.0%} | Noticias {weights['news']:.0%}"
    )

    # Fator Ásia (DXY/Global)
    if asia_bias == "BULLISH":
        drivers.append(f"* Asia (DXY/Global): Fecho em alta ({asia_conf:.0%}) — momentum positivo")
    elif asia_bias == "BEARISH":
        drivers.append(f"* Asia (DXY/Global): Fecho em baixa ({asia_conf:.0%}) — fraqueza global")
    else:
        drivers.append(f"* Asia (DXY/Global): Consolidacao neutra ({asia_conf:.0%})")

    # Fator Londres (DXY/Forex)
    if london_bias == "BULLISH":
        drivers.append(f"* Londres (Forex/DXY): Alta ({london_conf:.0%}) — forca para abertura NY")
    elif london_bias == "BEARISH":
        drivers.append(f"* Londres (Forex/DXY): Baixa ({london_conf:.0%}) — risco na abertura NY")
    else:
        drivers.append(f"* Londres (Forex/DXY): Range neutro ({london_conf:.0%})")

    # Fator Macro (regime-contextualizado)
    if macro_sentiment == "BULLISH":
        if regime == "inflation_fight":
            drivers.append(f"* Macro: Dados fracos/dovish ({macro_conf:.0%}) — pressao sobre Fed alivia")
        else:
            drivers.append(f"* Macro: Dados fortes ({macro_conf:.0%}) — economia resiliente")
    elif macro_sentiment == "BEARISH":
        if regime == "inflation_fight":
            drivers.append(f"* Macro: Dados quentes ({macro_conf:.0%}) — Fed pode apertar mais")
        elif regime == "recession_fear":
            drivers.append(f"* Macro: Dados fracos ({macro_conf:.0%}) — recessao a ganhar forca")
        else:
            drivers.append(f"* Macro: Contexto negativo ({macro_conf:.0%}) — ventos contrarios")
    else:
        drivers.append(f"* Macro: Calendario neutro ({macro_conf:.0%})")

    # Fator Noticias (SPY/QQQ + Mag7)
    impact_labels = {
        "high":   "ALTO IMPACTO — noticias dominam o sinal",
        "medium": "impacto medio",
        "low":    "impacto reduzido",
        "none":   "sem noticias relevantes — menos volatilidade",
    }
    impact_str = impact_labels.get(news_impact, news_impact)
    if news_bias == "BULLISH":
        drivers.append(f"* Noticias SPY/QQQ/Mag7: Sentimento positivo ({news_conf:.0%}) | {impact_str}")
    elif news_bias == "BEARISH":
        drivers.append(f"* Noticias SPY/QQQ/Mag7: Sentimento negativo ({news_conf:.0%}) | {impact_str}")
    else:
        drivers.append(f"* Noticias SPY/QQQ/Mag7: Neutro ({news_conf:.0%}) | {impact_str}")

    # Fator Historico
    if hist_context.get("available"):
        hb   = hist_context.get("overall_bias", "NEUTRAL")
        hc   = hist_context.get("overall_conf", 0.0)
        hn   = hist_context.get("total_samples", 0)
        nevt = len(hist_context.get("per_event", []))
        drivers.append(
            f"* Historico ({nevt} eventos, {hn} amostras): "
            f"{hb} ({hc:.0%}) — base rate em condicoes similares"
        )
    else:
        drivers.append("* Historico: sem dados — corra --build-history para activar")

    # Conclusao
    if ny_signal == "BULLISH":
        drivers.append("* Conclusao: Tendencia de alta para abertura NY (9:30-10:30)")
    elif ny_signal == "BEARISH":
        drivers.append("* Conclusao: Tendencia de baixa para abertura NY (9:30-10:30)")
    else:
        drivers.append("* Conclusao: Sinais mistos — cautela em trades direcionais na abertura")

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
