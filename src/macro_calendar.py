"""
Macro Calendar Module
Fetches upcoming economic events from Finnhub (real data) and historical
indicators from FRED (Federal Reserve).

Data sources:
- Finnhub Economic Calendar API (free tier) — upcoming events with real
  forecasts and previous values.
- FRED API (free) — latest historical indicator values.

If FINNHUB_API_KEY is not configured, the module falls back to hardcoded
placeholder values and logs a clear warning.
"""

import requests
from typing import Dict, List, Optional, Tuple
from datetime import datetime, timedelta, timezone
from src.config import FRED_API_KEY, FINNHUB_API_KEY
from src.utils import logger

# US high-impact event keywords used for filtering Finnhub results
_KEY_EVENTS = ["Nonfarm", "NFP", "Payroll", "CPI", "PCE", "PMI", "ISM",
               "Jobless", "Claims", "PPI", "GDP", "Retail Sales", "FOMC",
               "Federal Reserve", "Unemployment"]


# ============================================================================
# FRED — historical indicators
# ============================================================================

def fetch_fred_indicator(series_id: str, limit: int = 1) -> Optional[Dict]:
    """Fetch latest value for a FRED series."""
    if not FRED_API_KEY:
        logger.debug("FRED API key not configured.")
        return None

    try:
        url = "https://api.stlouisfed.org/fred/series/observations"
        params = {
            "series_id": series_id,
            "api_key": FRED_API_KEY,
            "limit": limit,
            "sort_order": "desc",
        }
        response = requests.get(url, params=params, timeout=10)
        response.raise_for_status()
        data = response.json()

        if "observations" in data and data["observations"]:
            latest = data["observations"][0]
            return {
                "series_id": series_id,
                "date": latest.get("date"),
                "value": latest.get("value"),
            }
    except Exception as e:
        logger.debug(f"Error fetching FRED {series_id}: {e}")

    return None


def fetch_macro_events_from_fred() -> Dict[str, Dict]:
    """Fetch latest macroeconomic indicators from FRED."""
    fred_indicators = {
        "NFP": "PAYEMS",
        "UNEMPLOYMENT": "UNRATE",
        "CPI": "CPIAUCSL",
        "PCE": "PCEPILFE",
        "JOBLESS_CLAIMS": "ICSA",
        "ISM_PMI": "MMNRNJ",
        "RETAIL_SALES": "RSXFS",
    }

    macro_data = {}
    for name, series_id in fred_indicators.items():
        indicator = fetch_fred_indicator(series_id)
        if indicator:
            macro_data[name] = indicator
            logger.info(f"FRED {name}: {indicator.get('value')} ({indicator.get('date')})")

    return macro_data


# ============================================================================
# FINNHUB — upcoming economic calendar (real forecasts)
# ============================================================================

def fetch_finnhub_calendar(days_ahead: int = 14) -> List[Dict]:
    """
    Fetch upcoming US economic events from Finnhub Economic Calendar API.
    NOTE: This endpoint requires a Finnhub *premium* plan.
          Returns an empty list on 403 so the caller falls back to ForexFactory.
    """
    if not FINNHUB_API_KEY:
        return []

    from_date = datetime.now().strftime("%Y-%m-%d")
    to_date = (datetime.now() + timedelta(days=days_ahead)).strftime("%Y-%m-%d")

    try:
        url = "https://finnhub.io/api/v1/calendar/economic"
        params = {"from": from_date, "to": to_date, "token": FINNHUB_API_KEY}
        response = requests.get(url, params=params, timeout=10)

        if response.status_code == 403:
            logger.warning(
                "Finnhub returned 403 — the economic calendar endpoint requires a "
                "premium plan. Falling back to ForexFactory JSON."
            )
            return []

        response.raise_for_status()
        data = response.json()
        raw_events = data.get("economicCalendar", [])

        impact_map = {"high": "High", "medium": "Medium", "low": "Low"}
        events = []
        for ev in raw_events:
            if ev.get("country") != "US":
                continue
            event_name = ev.get("event", "")
            if not any(kw.lower() in event_name.lower() for kw in _KEY_EVENTS):
                continue

            unit = ev.get("unit", "")

            def fmt(val):
                return f"{val}{' ' + unit if unit else ''}" if val is not None else "N/A"

            events.append({
                "event": event_name,
                "date": ev.get("time", "N/A"),
                "time": "N/A",
                "forecast": fmt(ev.get("estimate")),
                "previous": fmt(ev.get("prev")),
                "actual": fmt(ev.get("actual")),
                "impact": impact_map.get(str(ev.get("impact", "")).lower(), "Unknown"),
                "country": "US",
            })

        logger.info(f"Finnhub: {len(events)} US events ({from_date} → {to_date})")
        return events

    except Exception as e:
        logger.error(f"Error fetching Finnhub calendar: {e}")
        return []


