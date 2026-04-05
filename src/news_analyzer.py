"""
News Analyzer Module
Fetches and classifies recent news headlines for US equity indices
(SPY, QQQ) and the Magnificent 7, then applies regime-aware sentiment
scoring.

Data source: yfinance .news (free, no API key required)

Pipeline:
  1. Fetch headlines for SPY, QQQ + Mag7 (last 48h)
  2. Classify each headline by category (corporate, tariff, fed, geo, etc.)
  3. Apply regime filter → directional signal per headline
  4. Aggregate → overall news bias + impact level
  5. Return volatility expectation flag

Key principle:
  News and macro are always interlinked — the same headline means
  different things depending on the current regime.
  No significant news → lower volatility, macro dominates.
"""

import yfinance as yf
import time
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Tuple, Optional
from src.utils import logger

# ============================================================================
# TICKERS TO MONITOR
# ============================================================================
INDEX_TICKERS = ["SPY", "QQQ"]

MAG7_TICKERS = ["NVDA", "AAPL", "MSFT", "AMZN", "META", "GOOGL", "TSLA"]

# ============================================================================
# NEWS RECENCY WINDOW
# ============================================================================
NEWS_WINDOW_HOURS = 48   # only consider headlines from the last 48h

# ============================================================================
# KEYWORD CLASSIFICATION RULES
# Each category maps to a list of keyword triggers (lowercase).
# Order matters: more specific categories are checked first.
# ============================================================================

_KEYWORDS: Dict[str, List[str]] = {

    # ── Tarifas / Guerra Comercial ──────────────────────────────────────────
    "tariff": [
        "tariff", "tariffs", "trade war", "trade deal", "import tax",
        "export ban", "export control", "sanctions", "trade restriction",
        "trade policy", "trade dispute",
    ],

    # ── Fed / Política Monetária — Dovish (cortes, pausa) ──────────────────
    "fed_dovish": [
        "rate cut", "rate cuts", "cuts rates", "dovish", "pause rate",
        "hold rates", "easing", "quantitative easing", "qe", "pivot",
        "lower rates", "accommodative", "rate reduction", "no more hikes",
    ],

    # ── Fed / Política Monetária — Hawkish (subidas, aperto) ───────────────
    "fed_hawkish": [
        "rate hike", "rate hikes", "hikes rates", "hawkish",
        "higher for longer", "tightening", "more hikes", "raise rates",
        "restrictive", "inflation concern", "inflation risk",
    ],

    # ── Geopolítica / Risco Sistémico ───────────────────────────────────────
    "geopolitical": [
        "war", "conflict", "invasion", "attack", "missile", "military",
        "nato", "crisis", "sanctions on", "nuclear", "tension", "unrest",
        "coup", "shutdown", "debt ceiling", "default risk",
    ],

    # ── Notícia Corporativa Positiva ────────────────────────────────────────
    "corporate_positive": [
        "beat", "beats", "record", "record profit", "record revenue",
        "deal", "contract", "order", "orders", "partnership", "acquisition",
        "merger", "buyback", "dividend", "upgrade", "breakthrough",
        "launches", "wins contract", "exceeds", "surges", "jumps",
        "rally", "soars", "raises guidance", "above estimates",
        "strong earnings", "earnings beat", "revenue beat",
    ],

    # ── Notícia Corporativa Negativa ────────────────────────────────────────
    "corporate_negative": [
        "miss", "misses", "disappoints", "below estimates", "cuts guidance",
        "lowers guidance", "warning", "profit warning", "layoffs", "layoff",
        "job cuts", "recall", "investigation", "fine", "fined", "sued",
        "lawsuit", "downgrade", "slump", "falls", "drops", "crash",
        "concern", "risk", "weak earnings", "earnings miss", "revenue miss",
        "below expectations",
    ],

    # ── Política / Trump / Governo ──────────────────────────────────────────
    "political": [
        "trump", "executive order", "white house", "congress", "senate",
        "house passes", "regulation", "deregulation", "tax cut", "tax hike",
        "stimulus", "spending bill", "budget", "debt limit",
    ],
}

# ============================================================================
# REGIME-AWARE INTERPRETATION MATRIX
# For each news category: how does it affect US equity indices
# given the current macro regime?
# Values: +1 (bullish), -1 (bearish), 0 (neutral)
# ============================================================================

