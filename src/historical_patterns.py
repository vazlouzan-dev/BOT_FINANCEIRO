"""
Historical Patterns Module
Builds and queries a database of how SPY/QQQ historically reacted to each
macro event (NFP, CPI, PCE, PMI, Jobless Claims, GDP, FOMC) filtered by the
market regime at the time.

Provides a "historical base rate" to complement the current bias:
  "In similar past conditions, market was BEARISH 65% of the time (n=20)"

Data sources (all free):
  - FRED API: macro event values, CPI history, yield curve (T10Y2Y)
  - yfinance: SPY/QQQ daily OHLC (open ≈ 9:30 reaction start)

Database: output/patterns.db (SQLite, rebuilt weekly)

Event coverage:
  1. NFP           — Non-Farm Payrolls     (monthly,    PAYEMS)
  2. CPI           — Consumer Price Index  (monthly,    CPIAUCSL)
  3. Core PCE      — Fed inflation target  (monthly,    PCEPILFE)
  4. PMI/ISM       — Manufacturing PMI     (monthly,    MMNRNJ)
  5. Jobless Claims— Weekly unemployment   (weekly,     ICSA)
  6. GDP           — Real GDP growth       (quarterly,  A191RL1Q225SBEA)
  7. FOMC          — Fed rate decisions    (8x/year,    DFF — detect changes)
"""

import sqlite3
import os
import time
import requests
import pandas as pd
import yfinance as yf
from datetime import datetime, timezone, timedelta, date
from typing import Dict, List, Optional, Tuple
from pathlib import Path

from src.utils import logger
from src.config import FRED_API_KEY

# ============================================================================
# PATHS & CONSTANTS
# ============================================================================
_PROJECT_ROOT      = Path(__file__).resolve().parent.parent
PATTERNS_DB_PATH   = str(_PROJECT_ROOT / "output" / "patterns.db")
LOOKBACK_YEARS     = 5
HISTORY_REFRESH_DAYS = 7    # rebuild if DB is older than 7 days
MIN_SAMPLES        = 5      # minimum events to report a base rate

DIRECTION_THRESHOLD = 0.001  # 0.1% move = directional (else NEUTRAL)

# ============================================================================
# EVENT REGISTRY
# Each event: FRED series, estimated release offset (calendar days from
# observation date to market-moving release date), frequency, weight.
# ============================================================================
EVENTS: Dict[str, Dict] = {
    "NFP": {
        "series":       "PAYEMS",
        "offset_days":  35,      # ~5 weeks after reference month
        "freq":         "M",
        "weight":       0.45,
        "label":        "Non-Farm Payrolls",
        "hot_means":    "employment strong",
    },
    "CPI": {
        "series":       "CPIAUCSL",
        "offset_days":  14,      # ~2 weeks after reference month
        "freq":         "M",
        "weight":       0.20,
        "label":        "CPI",
        "hot_means":    "inflation rising",
    },
    "PCE": {
        "series":       "PCEPILFE",
        "offset_days":  28,      # ~4 weeks after reference month
        "freq":         "M",
        "weight":       0.10,
        "label":        "Core PCE",
        "hot_means":    "inflation rising (Fed target)",
    },
    "PMI": {
        "series":       "MMNRNJ",
        "offset_days":  2,       # first business day of next month
        "freq":         "M",
        "weight":       0.10,
        "label":        "ISM Manufacturing PMI",
        "hot_means":    "expansion accelerating",
    },
    "JOBLESS": {
        "series":       "ICSA",
        "offset_days":  6,       # released Thursday of following week
        "freq":         "W",
        "weight":       0.08,
        "label":        "Jobless Claims",
        "hot_means":    "MORE claims (labour weakening)",
    },
    "GDP": {
        "series":       "A191RL1Q225SBEA",
        "offset_days":  28,      # advance estimate ~4 weeks after quarter end
        "freq":         "Q",
        "weight":       0.07,
        "label":        "GDP (Real, QoQ %)",
        "hot_means":    "growth accelerating",
    },
    "FOMC": {
        "series":       "DFF",   # daily fed funds rate — detect day of change
        "offset_days":  -1,      # rate effective day AFTER meeting: subtract 1
        "freq":         "FOMC",  # special handling
        "weight":       0.20,
        "label":        "FOMC Rate Decision",
        "hot_means":    "rate HIKE (hawkish)",
    },
}


