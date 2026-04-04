"""
Main entry point for Financial Market Bias Analyzer
Run this script to analyze current market bias for NY opening session
"""

import os
import sys
import shutil
import tempfile

# ---------------------------------------------------------------------------
# SSL FIX — must run before any network library is imported.
# curl_cffi (used internally by yfinance) fails to read the certifi CA bundle
# when the venv path contains non-ASCII characters (e.g. "Área de Trabalho").
# We copy the bundle to a plain ASCII temp path and point curl_cffi there.
# ---------------------------------------------------------------------------
try:
    import certifi as _certifi
    _cert_src = _certifi.where()
    if any(ord(c) > 127 for c in _cert_src):
        _cert_dst = os.path.join(tempfile.gettempdir(), "bias_analyzer_cacert.pem")
        if not os.path.exists(_cert_dst):
            shutil.copy2(_cert_src, _cert_dst)
        os.environ.setdefault("CURL_CA_BUNDLE", _cert_dst)
        os.environ.setdefault("SSL_CERT_FILE", _cert_dst)
        os.environ.setdefault("REQUESTS_CA_BUNDLE", _cert_dst)
except Exception:
    pass  # certifi not installed — network calls may fail with SSL errors

import time
from datetime import datetime, timezone
import schedule

# Add src to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from src.utils import logger, format_bias_report, format_json_report, save_json_report
from src.bias_engine import calculate_ny_bias, validate_report
from src.config import OUTPUT_JSON, OUTPUT_CONSOLE, UPDATE_INTERVAL_SECONDS, USE_MOCK_DATA

def run_analysis():
    """Execute single market analysis cycle"""
    try:
        logger.info("\n" + "=" * 70)
        logger.info(f"ANALYSIS RUN: {datetime.now(timezone.utc).isoformat()}")
        logger.info("=" * 70)
        
        # Calculate bias
        report = calculate_ny_bias()
        
        # Validate
        if not validate_report(report):
            logger.error("Invalid report structure, aborting output")
            return
        
        # Output to console
        if OUTPUT_CONSOLE:
            console_output = format_bias_report(report)
            print(console_output)
        
        # Output to JSON file
        if OUTPUT_JSON:
            save_json_report(report, OUTPUT_JSON)
        
        logger.info("Analysis complete.")
        
    except Exception as e:
        logger.error(f"Error during analysis: {e}", exc_info=True)

def schedule_updates():
    """Schedule periodic market analysis"""
    
    logger.info(f"Scheduling updates every {UPDATE_INTERVAL_SECONDS} seconds")
    
    # Schedule job
    schedule.every(UPDATE_INTERVAL_SECONDS).seconds.do(run_analysis)
    
    # Keep scheduler running
    while True:
        schedule.run_pending()
        time.sleep(30)  # Check schedule every 30 seconds

def main():
    """Main entry point"""
    
    print("\n" + "=" * 70)
    print("  FINANCIAL MARKET BIAS ANALYZER - NY SESSION")
    print("  MVP v0.1.0")
    print("=" * 70 + "\n")
    
    # Check API keys
    from dotenv import load_dotenv
    load_dotenv()
    
    from src.config import FRED_API_KEY
    
    if not FRED_API_KEY or FRED_API_KEY == "your_fred_api_key_here":
        logger.warning("FRED API key not configured. Some features will be limited.")
        logger.warning("  1. Register free: https://fred.stlouisfed.org/docs/api/")
        logger.warning("  2. Add key to .env file: FRED_API_KEY=your_key")
    
    logger.info("Using FREE Forex Factory for economic calendar (no API key needed)")
    
    print("\nStarting analysis...\n")
    
    # Run single analysis or continuous scheduling
    if len(sys.argv) > 1 and sys.argv[1] == "--schedule":
        # Continuous mode (--schedule flag)
        logger.info("Running in SCHEDULED mode (updates every 15 minutes)")
        schedule_updates()
    else:
        # Single run mode (default)
        logger.info("Running in SINGLE ANALYSIS mode")
        run_analysis()
        
        print("\n" + "=" * 70)
        print("  ANALYSIS COMPLETE!")
        print("=" * 70)
        print("\nTo run continuos updates every 15 minutes:")
        print("  python main.py --schedule")
        print("\nTo schedule automatic runs (Windows):")
        print("  1. Open Task Scheduler")
        print("  2. Create Basic Task")
        print("  3. Set trigger (daily at 06:00 AM NY time)")
        print("  4. Action: Start program")
        print(f"  5. Program: python.exe")
        print(f"  6. Arguments: '{os.path.abspath(__file__)}'")
        print("=" * 70 + "\n")

if __name__ == "__main__":
    main()