_REGIME_SIGNALS: Dict[str, Dict[str, int]] = {
    "tariff": {
        "inflation_fight": -1,   # tariffs = more inflation = more Fed hikes
        "recession_fear":  -1,   # tariffs = trade slowdown = recession worsens
        "neutral":         -1,   # almost always negative for indices
    },
    "fed_dovish": {
        "inflation_fight": +1,   # relief — Fed easing pressure
        "recession_fear":  +1,   # rate cuts coming to rescue economy
        "neutral":         +1,
    },
    "fed_hawkish": {
        "inflation_fight": -1,   # more hikes = more headwinds
        "recession_fear":   0,   # mixed: fighting inflation but hurting growth
        "neutral":         -1,
    },
    "geopolitical": {
        "inflation_fight": -1,   # risk-off + energy prices rise
        "recession_fear":  -1,   # uncertainty amplifies recession fears
        "neutral":         -1,
    },
    "corporate_positive": {
        "inflation_fight": +1,   # company strength outweighs macro concern
        "recession_fear":  +1,   # economy not as bad as feared
        "neutral":         +1,
    },
    "corporate_negative": {
        "inflation_fight": -1,
        "recession_fear":  -1,   # confirms slowdown narrative
        "neutral":         -1,
    },
    "political": {
        # Political news is ambiguous — classify as neutral unless
        # it clearly overlaps with tariff/fed categories above
        "inflation_fight":  0,
        "recession_fear":   0,
        "neutral":          0,
    },
}

# ============================================================================
# IMPACT WEIGHT PER CATEGORY
# How much does each category contribute to the overall score?
# ============================================================================

_CATEGORY_WEIGHT: Dict[str, float] = {
    "tariff":            1.5,   # high — directly hits indices
    "fed_dovish":        1.5,   # high — rate policy is paramount
    "fed_hawkish":       1.5,
    "geopolitical":      1.2,
    "corporate_positive": 1.0,
    "corporate_negative": 1.0,
    "political":         0.5,   # low — ambiguous
}

# ============================================================================
# HIGH-IMPACT KEYWORDS (bump to "high" impact level)
# ============================================================================

_HIGH_IMPACT_KEYWORDS = [
    "tariff", "rate cut", "rate hike", "fed ", "federal reserve",
    "earnings", "beat", "miss", "record", "deal", "acquisition",
    "trump", "war", "invasion", "default", "layoff", "recall",
    "nvidia", "nvda", "apple", "microsoft", "amazon", "meta",
    "alphabet", "tesla",
]

# ============================================================================
# FETCH NEWS
# ============================================================================

def _parse_news_item(item: dict, ticker: str) -> Optional[dict]:
    """
    Parse a single yfinance news item into a normalised dict.
    Handles both the legacy format (flat keys) and the current format
    where data lives under item['content'].
    """
    # Current yfinance format: item = {'id': ..., 'content': {...}}
    content = item.get("content") if isinstance(item.get("content"), dict) else item

    title = (content.get("title") or "").strip()
    if not title:
        return None

    # Publisher: nested under 'provider' or flat
    provider = content.get("provider") or {}
    publisher = (
        provider.get("displayName")
        or content.get("publisher")
        or ""
    )

    # Publication date
    pub_str = (
        content.get("pubDate")
        or content.get("displayTime")
        or ""
    )
    try:
        pub_dt = datetime.fromisoformat(pub_str.replace("Z", "+00:00"))
    except Exception:
        # Legacy: Unix timestamp
        pub_ts = item.get("providerPublishTime") or 0
        try:
            pub_dt = datetime.fromtimestamp(int(pub_ts), tz=timezone.utc)
        except Exception:
            pub_dt = datetime.now(timezone.utc)

    return {
        "title":        title,
        "publisher":    publisher,
        "published_at": pub_dt,
        "ticker":       ticker,
    }


def _fetch_ticker_news(ticker: str) -> List[Dict]:
    """
    Fetch recent news for a single ticker via yfinance.
    Returns list of dicts with 'title', 'publisher', 'published_at' (UTC datetime).
    Only includes news from the last NEWS_WINDOW_HOURS hours.
    """
    try:
        t = yf.Ticker(ticker)
        raw_news = t.news or []
        cutoff = datetime.now(timezone.utc) - timedelta(hours=NEWS_WINDOW_HOURS)
        result = []
        for item in raw_news:
            parsed = _parse_news_item(item, ticker)
            if parsed is None:
                continue
            if parsed["published_at"] < cutoff:
                continue
            result.append(parsed)
        return result
    except Exception as e:
        logger.warning(f"News fetch failed for {ticker}: {e}")
        return []


def fetch_all_news() -> List[Dict]:
    """
    Fetch deduplicated news for SPY, QQQ and all Mag7 tickers.
    Returns list sorted newest first, with duplicate titles removed.
    """
    all_tickers = INDEX_TICKERS + MAG7_TICKERS
    seen_titles = set()
    all_news = []

    for ticker in all_tickers:
        items = _fetch_ticker_news(ticker)
        for item in items:
            # Deduplicate by normalised title
            norm = item["title"].lower().strip()
            if norm not in seen_titles:
                seen_titles.add(norm)
                all_news.append(item)
        time.sleep(0.1)   # polite rate limiting

    all_news.sort(key=lambda x: x["published_at"], reverse=True)
    logger.info(f"[NEWS] Fetched {len(all_news)} unique headlines (last {NEWS_WINDOW_HOURS}h)")
    return all_news


