"""
Evaluator Module
Tracks bot predictions vs actual market outcomes using SQLite.

Schema:
  - Each analysis run is saved automatically with the predicted bias.
  - The user manually enters the actual result (BULLISH / BEARISH / NEUTRAL)
    via the Streamlit dashboard.
  - Accuracy statistics are calculated over time and filterable by regime.
"""

import sqlite3
import json
import os
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple
from pathlib import Path

# ── DB path (same output/ folder as bias_report.json) ─────────────────────
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
DB_PATH = str(_PROJECT_ROOT / "output" / "evaluations.db")

VALID_SIGNALS = ("BULLISH", "BEARISH", "NEUTRAL")


# ============================================================================
# DATABASE SETUP
# ============================================================================

def _get_conn() -> sqlite3.Connection:
    """Open (and if needed, initialise) the SQLite database."""
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    _init_db(conn)
    return conn


def _init_db(conn: sqlite3.Connection) -> None:
    """Create table if it does not exist."""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS evaluations (
            id               INTEGER PRIMARY KEY AUTOINCREMENT,
            session_date     TEXT NOT NULL,          -- "2026-04-05"
            session_window   TEXT NOT NULL DEFAULT '09:30-10:30 ET',
            predicted_bias   TEXT NOT NULL,          -- BULLISH / BEARISH / NEUTRAL
            predicted_conf   REAL NOT NULL,
            weighted_score   REAL,
            is_valid_signal  INTEGER NOT NULL DEFAULT 0,
            regime           TEXT,                   -- inflation_fight / recession_fear / neutral
            regime_score     INTEGER,
            key_events       TEXT,                   -- JSON list of macro event names
            actual_result    TEXT,                   -- filled manually; NULL until evaluated
            notes            TEXT,
            report_json      TEXT,                   -- full JSON snapshot of the report
            created_at       TEXT NOT NULL,
            evaluated_at     TEXT
        )
    """)
    conn.commit()


# ============================================================================
# SAVE PREDICTION
# ============================================================================

def save_prediction(report: Dict) -> int:
    """
    Persist a new analysis report to the evaluations table.

    Args:
        report: Output of bias_engine.calculate_ny_bias()

    Returns:
        The new row id.
    """
    ny_bias      = report.get("ny_bias", {})
    regime_data  = report.get("market_regime", {})
    macro        = report.get("macro_sentiment", {})

    # Extract key macro event names for quick reference
    events = [
        ev.get("event", "")
        for ev in macro.get("upcoming_events", [])[:5]
    ]

    # Session date from report timestamp (UTC)
    ts_raw = report.get("timestamp", datetime.now(timezone.utc).isoformat())
    try:
        ts_dt = datetime.fromisoformat(ts_raw)
        session_date = ts_dt.strftime("%Y-%m-%d")
    except Exception:
        session_date = datetime.now().strftime("%Y-%m-%d")

    conn = _get_conn()
    try:
        cursor = conn.execute("""
            INSERT INTO evaluations
                (session_date, predicted_bias, predicted_conf, weighted_score,
                 is_valid_signal, regime, regime_score, key_events,
                 report_json, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            session_date,
            ny_bias.get("signal", "NEUTRAL"),
            float(ny_bias.get("confidence", 0.0)),
            float(ny_bias.get("weighted_score", 0.0)),
            int(ny_bias.get("is_valid_signal", False)),
            regime_data.get("regime"),
            regime_data.get("score"),
            json.dumps(events, ensure_ascii=False),
            json.dumps(report, default=str, ensure_ascii=False),
            datetime.now(timezone.utc).isoformat(),
        ))
        conn.commit()
        row_id = cursor.lastrowid
    finally:
        conn.close()

    return row_id


# ============================================================================
# UPDATE ACTUAL RESULT
# ============================================================================

def set_actual_result(row_id: int, actual: str, notes: str = "") -> bool:
    """
    Record the real market outcome for a prediction row.

    Args:
        row_id: ID of the evaluation row to update.
        actual: "BULLISH", "BEARISH", or "NEUTRAL"
        notes:  Optional free-text commentary.

    Returns:
        True if the row was found and updated.
    """
    if actual not in VALID_SIGNALS:
        raise ValueError(f"actual must be one of {VALID_SIGNALS}, got '{actual}'")

    conn = _get_conn()
    try:
        cursor = conn.execute("""
            UPDATE evaluations
            SET actual_result = ?,
                notes         = ?,
                evaluated_at  = ?
            WHERE id = ?
        """, (actual, notes, datetime.now(timezone.utc).isoformat(), row_id))
        conn.commit()
        return cursor.rowcount > 0
    finally:
        conn.close()


