# Financial Market Bias Analyzer

A Python application that analyzes the **Bullish/Bearish bias** for the New York stock market opening session, based on:
- Asian market close (Tokyo)
- London market close (London)
- Macroeconomic events and calendar

## Features

✅ **Real-time market analysis** using yfinance (9 key assets)  
✅ **Candlestick pattern detection** (Bullish/Bearish Engulfing, Hammer, Doji)  
✅ **Macroeconomic calendar** integration (NFP, CPI, PMI, etc.)  
✅ **Multi-timezone support** (Asia → London → NY)  
✅ **Confidence-based signals** (85% threshold for valid signal)  
✅ **JSON + Console output** (machine-readable + human-readable)  
✅ **100% Free** (uses open-source APIs)

## Monitored Assets

| Category | Assets |
|----------|--------|
| **US Indices** | SPY (S&P 500), QQQ (NASDAQ), DIA (Dow Jones) |
| **Forex** | EUR/USD, GBP/USD |
| **Commodities** | Gold (XAU/USD), US Dollar Index (DXY) |
| **Crypto** | Bitcoin (BTC-USD) |
| **Bonds** | US Treasury 10Y Yield (^TNX) |

## Setup

### 1. Create Virtual Environment

```bash
python -m venv .venv

# Windows
.venv\Scripts\activate

# macOS/Linux
source .venv/bin/activate
```

### 2. Install Dependencies

```bash
pip install -r requirements.txt
```

### 3. Configure API Keys

Create a `.env` file (copy from `.env.template`):

```bash
cp .env.template .env
```

Edit `.env` and add your free API keys:

**FRED API** (Federal Reserve Economic Data):
1. Register free: https://fred.stlouisfed.org/docs/api/
2. Add key to `.env`: `FRED_API_KEY=your_key_here`

**Trading Economics API**:
1. Register free: https://tradingeconomics.com/
2. Add key to `.env`: `TRADING_ECONOMICS_KEY=your_key_here`

## Usage

### Single Analysis Run

```bash
python main.py
```

Analyzes current market state once and outputs:
- Console report (human-readable)
- JSON file (`output/bias_report.json`)

### Continuous Updates (Every 15 minutes)

```bash
python main.py --schedule
```

Keeps running, updates market analysis every 15 minutes.

### Automatic Windows Scheduling

To run analysis automatically at 6:00 AM NY time daily:

1. Open **Task Scheduler** (Windows)
2. **Create Basic Task**
3. **Trigger**: Daily, 6:00 AM
4. **Action**: Start program
5. **Program**: `python.exe`
6. **Arguments**: `C:\full\path\to\main.py`

## Output Format

### Console Output

```
==================================================
    MARKET BIAS REPORT - NY OPENING SESSION
==================================================

Time (UTC): 2026-04-02T12:30:00Z
Time (NY): 2026-04-02 08:30:00 EDT

----- ASIA SESSION -----
Overall Bias: BULLISH (75% confidence)
Key Pattern: Bullish Engulfing

Asset Breakdown:
  SPY        → BULLISH  (pattern: bullish_engulfing)
  QQQ        → BULLISH  (pattern: hammer)
  DIA        → NEUTRAL  (pattern: doji)

... (London, Macro sections)

==================================================
         FINAL NY SESSION BIAS
==================================================

SIGNAL: ✓ BULLISH
Confidence: 72%
Valid Signal: NO (threshold: 85%)

Key Drivers:
  • Asia: Bullish close (75%) — Positive momentum into London
  • London: Bearish pressure (65%) — Risk-off into NY
  • Macro: Dovish/Positive setup (60%) — Economic optimism
  • Combined: Mixed signals — use caution for directional trades

==================================================
```

### JSON Output (`output/bias_report.json`)

```json
{
  "timestamp": "2026-04-02T12:30:00Z",
  "asia_session": {
    "overall_bias": "BULLISH",
    "confidence": 0.75,
    "dominant_pattern": "Bullish Engulfing",
    "assets": {
      "SPY": {
        "name": "S&P 500",
        "bias": "BULLISH",
        "pattern": "Bullish Engulfing",
        "confidence": 0.75,
        "last_close": 150.25
      },
      ...
    }
  },
  "ny_bias": {
    "signal": "BULLISH",
    "confidence": 0.72,
    "is_valid_signal": false,
    "key_drivers": [...]
  }
}
```

