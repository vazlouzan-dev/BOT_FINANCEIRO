"""
Regime Detector Module
Detects the current macro market regime automatically based on:
  - Yield curve (10Y - 2Y spread)
  - VIX (volatility/fear index)
  - CPI level and trend
  - PCE (Core PCE) level and trend  ← Fed's preferred inflation gauge
  - Fed Funds Rate
  - Unemployment rate trend
  - PMI level

Regime outputs:
  "inflation_fight"  — Fed is fighting inflation; hot data = bearish for stocks
  "recession_fear"   — Market fears slowdown; weak data = bearish, strong data = bullish
  "neutral"          — Mixed signals; standard interpretation applies

Note on CPI vs PCE:
  The Fed officially targets Core PCE at 2% (not CPI).
  PCE tends to run ~0.3-0.5pp below CPI but is more comprehensive.
  Both are included: PCE carries more weight in regime scoring.
"""

import yfinance as yf
import pandas as pd
from typing import Dict, Tuple, Optional
from src.utils import logger

# ============================================================================
# REGIME THRESHOLDS (tunable via config in future)
# ============================================================================
YIELD_CURVE_INVERSION_STRONG = -0.50   # 10Y-2Y < -0.5% = strongly inverted
YIELD_CURVE_INVERSION_MILD   = 0.0     # 10Y-2Y < 0 = mildly inverted
YIELD_CURVE_STEEP            = 1.5     # 10Y-2Y > 1.5% = steep (growth)
VIX_HIGH_FEAR                = 30      # VIX > 30 = panic
VIX_ELEVATED                 = 20      # VIX > 20 = concern
VIX_COMPLACENT               = 15      # VIX < 15 = calm
CPI_HIGH_INFLATION           = 4.0     # CPI > 4% = high inflation
CPI_ELEVATED_INFLATION       = 3.0     # CPI > 3% = elevated
CPI_BELOW_TARGET             = 2.0     # CPI < 2% = below Fed target
# PCE thresholds (Fed target = 2%; PCE runs ~0.3-0.5pp below CPI)
PCE_HIGH_INFLATION           = 3.0     # Core PCE > 3% = high (Fed very hawkish)
PCE_ELEVATED_INFLATION       = 2.5     # Core PCE > 2.5% = elevated (Fed concerned)
PCE_BELOW_TARGET             = 1.8     # Core PCE < 1.8% = below target (disinflationary)
FED_RATE_HIGH                = 4.0     # Fed Funds > 4% = restrictive
UNEMPLOYMENT_RISE_FAST       = 0.5     # Unemployment rose > 0.5pp in 3m = alarm
UNEMPLOYMENT_RISE_MILD       = 0.2     # Unemployment rose > 0.2pp = warning
PMI_CONTRACTION              = 48.0    # PMI < 48 = clear contraction
PMI_EXPANSION                = 52.0    # PMI > 52 = clear expansion

# Regime thresholds
INFLATION_SCORE_THRESHOLD    = 2       # score >= 2 = inflation_fight
RECESSION_SCORE_THRESHOLD    = -2      # score <= -2 = recession_fear


# ============================================================================
# FETCH INDICATORS
# ============================================================================

def _fetch_yf_latest(ticker: str) -> Optional[float]:
    """Fetch the most recent closing value for a yfinance ticker."""
    try:
        data = yf.download(ticker, period="5d", interval="1d", progress=False)
        if data.empty:
            return None
        if isinstance(data.columns, pd.MultiIndex):
            data.columns = data.columns.get_level_values(0)
        return float(data["Close"].iloc[-1])
    except Exception as e:
        logger.debug(f"yfinance fetch failed for {ticker}: {e}")
        return None