# ============================================================================
# FRED HELPERS
# ============================================================================

def _fred_get(series_id: str, start_date: str, end_date: str = None) -> List[Dict]:
    """
    Fetch all observations for a FRED series within a date range.
    Returns list of {'date': 'YYYY-MM-DD', 'value': float}.
    Skips observations with missing values ('.').
    """
    if not FRED_API_KEY:
        return []

    params = {
        "series_id":         series_id,
        "api_key":           FRED_API_KEY,
        "observation_start": start_date,
        "file_type":         "json",
    }
    if end_date:
        params["observation_end"] = end_date

    try:
        resp = requests.get(
            "https://api.stlouisfed.org/fred/series/observations",
            params=params, timeout=15,
        )
        resp.raise_for_status()
        result = []
        for o in resp.json().get("observations", []):
            try:
                result.append({"date": o["date"], "value": float(o["value"])})
            except (ValueError, TypeError):
                pass   # skip '.' missing values
        return result
    except Exception as e:
        logger.warning(f"FRED fetch failed [{series_id}]: {e}")
        return []


def _fred_latest(series_id: str) -> Optional[float]:
    """Return the single most-recent observation value."""
    obs = _fred_get(series_id, "2020-01-01")
    return obs[-1]["value"] if obs else None


# ============================================================================
# OHLC HELPERS
# ============================================================================

def _build_ohlc_lookup(ticker: str, start: str, end: str) -> Dict[str, Dict]:
    """
    Returns dict keyed by 'YYYY-MM-DD': {'open': float, 'close': float}.
    Fetches daily OHLC for the full date range in one call (efficient).
    """
    try:
        df = yf.download(ticker, start=start, end=end, interval="1d",
                         progress=False, auto_adjust=True)
        if df.empty:
            return {}
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        result = {}
        for idx, row in df.iterrows():
            d = idx.strftime("%Y-%m-%d") if hasattr(idx, "strftime") else str(idx)[:10]
            result[d] = {"open": float(row["Open"]), "close": float(row["Close"])}
        return result
    except Exception as e:
        logger.warning(f"OHLC lookup failed for {ticker}: {e}")
        return {}


def _nearest_trading_day(target_date: str, ohlc_lookup: Dict) -> Optional[str]:
    """
    Find the nearest trading day at or after target_date that exists in ohlc_lookup.
    Searches up to 7 days forward (to skip weekends/holidays).
    """
    d = datetime.strptime(target_date, "%Y-%m-%d").date()
    for offset in range(8):
        candidate = (d + timedelta(days=offset)).strftime("%Y-%m-%d")
        if candidate in ohlc_lookup:
            return candidate
    return None


def _market_direction(open_price: float, close_price: float) -> str:
    """Classify daily SPY direction: BULLISH / BEARISH / NEUTRAL."""
    if open_price <= 0:
        return "NEUTRAL"
    ret = (close_price - open_price) / open_price
    if ret > DIRECTION_THRESHOLD:
        return "BULLISH"
    elif ret < -DIRECTION_THRESHOLD:
        return "BEARISH"
    return "NEUTRAL"


# ============================================================================
# HISTORICAL REGIME CLASSIFICATION
# ============================================================================

