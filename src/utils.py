"""
Utility functions for logging, formatting, timezone handling, and data validation
"""

import logging
import json
import os
from datetime import datetime
import pytz
from typing import Dict, Any
from src.config import LOG_FILE, LOG_LEVEL, TIMEZONES

# ============================================================================
# LOGGING SETUP
# ============================================================================
def setup_logger():
    """Initialize logger for the application"""
    logger = logging.getLogger("BiasAnalyzer")
    logger.setLevel(getattr(logging, LOG_LEVEL))

    # Ensure log directory exists before creating file handler
    log_dir = os.path.dirname(LOG_FILE)
    if log_dir:
        os.makedirs(log_dir, exist_ok=True)

    # File handler
    file_handler = logging.FileHandler(LOG_FILE)
    file_handler.setLevel(logging.DEBUG)
    
    # Console handler
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    
    # Formatter
    formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    file_handler.setFormatter(formatter)
    console_handler.setFormatter(formatter)
    
    # Add handlers
    if not logger.handlers:  # Avoid duplicate handlers
        logger.addHandler(file_handler)
        logger.addHandler(console_handler)
    
    return logger

logger = setup_logger()

# ============================================================================
# TIMEZONE CONVERSION
# ============================================================================
def get_current_time_in_zone(zone: str) -> datetime:
    """Get current time in specified timezone"""
    tz = pytz.timezone(TIMEZONES.get(zone, "UTC"))
    return datetime.now(tz)

def convert_timezone(dt: datetime, from_zone: str, to_zone: str) -> datetime:
    """Convert datetime from one timezone to another"""
    from_tz = pytz.timezone(TIMEZONES.get(from_zone, "UTC"))
    to_tz = pytz.timezone(TIMEZONES.get(to_zone, "UTC"))
    
    if dt.tzinfo is None:
        dt = from_tz.localize(dt)
    return dt.astimezone(to_tz)

# ============================================================================
# DATA FORMATTING
# ============================================================================
def format_bias_report(report: Dict[str, Any]) -> str:
    """Format bias report as human-readable console output"""
    
    output = "\n"
    output += "=" * 50 + "\n"
    output += "    MARKET BIAS REPORT - NY OPENING SESSION\n"
    output += "=" * 50 + "\n\n"
    
    # Timestamp
    timestamp = report.get("timestamp", "N/A")
    output += f"Time (UTC): {timestamp}\n"
    output += f"Time (NY): {get_current_time_in_zone('ny').strftime('%Y-%m-%d %H:%M:%S %Z')}\n\n"
    
    # Asia Session
    asia = report.get("asia_session", {})
    output += "----- ASIA SESSION -----\n"
    output += f"Overall Bias: {asia.get('overall_bias', 'N/A')} "
    output += f"({asia.get('confidence', 0):.1%} confidence)\n"
    output += f"Key Pattern: {asia.get('dominant_pattern', 'N/A')}\n"
    
    if "assets" in asia:
        output += "\nAsset Breakdown:\n"
        for asset, data in asia["assets"].items():
            output += f"  {asset:10} | {data.get('bias', 'N/A'):8} | pattern: {data.get('pattern', 'N/A')}\n"
    output += "\n"
    
    # London Session
    london = report.get("london_session", {})
    output += "----- LONDON SESSION -----\n"
    output += f"Overall Bias: {london.get('overall_bias', 'N/A')} "
    output += f"({london.get('confidence', 0):.1%} confidence)\n"
    output += f"Key Pattern: {london.get('dominant_pattern', 'N/A')}\n"
    
    if "assets" in london:
        output += "\nAsset Breakdown:\n"
        for asset, data in london["assets"].items():
            output += f"  {asset:10} | {data.get('bias', 'N/A'):8} | pattern: {data.get('pattern', 'N/A')}\n"
    output += "\n"
    
    # Macro Events
    macro = report.get("macro_sentiment", {})
    output += "----- MACRO EVENTS (Next 7 Days) -----\n"
    output += f"Sentiment: {macro.get('sentiment', 'N/A')} ({macro.get('confidence', 0):.1%} confidence)\n"
    upcoming = macro.get("upcoming_events", [])
    if upcoming:
        for event in upcoming[:5]:  # Top 5 events
            output += f"  {event.get('event', 'N/A'):40} | {event.get('date', 'N/A')} | "
            output += f"Forecast: {event.get('forecast', 'N/A')} | Impact: {event.get('impact', 'N/A')}\n"
    else:
        output += "  (No upcoming events data)\n"
    output += "\n"
    
    # Final NY Bias
    ny_bias = report.get("ny_bias", {})
    output += "=" * 50 + "\n"
    output += "         FINAL NY SESSION BIAS\n"
    output += "=" * 50 + "\n\n"
    
    signal = ny_bias.get("signal", "NEUTRAL")
    confidence = ny_bias.get("confidence", 0)
    
    # Signal display (ASCII-safe for Windows)
    if signal == "BULLISH":
        signal_display = f"[BULLISH] {signal}"
    elif signal == "BEARISH":
        signal_display = f"[BEARISH] {signal}"
    else:
        signal_display = f"[NEUTRAL] {signal}"
    
    output += f"SIGNAL: {signal_display}\n"
    output += f"Confidence: {confidence:.1%}\n"
    is_valid = confidence >= 0.85
    output += f"Valid Signal: {'YES' if is_valid else 'NO'} (threshold: 85%)\n\n"
    
    # Key Drivers
    output += "Key Drivers:\n"
    for driver in ny_bias.get("key_drivers", []):
        output += f"  {driver}\n"
    
    output += "\n"
    output += "=" * 50 + "\n\n"
    
    return output

def format_json_report(report: Dict[str, Any]) -> str:
    """Convert report to JSON string"""
    return json.dumps(report, indent=2, default=str)

# ============================================================================
# ERROR HANDLING & VALIDATION
# ============================================================================
def validate_ohlc_data(data: Dict[str, Any]) -> bool:
    """Validate OHLC data completeness"""
    required_fields = ['open', 'high', 'low', 'close']
    return all(field in data for field in required_fields) and all(data.values())

def safe_divide(numerator: float, denominator: float, default: float = 0.0) -> float:
    """Safe division handling zero denominator"""
    try:
        if denominator == 0:
            return default
        return numerator / denominator
    except (TypeError, ValueError):
        return default

# ============================================================================
# DATA PERSISTENCE
# ============================================================================
def save_json_report(report: Dict[str, Any], filepath: str):
    """Save report to JSON file"""
    try:
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(report, f, indent=2, default=str)
        logger.info(f"Report saved to {filepath}")
    except Exception as e:
        logger.error(f"Error saving report: {e}")

def load_json_report(filepath: str) -> Dict[str, Any]:
    """Load report from JSON file"""
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"Error loading report: {e}")
        return {}

# ============================================================================
# DEBUGGING
# ============================================================================
def log_debug_info(title: str, data: Dict[str, Any]):
    """Log debug information"""
    if logger.level == logging.DEBUG:
        logger.debug(f"\n--- {title} ---")
        logger.debug(json.dumps(data, indent=2, default=str))