def _fetch_fred_series(series_id: str, observations: int = 4) -> Optional[list]:
    """
    Fetch the last N observations from FRED.
    Returns list of {"date": str, "value": float} sorted oldest→newest,
    or None on failure.
    """
    try:
        import requests
        from src.config import FRED_API_KEY
        if not FRED_API_KEY:
            return None
        url = "https://api.stlouisfed.org/fred/series/observations"
        params = {
            "series_id": series_id,
            "api_key": FRED_API_KEY,
            "limit": observations,
            "sort_order": "desc",
        }
        resp = requests.get(url, params=params, timeout=10)
        resp.raise_for_status()
        raw = resp.json().get("observations", [])
        result = []
        for obs in raw:
            try:
                result.append({"date": obs["date"], "value": float(obs["value"])})
            except (ValueError, TypeError):
                pass
        return list(reversed(result)) if result else None
    except Exception as e:
        logger.debug(f"FRED fetch failed for {series_id}: {e}")
        return None


def fetch_yield_curve() -> Optional[float]:
    """
    Returns the 10Y-2Y Treasury spread in percentage points.
    Uses FRED DGS10 and DGS2 if API key is available,
    falls back to yfinance ^TNX (10Y) minus ^IRX (13-week) as proxy.
    """
    try:
        y10_obs = _fetch_fred_series("DGS10", 1)
        y2_obs  = _fetch_fred_series("DGS2",  1)
        if y10_obs and y2_obs:
            spread = y10_obs[-1]["value"] - y2_obs[-1]["value"]
            logger.debug(f"Yield curve (FRED): 10Y={y10_obs[-1]['value']:.2f} 2Y={y2_obs[-1]['value']:.2f} spread={spread:.2f}")
            return spread
    except Exception:
        pass

    # Fallback: yfinance
    y10 = _fetch_yf_latest("^TNX")
    y2  = _fetch_yf_latest("^IRX")   # 13-week T-bill — not ideal but available
    if y10 is not None and y2 is not None:
        spread = y10 - y2
        logger.debug(f"Yield curve (yfinance proxy): 10Y={y10:.2f} 13W={y2:.2f} spread={spread:.2f}")
        return spread
    if y10 is not None:
        logger.debug("Only 10Y available for yield curve — cannot compute spread")
    return None


def fetch_vix() -> Optional[float]:
    """Returns current VIX level."""
    vix = _fetch_yf_latest("^VIX")
    if vix:
        logger.debug(f"VIX: {vix:.2f}")
    return vix


def fetch_cpi_trend() -> Tuple[Optional[float], Optional[float]]:
    """
    Returns (latest_cpi_yoy, cpi_3m_delta).
    latest_cpi_yoy: year-over-year CPI % (raw index value from FRED CPIAUCSL)
    cpi_3m_delta:   change in CPI over last 3 months (positive = rising)
    """
    obs = _fetch_fred_series("CPIAUCSL", 13)   # 13 months for YoY
    if obs and len(obs) >= 2:
        latest = obs[-1]["value"]
        prev_3m = obs[-4]["value"] if len(obs) >= 4 else obs[0]["value"]
        # Approximate YoY from index
        prev_12m = obs[-13]["value"] if len(obs) >= 13 else obs[0]["value"]
        yoy = ((latest - prev_12m) / prev_12m) * 100 if prev_12m else None
        delta_3m = latest - prev_3m
        logger.debug(f"CPI: latest={latest:.1f} yoy≈{yoy:.1f}% 3m_delta={delta_3m:.2f}")
        return yoy, delta_3m
    return None, None


def fetch_pce_trend() -> Tuple[Optional[float], Optional[float]]:
    """
    Returns (core_pce_yoy, pce_3m_delta) using FRED PCEPILFE (Core PCE Price Index).
    Core PCE excludes food and energy — this is what the Fed officially targets at 2%.

    core_pce_yoy:  approximate year-over-year % change
    pce_3m_delta:  change in index level over last 3 months (positive = rising)
    """
    obs = _fetch_fred_series("PCEPILFE", 13)   # 13 months for YoY
    if obs and len(obs) >= 2:
        latest  = obs[-1]["value"]
        prev_3m  = obs[-4]["value"] if len(obs) >= 4 else obs[0]["value"]
        prev_12m = obs[-13]["value"] if len(obs) >= 13 else obs[0]["value"]
        yoy      = ((latest - prev_12m) / prev_12m) * 100 if prev_12m else None
        delta_3m = latest - prev_3m
        logger.debug(f"Core PCE: latest={latest:.3f} yoy≈{yoy:.2f}% 3m_delta={delta_3m:.3f}")
        return yoy, delta_3m
    return None, None