def _build_regime_lookup(start: str, end: str) -> Dict[str, str]:
    """
    Build a date → regime mapping using:
      - T10Y2Y: daily 10Y-2Y Treasury spread (FRED)
      - CPIAUCSL: monthly CPI for YoY inflation calculation

    Regime rules (simplified, consistent with regime_detector.py):
      CPI YoY > 3.5%  AND  spread >= -0.3  → inflation_fight
      spread < -0.3   OR   CPI YoY < 2.0   → recession_fear
      else                                  → neutral
    """
    logger.info("  [HISTORY] Building regime lookup (T10Y2Y + CPI)...")

    spread_obs = _fred_get("T10Y2Y", start, end)
    cpi_obs    = _fred_get("CPIAUCSL", start, end)

    # Yield curve: daily dict
    spread_by_date = {o["date"]: o["value"] for o in spread_obs}

    # CPI YoY: requires 12 previous observations
    # Fetch 14 months of CPI to ensure we have prior year
    extra_start = (datetime.strptime(start, "%Y-%m-%d") - timedelta(days=400)).strftime("%Y-%m-%d")
    cpi_all = _fred_get("CPIAUCSL", extra_start, end)
    cpi_yoy_by_date: Dict[str, float] = {}
    for i, obs in enumerate(cpi_all):
        if i >= 12:
            try:
                yoy = ((obs["value"] - cpi_all[i - 12]["value"]) / cpi_all[i - 12]["value"]) * 100
                cpi_yoy_by_date[obs["date"]] = round(yoy, 2)
            except (ZeroDivisionError, TypeError):
                pass

    # Build daily lookup via sorted lists for binary-search-style lookups
    sorted_spread = sorted(spread_by_date.keys())
    sorted_cpi    = sorted(cpi_yoy_by_date.keys())

    def _latest_before(sorted_keys, d_str, lookup):
        """Return value from lookup for the latest key <= d_str."""
        result = None
        for k in sorted_keys:
            if k <= d_str:
                result = lookup.get(k)
            else:
                break
        return result

    # Generate for every calendar day in range
    start_dt = datetime.strptime(start, "%Y-%m-%d").date()
    end_dt   = datetime.strptime(end, "%Y-%m-%d").date()
    regime_lookup: Dict[str, str] = {}

    current = start_dt
    while current <= end_dt:
        d_str  = current.strftime("%Y-%m-%d")
        spread = _latest_before(sorted_spread, d_str, spread_by_date)
        cpi_yoy = _latest_before(sorted_cpi, d_str, cpi_yoy_by_date)
        regime_lookup[d_str] = _classify_regime(cpi_yoy, spread)
        current += timedelta(days=1)

    return regime_lookup


def _classify_regime(cpi_yoy: Optional[float], spread: Optional[float]) -> str:
    """Classify regime from CPI YoY and yield curve spread."""
    if cpi_yoy is not None and cpi_yoy > 3.5 and (spread is None or spread >= -0.3):
        return "inflation_fight"
    if (spread is not None and spread < -0.3) or (cpi_yoy is not None and cpi_yoy < 2.0):
        return "recession_fear"
    return "neutral"


# ============================================================================
# DATABASE
# ============================================================================

def _get_conn() -> sqlite3.Connection:
    os.makedirs(os.path.dirname(PATTERNS_DB_PATH), exist_ok=True)
    conn = sqlite3.connect(PATTERNS_DB_PATH)
    conn.row_factory = sqlite3.Row
    _init_db(conn)
    return conn


def _init_db(conn: sqlite3.Connection) -> None:
    conn.execute("""
        CREATE TABLE IF NOT EXISTS historical_events (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            event_type      TEXT NOT NULL,
            event_date      TEXT NOT NULL,
            obs_value       REAL,
            prior_value     REAL,
            is_hot          INTEGER,      -- 1=hot, 0=cool, NULL=fomc_hold
            fomc_action     TEXT,         -- 'hike'|'cut'|'hold' (FOMC only)
            regime          TEXT,
            spy_open        REAL,
            spy_close       REAL,
            spy_return_pct  REAL,
            spy_direction   TEXT,
            qqq_open        REAL,
            qqq_close       REAL,
            qqq_return_pct  REAL,
            qqq_direction   TEXT,
            built_at        TEXT,
            UNIQUE(event_type, event_date)
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS build_log (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            built_at   TEXT NOT NULL,
            n_events   INTEGER,
            status     TEXT
        )
    """)
    conn.commit()


def _db_needs_rebuild() -> bool:
    """Returns True if the DB doesn't exist or was built > HISTORY_REFRESH_DAYS ago."""
    if not os.path.exists(PATTERNS_DB_PATH):
        return True
    try:
        conn = _get_conn()
        row = conn.execute(
            "SELECT built_at FROM build_log ORDER BY id DESC LIMIT 1"
        ).fetchone()
        conn.close()
        if not row:
            return True
        last = datetime.fromisoformat(row["built_at"])
        age  = (datetime.now(timezone.utc) - last).days
        return age >= HISTORY_REFRESH_DAYS
    except Exception:
        return True


# ============================================================================
# BUILD HISTORY
# ============================================================================