def fetch_forexfactory_json() -> List[Dict]:
    """
    Fetch this week's and next week's economic events from the ForexFactory
    community JSON feed (no API key required).

    Feed URL: https://nfs.faireconomy.media/ff_calendar_thisweek.json
    Response fields: title, country, date, impact, forecast, previous, actual
    """
    events = []
    urls = [
        "https://nfs.faireconomy.media/ff_calendar_thisweek.json",
        "https://nfs.faireconomy.media/ff_calendar_nextweek.json",
    ]

    for url in urls:
        try:
            response = requests.get(url, timeout=10,
                                    headers={"User-Agent": "Mozilla/5.0"})
            response.raise_for_status()
            raw = response.json()

            for ev in raw:
                if ev.get("country", "").upper() not in ("USD", "US"):
                    continue
                event_name = ev.get("title", "")
                if not any(kw.lower() in event_name.lower() for kw in _KEY_EVENTS):
                    continue

                # Parse ISO date string
                date_str = ev.get("date", "")
                try:
                    date_parsed = datetime.fromisoformat(date_str)
                    date_out = date_parsed.strftime("%Y-%m-%d")
                    time_out = date_parsed.strftime("%H:%M GMT")
                except (ValueError, TypeError):
                    date_out = date_str
                    time_out = "N/A"

                impact_raw = ev.get("impact", "").capitalize()

                # Skip events that already happened
                try:
                    if date_parsed.date() < datetime.now().date():
                        continue
                except Exception:
                    pass

                events.append({
                    "event": event_name,
                    "date": date_out,
                    "time": time_out,
                    "forecast": ev.get("forecast") or "N/A",
                    "previous": ev.get("previous") or "N/A",
                    "actual": ev.get("actual") or "N/A",
                    "impact": impact_raw if impact_raw else "Unknown",
                    "country": "US",
                })

        except Exception as e:
            logger.warning(f"ForexFactory JSON ({url}): {e}")

    if events:
        logger.info(f"ForexFactory JSON: {len(events)} US key events loaded (real data)")
    else:
        logger.warning("ForexFactory JSON returned no events.")

    return events


def _fallback_mock_calendar() -> List[Dict]:
    """
    Hardcoded placeholder events used only when Finnhub API key is absent.
    Values are ILLUSTRATIVE — do not use for real trading decisions.
    """
    reason = (
        "Finnhub endpoint requires a premium plan and ForexFactory returned no upcoming events"
        if FINNHUB_API_KEY
        else "FINNHUB_API_KEY not configured and ForexFactory returned no upcoming events"
    )
    logger.warning(
        f"MACRO CALENDAR: {reason}. Using hardcoded placeholder values."
    )
    today = datetime.now()
    return [
        {
            "event": "Nonfarm Payrolls (placeholder)",
            "date": (today + timedelta(days=1)).strftime("%Y-%m-%d"),
            "time": "13:30 GMT",
            "forecast": "200 K",
            "previous": "180 K",
            "actual": "N/A",
            "impact": "High",
            "country": "US",
        },
        {
            "event": "Initial Jobless Claims (placeholder)",
            "date": (today + timedelta(days=2)).strftime("%Y-%m-%d"),
            "time": "13:30 GMT",
            "forecast": "215 K",
            "previous": "220 K",
            "actual": "N/A",
            "impact": "Medium",
            "country": "US",
        },
        {
            "event": "ISM Manufacturing PMI (placeholder)",
            "date": (today + timedelta(days=3)).strftime("%Y-%m-%d"),
            "time": "15:00 GMT",
            "forecast": "49.5",
            "previous": "49.2",
            "actual": "N/A",
            "impact": "Medium",
            "country": "US",
        },
        {
            "event": "CPI (placeholder)",
            "date": (today + timedelta(days=8)).strftime("%Y-%m-%d"),
            "time": "13:30 GMT",
            "forecast": "2.1 %",
            "previous": "2.4 %",
            "actual": "N/A",
            "impact": "High",
            "country": "US",
        },
        {
            "event": "PCE (placeholder)",
            "date": (today + timedelta(days=10)).strftime("%Y-%m-%d"),
            "time": "13:30 GMT",
            "forecast": "2.0 %",
            "previous": "2.1 %",
            "actual": "N/A",
            "impact": "High",
            "country": "US",
        },
    ]


# ============================================================================
# PUBLIC API
# ============================================================================