def fetch_fed_rate() -> Optional[float]:
    """Returns latest effective Fed Funds Rate from FRED."""
    obs = _fetch_fred_series("FEDFUNDS", 1)
    if obs:
        rate = obs[-1]["value"]
        logger.debug(f"Fed Funds Rate: {rate:.2f}%")
        return rate
    return None


def fetch_unemployment_trend() -> Tuple[Optional[float], Optional[float]]:
    """
    Returns (latest_unemployment, 3m_change).
    Positive 3m_change = unemployment rising (bad).
    """
    obs = _fetch_fred_series("UNRATE", 4)
    if obs and len(obs) >= 2:
        latest = obs[-1]["value"]
        prev_3m = obs[0]["value"]
        delta = latest - prev_3m
        logger.debug(f"Unemployment: latest={latest:.1f}% 3m_delta={delta:+.2f}pp")
        return latest, delta
    return None, None


def fetch_pmi() -> Optional[float]:
    """Returns latest ISM Manufacturing PMI from FRED (MMNRNJ)."""
    obs = _fetch_fred_series("MMNRNJ", 1)
    if obs:
        pmi = obs[-1]["value"]
        logger.debug(f"PMI: {pmi:.1f}")
        return pmi
    # Fallback: try ISM ETF proxy via yfinance — not reliable, skip
    return None


# ============================================================================
# SCORING ENGINE
# ============================================================================

def _score_yield_curve(spread: Optional[float]) -> int:
    """Negative score = recession signal, positive = inflation/growth."""
    if spread is None:
        return 0
    if spread < YIELD_CURVE_INVERSION_STRONG:
        return -2   # strongly inverted = recession alarm
    if spread < YIELD_CURVE_INVERSION_MILD:
        return -1   # mildly inverted = caution
    if spread > YIELD_CURVE_STEEP:
        return +1   # steep curve = growth expected
    return 0


def _score_vix(vix: Optional[float]) -> int:
    if vix is None:
        return 0
    if vix > VIX_HIGH_FEAR:
        return -2   # panic = recession/risk-off
    if vix > VIX_ELEVATED:
        return -1   # elevated concern
    return 0        # calm VIX doesn't push either way


def _score_cpi(cpi_yoy: Optional[float], cpi_delta: Optional[float]) -> int:
    if cpi_yoy is None:
        return 0
    score = 0
    if cpi_yoy > CPI_HIGH_INFLATION:
        score += 2
    elif cpi_yoy > CPI_ELEVATED_INFLATION:
        score += 1
    elif cpi_yoy < CPI_BELOW_TARGET:
        score -= 1   # below target → more room for recession fear
    # Trend reinforcement
    if cpi_delta is not None:
        if cpi_delta > 0.5:
            score += 1   # rising fast
        elif cpi_delta < -0.5:
            score -= 1   # falling fast
    return score


def _score_pce(pce_yoy: Optional[float], pce_delta: Optional[float]) -> int:
    """
    Score PCE (Core PCE YoY).
    PCE carries more weight than CPI because it is the Fed's official target.
    Max contribution: ±3 points (vs ±3 for CPI).
    """
    if pce_yoy is None:
        return 0
    score = 0
    if pce_yoy > PCE_HIGH_INFLATION:
        score += 3   # well above 2% target → strong inflation fight signal
    elif pce_yoy > PCE_ELEVATED_INFLATION:
        score += 2   # above 2.5% → Fed still restrictive
    elif pce_yoy > 2.0:
        score += 1   # marginally above target → mild concern
    elif pce_yoy < PCE_BELOW_TARGET:
        score -= 2   # clearly below target → more room to cut → recession risk weighs more
    # Trend reinforcement
    if pce_delta is not None:
        if pce_delta > 0.3:
            score += 1   # accelerating
        elif pce_delta < -0.3:
            score -= 1   # decelerating — dis-inflationary
    return score