def build_history(force: bool = False) -> int:
    """
    Fetch historical data and populate patterns.db.

    Args:
        force: If True, rebuild even if DB is recent.

    Returns:
        Number of events stored.
    """
    if not FRED_API_KEY:
        logger.warning(
            "[HISTORY] FRED_API_KEY not configured — "
            "historical patterns require FRED access. Skipping."
        )
        return 0

    if not force and not _db_needs_rebuild():
        conn = _get_conn()
        n = conn.execute("SELECT COUNT(*) FROM historical_events").fetchone()[0]
        conn.close()
        logger.info(f"[HISTORY] DB is recent — {n} events cached. Use force=True to rebuild.")
        return n

    logger.info(f"[HISTORY] Building {LOOKBACK_YEARS}-year historical pattern database...")
    start_str = (datetime.now() - timedelta(days=LOOKBACK_YEARS * 365)).strftime("%Y-%m-%d")
    end_str   = datetime.now().strftime("%Y-%m-%d")

    # ── 1. OHLC for SPY and QQQ (single call each) ─────────────────────
    logger.info("  [HISTORY] Downloading SPY and QQQ OHLC history...")
    spy_ohlc = _build_ohlc_lookup("SPY", start_str, end_str)
    time.sleep(0.5)
    qqq_ohlc = _build_ohlc_lookup("QQQ", start_str, end_str)
    logger.info(f"  [HISTORY] SPY: {len(spy_ohlc)} days | QQQ: {len(qqq_ohlc)} days")

    # ── 2. Regime lookup ────────────────────────────────────────────────
    regime_lookup = _build_regime_lookup(start_str, end_str)
    logger.info(f"  [HISTORY] Regime lookup built for {len(regime_lookup)} days")

    # ── 3. Process each event type ──────────────────────────────────────
    conn    = _get_conn()
    n_total = 0

    for event_type, cfg in EVENTS.items():
        logger.info(f"  [HISTORY] Processing {event_type} ({cfg['label']})...")
        time.sleep(0.3)   # rate limit FRED

        if event_type == "FOMC":
            n = _process_fomc(conn, spy_ohlc, qqq_ohlc, regime_lookup, start_str, end_str)
        else:
            n = _process_standard_event(
                conn, event_type, cfg, spy_ohlc, qqq_ohlc, regime_lookup, start_str, end_str
            )

        logger.info(f"  [HISTORY] {event_type}: {n} events stored")
        n_total += n

    # ── 4. Log build ────────────────────────────────────────────────────
    conn.execute(
        "INSERT INTO build_log (built_at, n_events, status) VALUES (?, ?, ?)",
        (datetime.now(timezone.utc).isoformat(), n_total, "ok"),
    )
    conn.commit()
    conn.close()

    logger.info(f"[HISTORY] Build complete — {n_total} total events in patterns.db")
    return n_total


def _process_standard_event(
    conn, event_type, cfg, spy_ohlc, qqq_ohlc, regime_lookup,
    start_str, end_str
) -> int:
    """Process one standard FRED indicator (non-FOMC)."""
    obs = _fred_get(cfg["series"], start_str, end_str)
    if len(obs) < 2:
        return 0

    n = 0
    for i in range(1, len(obs)):
        curr = obs[i]
        prev = obs[i - 1]

        # Approximate release date
        obs_date    = datetime.strptime(curr["date"], "%Y-%m-%d").date()
        release_date = (obs_date + timedelta(days=cfg["offset_days"])).strftime("%Y-%m-%d")

        # Skip future dates
        if release_date > end_str:
            continue

        # Find nearest trading day
        trading_day = _nearest_trading_day(release_date, spy_ohlc)
        if not trading_day:
            continue

        spy  = spy_ohlc.get(trading_day, {})
        qqq  = qqq_ohlc.get(trading_day, {})
        if not spy or not qqq:
            continue

        # Hot/cool: for JOBLESS, more claims = WORSE (inverted)
        is_hot = int(curr["value"] > prev["value"])
        # Note: hot_means for JOBLESS = "more claims" which is actually bad,
        # but we store raw direction and let interpretation matrix handle it.

        spy_ret = ((spy["close"] - spy["open"]) / spy["open"]) * 100 if spy["open"] else None
        qqq_ret = ((qqq["close"] - qqq["open"]) / qqq["open"]) * 100 if qqq["open"] else None

        regime = regime_lookup.get(trading_day, "neutral")

        try:
            conn.execute("""
                INSERT OR REPLACE INTO historical_events
                  (event_type, event_date, obs_value, prior_value, is_hot,
                   regime, spy_open, spy_close, spy_return_pct, spy_direction,
                   qqq_open, qqq_close, qqq_return_pct, qqq_direction, built_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """, (
                event_type, trading_day,
                round(curr["value"], 4), round(prev["value"], 4), is_hot,
                regime,
                round(spy["open"], 4), round(spy["close"], 4),
                round(spy_ret, 4) if spy_ret is not None else None,
                _market_direction(spy["open"], spy["close"]),
                round(qqq["open"], 4), round(qqq["close"], 4),
                round(qqq_ret, 4) if qqq_ret is not None else None,
                _market_direction(qqq["open"], qqq["close"]),
                datetime.now(timezone.utc).isoformat(),
            ))
            n += 1
        except sqlite3.IntegrityError:
            pass   # duplicate — skip

    conn.commit()
    return n