# ============================================================================
# QUERY
# ============================================================================

def get_all_evaluations(limit: int = 200) -> List[Dict]:
    """Return all evaluation rows, newest first."""
    conn = _get_conn()
    try:
        rows = conn.execute("""
            SELECT id, session_date, session_window, predicted_bias, predicted_conf,
                   weighted_score, is_valid_signal, regime, regime_score,
                   key_events, actual_result, notes, created_at, evaluated_at
            FROM evaluations
            ORDER BY session_date DESC, created_at DESC
            LIMIT ?
        """, (limit,)).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_pending_evaluations() -> List[Dict]:
    """Return rows where actual_result has not yet been filled in."""
    conn = _get_conn()
    try:
        rows = conn.execute("""
            SELECT id, session_date, predicted_bias, predicted_conf,
                   regime, key_events, created_at
            FROM evaluations
            WHERE actual_result IS NULL
            ORDER BY session_date DESC
        """).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


# ============================================================================
# ACCURACY STATISTICS
# ============================================================================

def calculate_accuracy_stats(regime_filter: Optional[str] = None) -> Dict:
    """
    Calculate accuracy statistics over evaluated rows.

    Args:
        regime_filter: Optional — filter to "inflation_fight", "recession_fear", or "neutral".

    Returns:
    {
        "total_evaluated": int,
        "correct": int,
        "accuracy": float,          # 0.0–1.0
        "by_signal": {
            "BULLISH": {"correct": int, "total": int, "accuracy": float},
            "BEARISH": {...},
            "NEUTRAL": {...},
        },
        "by_regime": {
            "inflation_fight": {"correct": int, "total": int, "accuracy": float},
            ...
        },
        "valid_signals_only": {     # rows where is_valid_signal = 1
            "total": int,
            "correct": int,
            "accuracy": float,
        },
    }
    """
    conn = _get_conn()
    try:
        query = """
            SELECT predicted_bias, actual_result, is_valid_signal, regime
            FROM evaluations
            WHERE actual_result IS NOT NULL
        """
        params: list = []
        if regime_filter:
            query += " AND regime = ?"
            params.append(regime_filter)
        rows = conn.execute(query, params).fetchall()
    finally:
        conn.close()

    if not rows:
        return {
            "total_evaluated": 0,
            "correct": 0,
            "accuracy": 0.0,
            "by_signal": {},
            "by_regime": {},
            "valid_signals_only": {"total": 0, "correct": 0, "accuracy": 0.0},
        }

    total = len(rows)
    correct = sum(1 for r in rows if r["predicted_bias"] == r["actual_result"])

    # By predicted signal
    by_signal: Dict[str, Dict] = {}
    for sig in VALID_SIGNALS:
        sig_rows = [r for r in rows if r["predicted_bias"] == sig]
        sig_correct = sum(1 for r in sig_rows if r["actual_result"] == sig)
        by_signal[sig] = {
            "correct": sig_correct,
            "total": len(sig_rows),
            "accuracy": round(sig_correct / len(sig_rows), 3) if sig_rows else 0.0,
        }

    # By regime
    by_regime: Dict[str, Dict] = {}
    for reg in ("inflation_fight", "recession_fear", "neutral"):
        reg_rows = [r for r in rows if r["regime"] == reg]
        reg_correct = sum(1 for r in reg_rows if r["predicted_bias"] == r["actual_result"])
        if reg_rows:
            by_regime[reg] = {
                "correct": reg_correct,
                "total": len(reg_rows),
                "accuracy": round(reg_correct / len(reg_rows), 3),
            }

    # Valid signals only (high-confidence predictions)
    valid_rows = [r for r in rows if r["is_valid_signal"]]
    valid_correct = sum(1 for r in valid_rows if r["predicted_bias"] == r["actual_result"])

    return {
        "total_evaluated": total,
        "correct": correct,
        "accuracy": round(correct / total, 3) if total else 0.0,
        "by_signal": by_signal,
        "by_regime": by_regime,
        "valid_signals_only": {
            "total": len(valid_rows),
            "correct": valid_correct,
            "accuracy": round(valid_correct / len(valid_rows), 3) if valid_rows else 0.0,
        },
    }


def delete_evaluation(row_id: int) -> bool:
    """Delete an evaluation row (e.g., duplicate or erroneous run)."""
    conn = _get_conn()
    try:
        cursor = conn.execute("DELETE FROM evaluations WHERE id = ?", (row_id,))
        conn.commit()
        return cursor.rowcount > 0
    finally:
        conn.close()