def _score_fed_rate(fed_rate: Optional[float], cpi_yoy: Optional[float]) -> int:
    if fed_rate is None:
        return 0
    if fed_rate > FED_RATE_HIGH:
        if cpi_yoy and cpi_yoy > CPI_ELEVATED_INFLATION:
            return +1   # high rates AND high inflation = still fighting
        else:
            return -1   # high rates but inflation falling = recession risk from overtightening
    return 0


def _score_unemployment(delta: Optional[float]) -> int:
    if delta is None:
        return 0
    if delta > UNEMPLOYMENT_RISE_FAST:
        return -2
    if delta > UNEMPLOYMENT_RISE_MILD:
        return -1
    if delta < -UNEMPLOYMENT_RISE_MILD:
        return +1   # falling unemployment = growth
    return 0


def _score_pmi(pmi: Optional[float]) -> int:
    if pmi is None:
        return 0
    if pmi < PMI_CONTRACTION:
        return -1
    if pmi > PMI_EXPANSION:
        return +1
    return 0


# ============================================================================
# PUBLIC API
# ============================================================================

def detect_market_regime() -> Dict:
    """
    Detect the current macro market regime.

    Returns:
    {
        "regime": "inflation_fight" | "recession_fear" | "neutral",
        "score": int,           # raw score (positive=inflation, negative=recession)
        "confidence": float,    # 0.0–1.0
        "indicators": {
            "yield_curve_spread": float | None,
            "vix": float | None,
            "cpi_yoy": float | None,
            "cpi_3m_delta": float | None,
            "fed_rate": float | None,
            "unemployment_delta": float | None,
            "pmi": float | None,
        },
        "scores": {             # individual contribution of each indicator
            "yield_curve": int,
            "vix": int,
            "cpi": int,
            "fed_rate": int,
            "unemployment": int,
            "pmi": int,
        },
        "description": str,     # human-readable explanation
    }
    """
    logger.info("[REGIME DETECTOR] Fetching indicators...")

    # Fetch all indicators
    spread                    = fetch_yield_curve()
    vix                       = fetch_vix()
    cpi_yoy,  cpi_delta       = fetch_cpi_trend()
    pce_yoy,  pce_delta       = fetch_pce_trend()
    fed_rate                  = fetch_fed_rate()
    unemployment, unemp_delta = fetch_unemployment_trend()
    pmi                       = fetch_pmi()

    # Score each indicator
    s_curve  = _score_yield_curve(spread)
    s_vix    = _score_vix(vix)
    s_cpi    = _score_cpi(cpi_yoy, cpi_delta)
    s_pce    = _score_pce(pce_yoy, pce_delta)       # Fed's preferred measure — higher weight
    s_fed    = _score_fed_rate(fed_rate, cpi_yoy)
    s_unemp  = _score_unemployment(unemp_delta)
    s_pmi    = _score_pmi(pmi)

    total_score = s_curve + s_vix + s_cpi + s_pce + s_fed + s_unemp + s_pmi

    # Determine regime
    if total_score >= INFLATION_SCORE_THRESHOLD:
        regime = "inflation_fight"
    elif total_score <= RECESSION_SCORE_THRESHOLD:
        regime = "recession_fear"
    else:
        regime = "neutral"

    # Confidence: how far the score is from the "other side"
    max_possible = 9   # theoretical max absolute score
    confidence = min(abs(total_score) / max_possible, 1.0)
    confidence = max(confidence, 0.3)   # floor at 30% — always some signal

    # Build description
    description = _build_description(
        regime, total_score, spread, vix, cpi_yoy, pce_yoy, fed_rate, unemp_delta, pmi
    )

    result = {
        "regime": regime,
        "score": total_score,
        "confidence": round(confidence, 3),
        "indicators": {
            "yield_curve_spread":  round(spread, 3)     if spread      is not None else None,
            "vix":                 round(vix, 2)         if vix         is not None else None,
            "cpi_yoy":             round(cpi_yoy, 2)     if cpi_yoy     is not None else None,
            "cpi_3m_delta":        round(cpi_delta, 3)   if cpi_delta   is not None else None,
            "pce_yoy":             round(pce_yoy, 2)     if pce_yoy     is not None else None,
            "pce_3m_delta":        round(pce_delta, 3)   if pce_delta   is not None else None,
            "fed_rate":            round(fed_rate, 2)    if fed_rate    is not None else None,
            "unemployment":        round(unemployment, 1) if unemployment is not None else None,
            "unemployment_delta":  round(unemp_delta, 2) if unemp_delta is not None else None,
            "pmi":                 round(pmi, 1)         if pmi         is not None else None,
        },
        "scores": {
            "yield_curve": s_curve,
            "vix":         s_vix,
            "cpi":         s_cpi,
            "pce":         s_pce,
            "fed_rate":    s_fed,
            "unemployment": s_unemp,
            "pmi":         s_pmi,
        },
        "description": description,
    }

    logger.info(f"[REGIME] {regime.upper()} (score={total_score:+d}, confidence={confidence:.0%})")
    logger.info(f"[REGIME] {description}")

    return result


