"""
Analisador de Tendência de Mercado NY — Dashboard Streamlit
Correr localmente:  streamlit run app.py
Deploy:             Streamlit Community Cloud (streamlit.io/cloud)
"""

import streamlit as st
import json
import os
import sys
import subprocess
from datetime import datetime
import pytz

# ── Configuração da página ────────────────────────────────────────────────────
st.set_page_config(
    page_title="Analisador de Tendência NY",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# ── Constantes ────────────────────────────────────────────────────────────────
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

# Tradução dos sinais para português
SIGNAL_PT = {
    "BULLISH": "ALTA",
    "BEARISH": "BAIXA",
    "NEUTRAL": "NEUTRO",
    "N/A":     "N/D",
}

# Tradução dos padrões de candlestick
PATTERN_PT = {
    "Bullish Engulfing":  "Engolfo de Alta",
    "Bearish Engulfing":  "Engolfo de Baixa",
    "Hammer":             "Martelo",
    "Shooting Star":      "Estrela Cadente",
    "Doji":               "Doji",
    "Bullish Candle":     "Vela de Alta",
    "Bearish Candle":     "Vela de Baixa",
    "Insufficient Data":  "Dados Insuficientes",
    "No Data":            "Sem Dados",
    "Mixed":              "Misto",
}

IMPACT_PT = {
    "High":    "Alto",
    "Medium":  "Médio",
    "Low":     "Baixo",
    "Unknown": "Desconhecido",
}


# ── Funções auxiliares ────────────────────────────────────────────────────────
def load_report():
    if os.path.exists(REPORT_PATH):
        with open(REPORT_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    return None


def run_analysis():
    """Executa o main.py e recarrega o relatório."""
    with st.spinner("A correr análise... pode demorar ~30 segundos"):
        result = subprocess.run(
            [sys.executable, os.path.join(os.path.dirname(__file__), "main.py")],
            capture_output=True,
            text=True,
            cwd=os.path.dirname(__file__),
        )
    if result.returncode == 0:
        st.success("Análise concluída! A atualizar...")
        st.rerun()
    else:
        st.error("A análise falhou. Verifique os logs.")
        st.code(result.stderr[-2000:] if result.stderr else "Sem saída de erro")


def fmt_conf(value: float) -> str:
    return f"{value * 100:.1f}%"


def hora_ny() -> str:
    ny = pytz.timezone("America/New_York")
    return datetime.now(ny).strftime("%Y-%m-%d %H:%M %Z")


def traduz_padrao(pattern: str) -> str:
    return PATTERN_PT.get(pattern, pattern)


def traduz_sinal(signal: str) -> str:
    return SIGNAL_PT.get(signal, signal)


def traduz_impacto(impact: str) -> str:
    return IMPACT_PT.get(impact, impact)


# ── CSS ───────────────────────────────────────────────────────────────────────
st.markdown("""
<style>
    .signal-card  { border-radius:12px; padding:24px 32px;
                    text-align:center; margin-bottom:8px; }
    .signal-label { font-size:1rem; color:#888; font-weight:500; margin-bottom:4px; }
    .signal-value { font-size:3rem; font-weight:800; letter-spacing:2px; }
    .conf-label   { font-size:0.85rem; color:#aaa; margin-top:8px; }
    .driver-line  { padding:5px 0; font-size:0.92rem; border-bottom:1px solid #1e1e1e; }
    .tag-alto   { background:#ff4b4b22; color:#ff4b4b; padding:2px 8px;
                  border-radius:4px; font-size:0.75rem; font-weight:600; }
    .tag-medio  { background:#ffa50022; color:#ffa500; padding:2px 8px;
                  border-radius:4px; font-size:0.75rem; font-weight:600; }
    .tag-baixo  { background:#88888822; color:#888; padding:2px 8px;
                  border-radius:4px; font-size:0.75rem; font-weight:600; }
</style>
""", unsafe_allow_html=True)

# ── Cabeçalho ─────────────────────────────────────────────────────────────────
col_titulo, col_btn = st.columns([4, 1])
with col_titulo:
    st.markdown("## 📈 Analisador de Tendência — Abertura Nova Iorque")
    st.caption(f"Hora de Nova Iorque: {hora_ny()}")
with col_btn:
    st.write("")
    if st.button("🔄 Correr Análise", use_container_width=True, type="primary"):
        run_analysis()

st.divider()

# ── Carregar relatório ────────────────────────────────────────────────────────
report = load_report()

if report is None:
    st.info("Sem relatório disponível. Clique em **Correr Análise** para gerar um.")
    st.stop()

# ── Extrair dados ─────────────────────────────────────────────────────────────
ny_bias     = report.get("ny_bias", {})
asia        = report.get("asia_session", {})
london      = report.get("london_session", {})
macro       = report.get("macro_sentiment", {})
signal      = ny_bias.get("signal", "NEUTRAL")
confidence  = ny_bias.get("confidence", 0.0)
is_valid    = ny_bias.get("is_valid_signal", False)
key_drivers = ny_bias.get("key_drivers", [])
ts_raw      = report.get("timestamp", "")

try:
    ts = datetime.fromisoformat(ts_raw).strftime("%Y-%m-%d %H:%M UTC")
except Exception:
    ts = ts_raw

color = SIGNAL_COLORS.get(signal, "#888")
icon  = SIGNAL_ICONS.get(signal, "●")
label = traduz_sinal(signal)

# ── Cartão principal ──────────────────────────────────────────────────────────
c1, c2, c3 = st.columns([2, 1.5, 1.5])

with c1:
    st.markdown(f"""
    <div class="signal-card" style="background:{color}18; border:2px solid {color}55;">
        <div class="signal-label">TENDÊNCIA ABERTURA NY</div>
        <div class="signal-value" style="color:{color};">{icon} {label}</div>
        <div class="conf-label">Última atualização: {ts}</div>
    </div>
    """, unsafe_allow_html=True)

with c2:
    st.metric("Confiança", fmt_conf(confidence))
    st.progress(min(confidence, 1.0))
    validade = "✅ Sinal Válido" if is_valid else "⚠️ Abaixo do limiar (85%)"
    st.caption(validade)

with c3:
    weighted  = ny_bias.get("weighted_score", 0.0)
    direcao   = "Alta" if weighted > 0 else "Baixa" if weighted < 0 else "Neutro"
    st.metric("Score Ponderado", f"{weighted:+.3f}", delta=direcao,
              delta_color="normal" if weighted > 0 else "inverse" if weighted < 0 else "off")
    fontes = macro.get("data_sources", [])
    if fontes:
        st.caption("Fontes: " + " · ".join(fontes))

st.divider()

# ── Sessões e Macro ───────────────────────────────────────────────────────────
col_asia, col_london, col_macro = st.columns(3)


def render_sessao(col, titulo, session_data):
    bias        = session_data.get("overall_bias", "N/A")
    conf        = session_data.get("confidence", 0.0)
    pattern     = session_data.get("dominant_pattern", "N/A")
    assets      = session_data.get("assets", {})
    bias_color  = SIGNAL_COLORS.get(bias, "#888")
    bias_icon   = BIAS_ICONS.get(bias, "⚪")
    bias_label  = traduz_sinal(bias)

    with col:
        st.markdown(f"**{titulo}**")
        st.markdown(
            f"<span style='color:{bias_color}; font-size:1.3rem; font-weight:700;'>"
            f"{bias_icon} {bias_label}</span> &nbsp; "
            f"<span style='color:#aaa; font-size:0.9rem;'>{fmt_conf(conf)} de confiança</span>",
            unsafe_allow_html=True,
        )
        st.caption(f"Padrão dominante: {traduz_padrao(pattern)}")

        if assets:
            rows = []
            for key, info in assets.items():
                b      = info.get("bias", "N/A")
                p      = info.get("pattern", "N/A")
                c      = info.get("confidence", 0.0)
                close  = info.get("last_close", None)
                name   = info.get("name", key)
                b_icon = BIAS_ICONS.get(b, "⚪")
                rows.append({
                    "Ativo":      name,
                    "Tendência":  f"{b_icon} {traduz_sinal(b)}",
                    "Padrão":     traduz_padrao(p),
                    "Conf.":      fmt_conf(c),
                    "Fecho":      f"{close:.2f}" if close else "N/D",
                })
            st.dataframe(rows, use_container_width=True, hide_index=True)
        else:
            st.caption("Sem dados de ativos disponíveis.")


render_sessao(col_asia,   "🌏 Sessão Ásia",     asia)
render_sessao(col_london, "🇬🇧 Sessão Londres",  london)

# Coluna Macro
with col_macro:
    macro_sinal = macro.get("sentiment", "N/A")
    macro_conf  = macro.get("confidence", 0.0)
    macro_color = SIGNAL_COLORS.get(macro_sinal, "#888")
    macro_icon  = BIAS_ICONS.get(macro_sinal, "⚪")
    macro_label = traduz_sinal(macro_sinal)
    upcoming    = macro.get("upcoming_events", [])

    st.markdown("**📰 Eventos Macroeconómicos**")
    st.markdown(
        f"<span style='color:{macro_color}; font-size:1.3rem; font-weight:700;'>"
        f"{macro_icon} {macro_label}</span> &nbsp; "
        f"<span style='color:#aaa; font-size:0.9rem;'>{fmt_conf(macro_conf)} de confiança</span>",
        unsafe_allow_html=True,
    )

    if upcoming:
        for ev in upcoming[:8]:
            impact_en  = ev.get("impact", "")
            impact_pt  = traduz_impacto(impact_en)
            tag_class  = {"Alto": "tag-alto", "Médio": "tag-medio"}.get(impact_pt, "tag-baixo")
            fc         = ev.get("forecast", "N/D")
            prev       = ev.get("previous", "N/D")
            fc_str     = f"Prev: {fc} / Ant: {prev}" if fc not in ("N/A", "N/D") else ""
            st.markdown(
                f"<div class='driver-line'>"
                f"<span class='{tag_class}'>{impact_pt}</span> "
                f"<b>{ev.get('event','')[:38]}</b><br>"
                f"<span style='color:#888; font-size:0.8rem;'>"
                f"{ev.get('date','')}&nbsp;&nbsp;{fc_str}</span>"
                f"</div>",
                unsafe_allow_html=True,
            )
    else:
        st.caption("Sem eventos próximos disponíveis.")

st.divider()

# ── Fatores Determinantes ─────────────────────────────────────────────────────
st.markdown("**🔍 Fatores Determinantes**")
if key_drivers:
    for driver in key_drivers:
        clean = driver.lstrip("* ").strip()
        st.markdown(f"- {clean}")
else:
    st.caption("Sem fatores disponíveis.")

# ── Rodapé ────────────────────────────────────────────────────────────────────
st.divider()
st.caption(
    "Dados: yfinance (OHLC) · FRED API (histórico) · ForexFactory JSON (calendário macro) | "
    "Os sinais são meramente informativos — não constituem aconselhamento financeiro."
)