# ============================================================================
# CLASSIFICATION
# ============================================================================

def _classify_headline(title: str) -> Optional[str]:
    """
    Classify a headline into one of the news categories.
    Returns category name or None if no match.
    Priority order follows _KEYWORDS dict order.
    """
    title_lower = title.lower()
    for category, keywords in _KEYWORDS.items():
        if any(kw in title_lower for kw in keywords):
            return category
    return None


def _is_high_impact(title: str) -> bool:
    """Returns True if the headline contains a high-impact keyword."""
    title_lower = title.lower()
    return any(kw in title_lower for kw in _HIGH_IMPACT_KEYWORDS)


# ============================================================================
# SENTIMENT SCORING
# ============================================================================

def calculate_news_sentiment(
    news_items: List[Dict],
    regime: str = "neutral",
) -> Dict:
    """
    Score news headlines and produce a regime-aware sentiment result.

    Args:
        news_items: Output of fetch_all_news()
        regime:     Current market regime string

    Returns:
    {
        "bias":             "BULLISH" | "BEARISH" | "NEUTRAL",
        "confidence":       float (0.0–1.0),
        "impact_level":     "high" | "medium" | "low" | "none",
        "volatility_flag":  "ALTA" | "MÉDIA" | "BAIXA" | "MUITO BAIXA",
        "scored_items":     [...],   # classified headlines with signal
        "total_headlines":  int,
        "high_impact_count": int,
    }
    """
    regime_key = regime if regime in ("inflation_fight", "recession_fear") else "neutral"

    scored = []
    total_score = 0.0
    total_weight = 0.0
    high_impact_count = 0

    for item in news_items:
        title    = item["title"]
        category = _classify_headline(title)
        if category is None:
            continue

        direction = _REGIME_SIGNALS[category].get(regime_key, 0)
        weight    = _CATEGORY_WEIGHT.get(category, 1.0)
        hi        = _is_high_impact(title)
        if hi:
            weight *= 1.5
            high_impact_count += 1

        total_score  += direction * weight
        total_weight += weight

        scored.append({
            "title":       title,
            "publisher":   item.get("publisher", ""),
            "published_at": item["published_at"].strftime("%Y-%m-%d %H:%M UTC"),
            "ticker":      item.get("ticker", ""),
            "category":    category,
            "signal":      "BULLISH" if direction > 0 else "BEARISH" if direction < 0 else "NEUTRAL",
            "high_impact": hi,
            "weight":      round(weight, 2),
        })

        logger.debug(
            f"  [{category}] {'⬆' if direction>0 else '⬇' if direction<0 else '●'} "
            f"({regime_key}) | {title[:60]}"
        )

    # Normalise score
    if total_weight > 0:
        norm_score = total_score / total_weight
    else:
        norm_score = 0.0

    # Bias signal
    if norm_score > 0.15:
        bias       = "BULLISH"
        confidence = min(abs(norm_score), 1.0)
    elif norm_score < -0.15:
        bias       = "BEARISH"
        confidence = min(abs(norm_score), 1.0)
    else:
        bias       = "NEUTRAL"
        confidence = 0.3

    # Impact level (drives dynamic weights in bias_engine)
    n_scored = len(scored)
    if high_impact_count >= 3 or (high_impact_count >= 1 and n_scored >= 5):
        impact_level = "high"
    elif high_impact_count >= 1 or n_scored >= 3:
        impact_level = "medium"
    elif n_scored >= 1:
        impact_level = "low"
    else:
        impact_level = "none"

    # Volatility expectation
    volatility_map = {
        "high":   "ALTA",
        "medium": "MÉDIA",
        "low":    "BAIXA",
        "none":   "MUITO BAIXA",
    }

    result = {
        "bias":              bias,
        "confidence":        round(confidence, 3),
        "raw_score":         round(norm_score, 3),
        "impact_level":      impact_level,
        "volatility_flag":   volatility_map[impact_level],
        "regime_applied":    regime_key,
        "scored_items":      scored[:20],   # top 20 for the report
        "total_headlines":   len(news_items),
        "classified_count":  n_scored,
        "high_impact_count": high_impact_count,
    }

    logger.info(
        f"[NEWS] {bias} ({confidence:.0%} conf) | "
        f"impact={impact_level} | volatilidade={volatility_map[impact_level]} | "
        f"{n_scored} classificadas ({high_impact_count} alto impacto)"
    )
    return result