def fetch_macro_calendar() -> Dict:
    """
    Fetch complete macro calendar.

    1. Tries Finnhub for upcoming events (real forecasts & previous values).
    2. Falls back to placeholder data if Finnhub key is not configured.
    3. Also pulls latest historical indicators from FRED (independent of Finnhub).
    """
    use_finnhub = bool(FINNHUB_API_KEY)

    calendar = {
        "fetch_timestamp": datetime.now(timezone.utc).isoformat(),
        "recent_economic_data": {},
        "upcoming_events": [],
        "data_sources": [],
        "using_real_calendar": use_finnhub,
    }

    # Historical data from FRED
    if FRED_API_KEY:
        logger.info("Fetching FRED economic indicators...")
        calendar["recent_economic_data"] = fetch_macro_events_from_fred()
        calendar["data_sources"].append("FRED (Federal Reserve)")

    # Upcoming events priority: Finnhub (premium) → ForexFactory JSON (free) → placeholder
    upcoming = []
    if use_finnhub:
        logger.info("Fetching Finnhub economic calendar...")
        upcoming = fetch_finnhub_calendar()
        if upcoming:
            calendar["data_sources"].append("Finnhub Economic Calendar")

    if not upcoming:
        logger.info("Fetching ForexFactory JSON calendar (free, no API key)...")
        upcoming = fetch_forexfactory_json()
        if upcoming:
            calendar["data_sources"].append("ForexFactory JSON Feed")

    if not upcoming:
        upcoming = _fallback_mock_calendar()
        calendar["data_sources"].append("Hardcoded placeholder (ForexFactory and Finnhub unavailable)")

    # Normalise and store
    key_events = ["Nonfarm", "NFP", "Payroll", "CPI", "PCE", "PMI", "ISM",
                  "Jobless", "Claims", "PPI", "GDP", "Retail", "FOMC",
                  "Federal Reserve", "Unemployment"]

    for event in upcoming:
        event_name = event.get("event", "")
        if any(kw.lower() in event_name.lower() for kw in key_events):
            calendar["upcoming_events"].append({
                "event": event_name,
                "date": event.get("date", "N/A"),
                "time": event.get("time", "N/A"),
                "forecast": event.get("forecast", "N/A"),
                "previous": event.get("previous", "N/A"),
                "actual": event.get("actual", "N/A"),
                "impact": event.get("impact", "Unknown"),
                "country": event.get("country", "US"),
            })
            logger.info(
                f"Event: {event_name} | {event.get('date')} | "
                f"Forecast: {event.get('forecast')} | Impact: {event.get('impact')}"
            )

    return calendar


# ============================================================================
# REGIME-AWARE MACRO INTERPRETATION
# ============================================================================

# How to interpret "hot" (forecast > previous) data per event type and regime.
# +1 = BULLISH for stocks, -1 = BEARISH for stocks
_REGIME_INTERPRETATION = {
    # NFP / Nonfarm Payrolls
    "NFP": {
        "inflation_fight": {"hot": -1, "cool": +1},  # hot = more hikes → bearish
        "recession_fear":  {"hot": +1, "cool": -1},  # hot = economy ok → bullish
        "neutral":         {"hot": +1, "cool": -1},
    },
    # CPI / Inflation
    "CPI": {
        "inflation_fight": {"hot": -1, "cool": +1},
        "recession_fear":  {"hot": -1, "cool": +1},  # still bad either way
        "neutral":         {"hot": -1, "cool": +1},
    },
    # PCE
    "PCE": {
        "inflation_fight": {"hot": -1, "cool": +1},
        "recession_fear":  {"hot": -1, "cool": +1},
        "neutral":         {"hot": -1, "cool": +1},
    },
    # PMI / ISM
    "PMI": {
        "inflation_fight": {"hot": -1, "cool": +1},  # hot PMI = more inflation pressure
        "recession_fear":  {"hot": +1, "cool": -1},  # hot PMI = economy not crashing
        "neutral":         {"hot": +1, "cool": -1},
    },
    # Jobless Claims (inverted: MORE claims = labour weakness)
    "JOBLESS": {
        "inflation_fight": {"hot": +1, "cool": -1},  # more claims = softer labour → bullish (less hikes)
        "recession_fear":  {"hot": -1, "cool": +1},  # more claims = recession worsening
        "neutral":         {"hot": -1, "cool": +1},
    },
    # Default for unknown events
    "OTHER": {
        "inflation_fight": {"hot": -1, "cool": +1},
        "recession_fear":  {"hot": +1, "cool": -1},
        "neutral":         {"hot": +1, "cool": -1},
    },
}