def _process_fomc(conn, spy_ohlc, qqq_ohlc, regime_lookup, start_str, end_str) -> int:
    """
    Detect FOMC decision days from DFF (daily fed funds rate).
    A change in DFF = rate decision effective date (day AFTER meeting).
    We look at the prior day (actual meeting/announcement day).
    """
    dff_obs = _fred_get("DFF", start_str, end_str)
    if len(dff_obs) < 2:
        return 0

    n = 0
    for i in range(1, len(dff_obs)):
        prev_rate = dff_obs[i - 1]["value"]
        curr_rate = dff_obs[i]["value"]

        if prev_rate == curr_rate:
            continue   # no change = no FOMC decision (or on-hold)

        effective_date = dff_obs[i]["date"]  # DFF change date
        # Meeting day = 1 calendar day before effective date
        meeting_day_dt = datetime.strptime(effective_date, "%Y-%m-%d").date() - timedelta(days=1)
        meeting_day    = meeting_day_dt.strftime("%Y-%m-%d")

        if meeting_day < start_str or meeting_day > end_str:
            continue

        trading_day = _nearest_trading_day(meeting_day, spy_ohlc)
        if not trading_day:
            # Try effective date itself
            trading_day = _nearest_trading_day(effective_date, spy_ohlc)
        if not trading_day:
            continue

        spy = spy_ohlc.get(trading_day, {})
        qqq = qqq_ohlc.get(trading_day, {})
        if not spy or not qqq:
            continue

        fomc_action = "hike" if curr_rate > prev_rate else "cut"
        is_hot      = 1 if fomc_action == "hike" else 0

        spy_ret = ((spy["close"] - spy["open"]) / spy["open"]) * 100 if spy["open"] else None
        qqq_ret = ((qqq["close"] - qqq["open"]) / qqq["open"]) * 100 if qqq["open"] else None

        regime = regime_lookup.get(trading_day, "neutral")

        try:
            conn.execute("""
                INSERT OR REPLACE INTO historical_events
                  (event_type, event_date, obs_value, prior_value, is_hot, fomc_action,
                   regime, spy_open, spy_close, spy_return_pct, spy_direction,
                   qqq_open, qqq_close, qqq_return_pct, qqq_direction, built_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """, (
                "FOMC", trading_day,
                round(curr_rate, 4), round(prev_rate, 4), is_hot, fomc_action,
                regime,
                round(spy["open"], 4), round(spy["close"], 4),
                round(spy_ret, 4) if spy_ret is not None else None,
                _market_direction(spy["open"], spy["close"]),
                round(qqq["open"], 4), round(qqq["close"], 4),
                round(qqq_ret, 4) if qqq_ret is not None else None,
                _market_direction(qqq["open"], qqq["close"]),
                datetime.now(timezone.utc).isoformat(),
            ))
            n += 1
        except sqlite3.IntegrityError:
            pass

    conn.commit()
    return n


# ============================================================================
# QUERY — BASE RATE
# ============================================================================

