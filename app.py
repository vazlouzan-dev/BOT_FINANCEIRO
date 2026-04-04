"""
Financial Market Bias Analyzer — Streamlit Dashboard
Run locally:  streamlit run app.py
Deploy:       Streamlit Community Cloud (streamlit.io/cloud)
"""

import streamlit as st
import json
import os
import sys
import subprocess
from datetime import datetime
import pytz

# ── Page config ──────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="NY Market Bias Analyzer",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# ── Constants ─────────────────────────────────────────────────────────────────
REPORT_PATH = os.path.join(os.path.dirname(__file__), "output", "bias_report.json")

SIGNAL_COLORS = {
    "BULLISH": "#00C805",
    "BEARISH": "#FF4B4B",
    "NEUTRAL": "#FFA500",
}
SIGNAL_ICONS = {
    "BULLISH": "▲",
    "BEARISH": "▼",
    "NEUTRAL": "●",
}
BIAS_ICONS = {
    "BULLISH": "🟢",
    "BEARISH": "🔴",
    "NEUTRAL": "🟡",
}

# ── Helpers ───────────────────────────────────────────────────────────────────
def load_report():
    if os.path.exists(REPORT_PATH):
        with open(REPORT_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    return None


def run_analysis():
    """Trigger main.py and reload the report."""
    with st.spinner("Running analysis... this may take ~30 seconds"):
        result = subprocess.run(
            [sys.executable, os.path.join(os.path.dirname(__file__), "main.py")],
            capture_output=True,
            text=True,
            cwd=os.path.dirname(__file__),
        )
    if result.returncode == 0:
        st.success("Analysis complete! Refreshing...")
        st.rerun()
    else:
        st.error("Analysis failed. Check logs.")
        st.code(result.stderr[-2000:] if result.stderr else "No stderr output")


def fmt_confidence(value: float) -> str:
    return f"{value * 100:.1f}%"


def ny_time() -> str:
    ny = pytz.timezone("America/New_York")
    return datetime.now(ny).strftime("%Y-%m-%d %H:%M %Z")


# ── CSS ───────────────────────────────────────────────────────────────────────
st.markdown("""
<style>
    .signal-card {
        border-radius: 12px;
        padding: 24px 32px;
        text-align: center;
        margin-bottom: 8px;
    }
    .signal-label { font-size: 1rem; color: #888; font-weight: 500; margin-bottom: 4px; }
    .signal-value { font-size: 3rem; font-weight: 800; letter-spacing: 2px; }
    .signal-icon  { font-size: 2rem; }
    .conf-label   { font-size: 0.85rem; color: #aaa; margin-top: 8px; }
    .section-title { font-size: 1.1rem; font-weight: 700; margin-bottom: 8px; }
    .asset-row    { display: flex; justify-content: space-between; padding: 4px 0;
                    border-bottom: 1px solid #2a2a2a; font-size: 0.9rem; }
    .driver-line  { padding: 5px 0; font-size: 0.92rem; border-bottom: 1px solid #1e1e1e; }
    .tag-high   { background:#ff4b4b22; color:#ff4b4b; padding:2px 8px;
                  border-radius:4px; font-size:0.75rem; font-weight:600; }
    .tag-medium { background:#ffa50022; color:#ffa500; padding:2px 8px;
                  border-radius:4px; font-size:0.75rem; font-weight:600; }
    .tag-low    { background:#88888822; color:#888; padding:2px 8px;
                  border-radius:4px; font-size:0.75rem; font-weight:600; }
</style>
""", unsafe_allow_html=True)

# ── Header ────────────────────────────────────────────────────────────────────
col_title, col_btn = st.columns([4, 1])
with col_title:
    st.markdown("## 📈 NY Market Bias Analyzer")
    st.caption(f"New York time: {ny_time()}")
with col_btn:
    st.write("")
    if st.button("🔄 Run Analysis", use_container_width=True, type="primary"):
        run_analysis()

st.divider()

# ── Load report ───────────────────────────────────────────────────────────────
report = load_report()

if report is None:
    st.info("No report found. Click **Run Analysis** to generate one.")
    st.stop()

# ── Parse ─────────────────────────────────────────────────────────────────────
ny_bias       = report.get("ny_bias", {})
asia          = report.get("asia_session", {})
london        = report.get("london_session", {})
macro         = report.get("macro_sentiment", {})
signal        = ny_bias.get("signal", "NEUTRAL")
confidence    = ny_bias.get("confidence", 0.0)
is_valid      = ny_bias.get("is_valid_signal", False)
key_drivers   = ny_bias.get("key_drivers", [])
ts_raw        = report.get("timestamp", "")
try:
    ts = datetime.fromisoformat(ts_raw).strftime("%Y-%m-%d %H:%M UTC")
except Exception:
    ts = ts_raw

color = SIGNAL_COLORS.get(signal, "#888")
icon  = SIGNAL_ICONS.get(signal, "●")

# ── Main signal card ──────────────────────────────────────────────────────────
c1, c2, c3 = st.columns([2, 1.5, 1.5])

with c1:
    st.markdown(f"""
    <div class="signal-card" style="background:{color}18; border: 2px solid {color}55;">
        <div class="signal-label">NY OPENING BIAS</div>
        <div class="signal-value" style="color:{color};">{icon} {signal}</div>
        <div class="conf-label">Last updated: {ts}</div>
    </div>
    """, unsafe_allow_html=True)

with c2:
    st.metric("Confidence", fmt_confidence(confidence))
    st.progress(min(confidence, 1.0))
    validity_text = "✅ Valid Signal" if is_valid else "⚠️ Below threshold (85%)"
    st.caption(validity_text)

with c3:
    weighted = ny_bias.get("weighted_score", 0.0)
    direction = "Bullish" if weighted > 0 else "Bearish" if weighted < 0 else "Neutral"
    st.metric("Weighted Score", f"{weighted:+.3f}", delta=direction,
              delta_color="normal" if weighted > 0 else "inverse" if weighted < 0 else "off")
    sources = macro.get("data_sources", [])
    if sources:
        st.caption("Sources: " + " · ".join(sources))

st.divider()

# ── Sessions & Macro ──────────────────────────────────────────────────────────
col_asia, col_london, col_macro = st.columns(3)

def render_session(col, title, session_data):
    bias       = session_data.get("overall_bias", "N/A")
    conf       = session_data.get("confidence", 0.0)
    pattern    = session_data.get("dominant_pattern", "N/A")
    assets     = session_data.get("assets", {})
    bias_color = SIGNAL_COLORS.get(bias, "#888")
    bias_icon  = BIAS_ICONS.get(bias, "⚪")

    with col:
        st.markdown(f"**{title}**")
        st.markdown(
            f"<span style='color:{bias_color}; font-size:1.3rem; font-weight:700;'>"
            f"{bias_icon} {bias}</span> &nbsp; "
            f"<span style='color:#aaa; font-size:0.9rem;'>{fmt_confidence(conf)} confidence</span>",
            unsafe_allow_html=True,
        )
        st.caption(f"Pattern: {pattern}")

        if assets:
            rows = []
            for key, info in assets.items():
                b = info.get("bias", "N/A")
                p = info.get("pattern", "N/A")
                c = info.get("confidence", 0.0)
                close = info.get("last_close", None)
                name  = info.get("name", key)
                b_icon = BIAS_ICONS.get(b, "⚪")
                rows.append({
                    "Asset": name,
                    "Bias": f"{b_icon} {b}",
                    "Pattern": p,
                    "Conf": fmt_confidence(c),
                    "Close": f"{close:.2f}" if close else "N/A",
                })
            st.dataframe(rows, use_container_width=True, hide_index=True)
        else:
            st.caption("No asset data available.")

render_session(col_asia,   "🌏 Asia Session",   asia)
render_session(col_london, "🇬🇧 London Session", london)

# Macro column
with col_macro:
    macro_sentiment = macro.get("sentiment", "N/A")
    macro_conf      = macro.get("confidence", 0.0)
    macro_color     = SIGNAL_COLORS.get(macro_sentiment, "#888")
    macro_icon      = BIAS_ICONS.get(macro_sentiment, "⚪")
    upcoming        = macro.get("upcoming_events", [])

    st.markdown("**📰 Macro Events**")
    st.markdown(
        f"<span style='color:{macro_color}; font-size:1.3rem; font-weight:700;'>"
        f"{macro_icon} {macro_sentiment}</span> &nbsp; "
        f"<span style='color:#aaa; font-size:0.9rem;'>{fmt_confidence(macro_conf)} confidence</span>",
        unsafe_allow_html=True,
    )

    if upcoming:
        for ev in upcoming[:8]:
            impact = ev.get("impact", "").lower()
            tag_class = {"high": "tag-high", "medium": "tag-medium"}.get(impact, "tag-low")
            fc = ev.get("forecast", "N/A")
            prev = ev.get("previous", "N/A")
            fc_str = f"F: {fc} / P: {prev}" if fc != "N/A" else ""
            st.markdown(
                f"<div class='driver-line'>"
                f"<span class='{tag_class}'>{ev.get('impact','?')}</span> "
                f"<b>{ev.get('event','')[:35]}</b><br>"
                f"<span style='color:#888; font-size:0.8rem;'>"
                f"{ev.get('date','')}&nbsp;&nbsp;{fc_str}</span>"
                f"</div>",
                unsafe_allow_html=True,
            )
    else:
        st.caption("No upcoming events.")

st.divider()

# ── Key Drivers ───────────────────────────────────────────────────────────────
st.markdown("**🔍 Key Drivers**")
if key_drivers:
    for driver in key_drivers:
        clean = driver.lstrip("* ").strip()
        st.markdown(f"- {clean}")
else:
    st.caption("No drivers available.")

# ── Footer ────────────────────────────────────────────────────────────────────
st.divider()
st.caption(
    "Data: yfinance (OHLC) · FRED API (historical) · ForexFactory JSON (macro calendar) | "
    "Signals are informational only — not financial advice."
)