def _classify_event(event_name: str) -> str:
    """Map event name to an interpretation category."""
    name = event_name.lower()
    if any(k in name for k in ("payroll", "nfp", "nonfarm")):
        return "NFP"
    if "cpi" in name:
        return "CPI"
    if "pce" in name:
        return "PCE"
    if any(k in name for k in ("pmi", "ism")):
        return "PMI"
    if any(k in name for k in ("jobless", "claims", "unemployment")):
        return "JOBLESS"
    return "OTHER"


def _parse_numeric(value) -> Optional[float]:
    """Parse forecast/previous string to float, or return None."""
    if value in (None, "N/A", "N/D", ""):
        return None
    try:
        cleaned = (str(value)
                   .replace(',', '').replace('%', '')
                   .replace('k', '000').replace('K', '000')
                   .strip())
        return float(cleaned)
    except (ValueError, TypeError):
        return None


def _event_is_hot(event_name: str, forecast, previous) -> Optional[bool]:
    """
    Returns True if data is 'hot' (better/higher than expected in growth terms),
    False if 'cool', None if cannot determine.
    For jobless claims, HIGHER = worse (so hot means MORE claims).
    """
    f_val = _parse_numeric(forecast)
    p_val = _parse_numeric(previous)
    if f_val is None or p_val is None:
        return None
    category = _classify_event(event_name)
    # Jobless claims: higher = worse labour market = "hot" in the sense of "bad"
    # For consistency the interpretation table already handles the direction correctly.
    return f_val > p_val


# ============================================================================
# SENTIMENT CALCULATION (regime-aware)
# ============================================================================

def calculate_macro_sentiment(
    calendar: Dict,
    weights: Dict[str, float],
    regime: str = "neutral",
) -> Tuple[str, float]:
    """
    Calculate macro bias from upcoming events using regime-aware weighted scoring.

    Args:
        calendar: Output of fetch_macro_calendar()
        weights:  MACRO_EVENT_WEIGHTS from config
        regime:   Current market regime ("inflation_fight", "recession_fear", "neutral")

    For each event:
      - Determines if the data is "hot" (forecast > previous) or "cool"
      - Applies the regime-specific directional signal from _REGIME_INTERPRETATION
      - Weights the signal by the event's importance

    Returns: (sentiment, confidence)
    """
    sentiment_score = 0.0
    total_weight = 0.0

    upcoming_events = calendar.get("upcoming_events", [])

    if not upcoming_events:
        return ("NEUTRAL", 0.5)

    for event in upcoming_events:
        event_name = event.get("event", "")
        forecast   = event.get("forecast", "N/A")
        previous   = event.get("previous", "N/A")
        actual     = event.get("actual", "N/A")

        # Prefer actual over forecast when available
        compare_val = actual if actual not in ("N/A", "N/D", None, "") else forecast

        is_hot = _event_is_hot(event_name, compare_val, previous)
        if is_hot is None:
            continue   # cannot interpret this event

        category = _classify_event(event_name)
        regime_key = regime if regime in ("inflation_fight", "recession_fear") else "neutral"
        interp = _REGIME_INTERPRETATION.get(category, _REGIME_INTERPRETATION["OTHER"])
        direction = interp[regime_key]["hot" if is_hot else "cool"]

        # Event weight
        name_lower = event_name.lower()
        if any(k in name_lower for k in ("payroll", "nfp", "nonfarm")):
            event_weight = weights.get("NFP", 0.45)
        elif "cpi" in name_lower:
            event_weight = weights.get("CPI", 0.20)
        elif "pce" in name_lower:
            event_weight = weights.get("PCE", 0.10)
        elif any(k in name_lower for k in ("pmi", "ism")):
            event_weight = weights.get("PMI", 0.10)
        elif any(k in name_lower for k in ("jobless", "claims")):
            event_weight = weights.get("jobless_claims", 0.08)
        else:
            event_weight = weights.get("other", 0.07)

        sentiment_score += direction * event_weight
        total_weight += event_weight

        hot_str = "quente" if is_hot else "frio"
        logger.debug(
            f"  [{category}] {event_name[:40]} → {hot_str} → "
            f"{'BULLISH' if direction > 0 else 'BEARISH'} "
            f"(regime={regime_key}, weight={event_weight})"
        )

    if total_weight > 0:
        sentiment_score = sentiment_score / total_weight

    if sentiment_score > 0.2:
        sentiment = "BULLISH"
        confidence = min(abs(sentiment_score), 1.0)
    elif sentiment_score < -0.2:
        sentiment = "BEARISH"
        confidence = min(abs(sentiment_score), 1.0)
    else:
        sentiment = "NEUTRAL"
        confidence = 0.5

    return (sentiment, confidence)