## Configuration

Edit `src/config.py` to customize:

- **CONFIDENCE_THRESHOLD**: Minimum confidence for valid signal (default: 85%)
- **SESSION_WEIGHTS**: How much each session influences NY bias (A 30%, L 40%, M 30%)
- **MACRO_EVENT_WEIGHTS**: How much each economic indicator weighs (NFP 45%, CPI 30%, etc.)
- **UPDATE_INTERVAL_SECONDS**: How often to refresh in scheduled mode (default: 900s = 15min)

## Candlestick Patterns

The analyzer detects:

| Pattern | Signal | Strength |
|---------|--------|----------|
| **Bullish Engulfing** | BULLISH | 75% confidence |
| **Bearish Engulfing** | BEARISH | 75% confidence |
| **Hammer** | BULLISH | 65% confidence |
| **Shooting Star** | BEARISH | 65% confidence |
| **Doji** | NEUTRAL | 50% confidence |
| **Bullish Candle** | BULLISH | 40% confidence |
| **Bearish Candle** | BEARISH | 40% confidence |

## Bias Calculation

Final NY Bias = (Asia Bias × 30%) + (London Bias × 40%) + (Macro Sentiment × 30%)

Each component is scored from -1 (Bearish) to +1 (Bullish), then combined with weights.

## Macroeconomic Indicators (via FRED + Trading Economics)

**Weighted by impact:**
- NFP (Non-Farm Payroll): 45%
- CPI (Consumer Price Index): 20%
- PCE (Personal Consumption): 10%
- PMI (Manufacturing): 10%
- Jobless Claims: 8%
- Other (PPI, GDP, etc.): 7%

## Architecture

```
Bot_Financeiro/
├── src/
│   ├── __init__.py           # Package init
│   ├── config.py             # Configuration (assets, API keys, thresholds)
│   ├── market_analyzer.py    # Candlestick pattern detection + OHLC fetch
│   ├── macro_calendar.py     # FRED + Trading Economics integration
│   ├── bias_engine.py        # Core decision logic
│   └── utils.py              # Helpers (logging, formatting, timezone)
├── output/
│   ├── bias_report.json      # Auto-generated report
│   └── logs/
│       └── bias_analyzer.log # Log file
├── main.py                   # Entry point
├── requirements.txt          # Python dependencies
├── .env                      # API keys (user-created)
├── .env.template             # API key template
└── README.md                 # This file
```

## Troubleshooting

### How to enable detailed logging?

Edit `src/config.py`:
```python
LOG_LEVEL = "DEBUG"  # More verbose
VERBOSE = True
```

### No data for a specific asset?

Check:
1. Ticker symbol is correct in `config.py`
2. Market data is available (yfinance limitation)
3. Check logs: `output/logs/bias_analyzer.log`

### API key errors?

1. Verify `.env` file exists in project root
2. Check keys are correct (no extra spaces)
3. Restart Python (pick up new .env)

## Notes

- **Data latency**: yfinance data is ~15-20 minutes delayed (free limitation)
- **MVP Scope**: Candlestick patterns only (no RSI/MACD indicators yet)
- **Real-time upgrade**: Requires paid APIs (Alpha Vantage Premium, IEX Cloud, etc.)

## Future Enhancements

- [ ] RSI, MACD, Moving Averages indicators
- [ ] WebSocket real-time data (paid APIs)
- [ ] Dashboard UI (web-based)
- [ ] Push notifications (email, Telegram, Discord)
- [ ] Database persistence (PostgreSQL)
- [ ] Machine learning sentiment analysis
- [ ] Backtesting engine
- [ ] Risk management alerts

## License

This project is free and open source.

## Support

For issues, questions, or suggestions, review the logs:
```bash
cat output/logs/bias_analyzer.log
```

---

**Happy trading! 📈**