def get_base_rate(
    event_type: str,
    is_hot: Optional[bool],
    regime: str,
    min_samples: int = MIN_SAMPLES,
) -> Optional[Dict]:
    """
    Query the historical base rate for a given event + condition + regime.

    Args:
        event_type:  "NFP", "CPI", "PCE", "PMI", "JOBLESS", "GDP", "FOMC"
        is_hot:      True = hot/hawkish, False = cool/dovish, None = any
        regime:      "inflation_fight" | "recession_fear" | "neutral"
        min_samples: Minimum events required to return a result.

    Returns dict or None:
    {
        "event_type":     "NFP",
        "is_hot":         True,
        "regime":         "neutral",
        "n_samples":      18,
        "bullish_pct":    0.56,
        "bearish_pct":    0.33,
        "neutral_pct":    0.11,
        "dominant_dir":   "BULLISH",
        "confidence":     0.56,        # = dominant_pct
        "avg_spy_return": 0.42,        # avg % move on event days
    }
    """
    if not os.path.exists(PATTERNS_DB_PATH):
        return None

    try:
        conn = _get_conn()

        query = """
            SELECT spy_direction, spy_return_pct
            FROM historical_events
            WHERE event_type = ?
              AND regime = ?
              AND spy_direction IS NOT NULL
        """
        params = [event_type, regime]

        if is_hot is not None:
            query  += " AND is_hot = ?"
            params.append(1 if is_hot else 0)

        rows = conn.execute(query, params).fetchall()
        conn.close()

        if len(rows) < min_samples:
            return None

        directions  = [r["spy_direction"] for r in rows]
        returns     = [r["spy_return_pct"] for r in rows if r["spy_return_pct"] is not None]
        n           = len(directions)

        bullish_n = directions.count("BULLISH")
        bearish_n = directions.count("BEARISH")
        neutral_n = directions.count("NEUTRAL")

        bullish_pct = bullish_n / n
        bearish_pct = bearish_n / n
        neutral_pct = neutral_n / n

        dominant = max(
            [("BULLISH", bullish_pct), ("BEARISH", bearish_pct), ("NEUTRAL", neutral_pct)],
            key=lambda x: x[1],
        )

        return {
            "event_type":     event_type,
            "is_hot":         is_hot,
            "regime":         regime,
            "n_samples":      n,
            "bullish_pct":    round(bullish_pct, 3),
            "bearish_pct":    round(bearish_pct, 3),
            "neutral_pct":    round(neutral_pct, 3),
            "dominant_dir":   dominant[0],
            "confidence":     round(dominant[1], 3),
            "avg_spy_return": round(sum(returns) / len(returns), 3) if returns else None,
        }

    except Exception as e:
        logger.warning(f"[HISTORY] Base rate query failed: {e}")
        return None


# ============================================================================
# AGGREGATE — HISTORICAL CONTEXT FOR TODAY
# ============================================================================