def _build_description(
    regime: str, score: int,
    spread, vix, cpi_yoy, pce_yoy, fed_rate, unemp_delta, pmi
) -> str:
    """Build a human-readable regime description."""
    parts = []

    if regime == "inflation_fight":
        parts.append("Fed em modo restritivo — dados fortes = BEARISH para acções")
        if pce_yoy is not None and pce_yoy > PCE_ELEVATED_INFLATION:
            parts.append(f"Core PCE ≈ {pce_yoy:.1f}% (acima do objectivo de 2% da Fed)")
        elif cpi_yoy is not None and cpi_yoy > CPI_ELEVATED_INFLATION:
            parts.append(f"CPI ≈ {cpi_yoy:.1f}% (inflação elevada)")
        if fed_rate is not None and fed_rate > FED_RATE_HIGH:
            parts.append(f"Taxa Fed a {fed_rate:.2f}% (território restritivo)")
    elif regime == "recession_fear":
        parts.append("Mercado receia abrandamento — dados fracos = BEARISH, fortes = BULLISH")
        if spread is not None and spread < YIELD_CURVE_INVERSION_MILD:
            parts.append(f"Curva de yields invertida ({spread:+.2f}pp)")
        if vix is not None and vix > VIX_ELEVATED:
            parts.append(f"VIX elevado ({vix:.1f}) — maior aversão ao risco")
        if unemp_delta is not None and unemp_delta > UNEMPLOYMENT_RISE_MILD:
            parts.append(f"Desemprego em alta ({unemp_delta:+.2f}pp nos últimos 3 meses)")
        if pce_yoy is not None and pce_yoy < PCE_BELOW_TARGET:
            parts.append(f"Core PCE {pce_yoy:.1f}% — abaixo do objectivo, Fed tem margem para cortar")
    else:
        parts.append("Sinais mistos — interpretação standard dos dados macro")
        if pce_yoy is not None:
            parts.append(f"Core PCE {pce_yoy:.1f}% (próximo do objectivo de 2%)")

    if pmi is not None:
        status = "em expansão" if pmi > 50 else "em contracção"
        parts.append(f"PMI {pmi:.1f} ({status})")

    return " | ".join(parts)