def get_historical_context(
    regime: str,
    macro_events: List[Dict],
) -> Dict:
    """
    Calculate overall historical context for today's macro conditions.

    Args:
        regime:        Current market regime string.
        macro_events:  List of event dicts from macro_calendar (with forecast/previous/actual).

    Returns:
    {
        "available":        True,
        "overall_bias":     "BEARISH",
        "overall_conf":     0.62,
        "total_samples":    55,
        "per_event":        [...],
        "db_has_data":      True,
    }
    """
    if not os.path.exists(PATTERNS_DB_PATH):
        return {"available": False, "db_has_data": False, "per_event": []}

    from src.macro_calendar import _parse_numeric, _classify_event

    per_event  = []
    total_score  = 0.0
    total_weight = 0.0
    total_samples = 0

    for ev in macro_events:
        event_name = ev.get("event", "")
        actual     = ev.get("actual", "N/A")
        forecast   = ev.get("forecast", "N/A")
        previous   = ev.get("previous", "N/A")

        compare = actual if actual not in ("N/A", "N/D", None, "") else forecast
        prev_val = _parse_numeric(previous)
        comp_val = _parse_numeric(compare)

        if comp_val is None or prev_val is None:
            continue

        is_hot    = comp_val > prev_val
        category  = _classify_event(event_name)

        # Map macro_calendar category to EVENTS key
        cat_to_event = {
            "NFP":    "NFP",
            "CPI":    "CPI",
            "PCE":    "PCE",
            "PMI":    "PMI",
            "JOBLESS":"JOBLESS",
        }
        event_key = cat_to_event.get(category)
        if not event_key:
            continue

        base = get_base_rate(event_key, is_hot, regime)
        if base is None:
            continue

        # Weight by event importance
        weight = EVENTS[event_key]["weight"]

        # Score: bullish dominant → positive, bearish → negative
        if base["dominant_dir"] == "BULLISH":
            score = base["confidence"]
        elif base["dominant_dir"] == "BEARISH":
            score = -base["confidence"]
        else:
            score = 0.0

        total_score  += score * weight
        total_weight += weight
        total_samples += base["n_samples"]

        per_event.append({
            "event_name":  event_name[:50],
            "event_key":   event_key,
            "is_hot":      is_hot,
            "hot_label":   "quente" if is_hot else "frio",
            "n_samples":   base["n_samples"],
            "bullish_pct": base["bullish_pct"],
            "bearish_pct": base["bearish_pct"],
            "dominant":    base["dominant_dir"],
            "confidence":  base["confidence"],
            "avg_spy_ret": base["avg_spy_return"],
            "regime":      regime,
            "weight":      weight,
        })

    # Also check FOMC if in upcoming events
    fomc_events = [e for e in macro_events if "fomc" in e.get("event","").lower()
                   or "federal reserve" in e.get("event","").lower()]
    if fomc_events:
        fomc_base = get_base_rate("FOMC", None, regime)
        if fomc_base:
            weight = EVENTS["FOMC"]["weight"]
            score  = fomc_base["confidence"] if fomc_base["dominant_dir"] == "BULLISH" else -fomc_base["confidence"] if fomc_base["dominant_dir"] == "BEARISH" else 0.0
            total_score  += score * weight
            total_weight += weight
            total_samples += fomc_base["n_samples"]
            per_event.append({
                "event_name":  "FOMC Meeting",
                "event_key":   "FOMC",
                "is_hot":      None,
                "hot_label":   "qualquer decisão",
                "n_samples":   fomc_base["n_samples"],
                "bullish_pct": fomc_base["bullish_pct"],
                "bearish_pct": fomc_base["bearish_pct"],
                "dominant":    fomc_base["dominant_dir"],
                "confidence":  fomc_base["confidence"],
                "avg_spy_ret": fomc_base["avg_spy_return"],
                "regime":      regime,
                "weight":      weight,
            })

    if not per_event or total_weight == 0:
        return {
            "available":    False,
            "db_has_data":  os.path.exists(PATTERNS_DB_PATH),
            "per_event":    [],
            "total_samples": 0,
        }

    norm_score = total_score / total_weight

    if norm_score > 0.15:
        overall_bias = "BULLISH"
        overall_conf = min(abs(norm_score), 1.0)
    elif norm_score < -0.15:
        overall_bias = "BEARISH"
        overall_conf = min(abs(norm_score), 1.0)
    else:
        overall_bias = "NEUTRAL"
        overall_conf = 0.5

    logger.info(
        f"[HISTORY] {overall_bias} ({overall_conf:.0%}) | "
        f"{len(per_event)} events | {total_samples} total samples"
    )

    return {
        "available":     True,
        "db_has_data":   True,
        "overall_bias":  overall_bias,
        "overall_conf":  round(overall_conf, 3),
        "raw_score":     round(norm_score, 3),
        "total_samples": total_samples,
        "per_event":     per_event,
        "regime":        regime,
    }


# ============================================================================
# DB STATS (for dashboard)
# ============================================================================

def get_db_stats() -> Dict:
    """Return summary statistics about the patterns database."""
    if not os.path.exists(PATTERNS_DB_PATH):
        return {"exists": False}

    try:
        conn = _get_conn()
        rows = conn.execute("""
            SELECT event_type,
                   COUNT(*) as n,
                   SUM(CASE WHEN spy_direction='BULLISH' THEN 1 ELSE 0 END) as bull,
                   SUM(CASE WHEN spy_direction='BEARISH' THEN 1 ELSE 0 END) as bear,
                   MIN(event_date) as oldest,
                   MAX(event_date) as newest
            FROM historical_events
            GROUP BY event_type
            ORDER BY event_type
        """).fetchall()

        log_row = conn.execute(
            "SELECT built_at FROM build_log ORDER BY id DESC LIMIT 1"
        ).fetchone()
        conn.close()

        by_event = []
        for r in rows:
            n = r["n"] or 0
            by_event.append({
                "event_type":  r["event_type"],
                "n":           n,
                "bull_pct":    round(r["bull"] / n, 2) if n else 0,
                "bear_pct":    round(r["bear"] / n, 2) if n else 0,
                "oldest":      r["oldest"],
                "newest":      r["newest"],
            })

        return {
            "exists":     True,
            "by_event":   by_event,
            "total":      sum(r["n"] for r in by_event),
            "built_at":   log_row["built_at"] if log_row else None,
        }
    except Exception as e:
        return {"exists": True, "error": str(e)}
