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

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from src.evaluator import (
    get_all_evaluations, get_pending_evaluations,
    set_actual_result, calculate_accuracy_stats, delete_evaluation,
)

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
    """Executa o main.py, guarda a previsão na BD de avaliação e recarrega."""
    with st.spinner("A correr análise... pode demorar ~30 segundos"):
        result = subprocess.run(
            [sys.executable, os.path.join(os.path.dirname(__file__), "main.py")],
            capture_output=True,
            text=True,
            cwd=os.path.dirname(__file__),
        )
    if result.returncode == 0:
        # Auto-save prediction to evaluations DB
        try:
            report = load_report()
            if report:
                from src.evaluator import save_prediction
                save_prediction(report)
        except Exception:
            pass   # non-critical
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

tab_dashboard, tab_avaliacao = st.tabs(["📊 Dashboard", "🎯 Avaliação"])

# ── Carregar relatório ────────────────────────────────────────────────────────
report = load_report()

# ════════════════════════════════════════════════════════════════════════════
# TAB 1 — DASHBOARD
# ════════════════════════════════════════════════════════════════════════════
with tab_dashboard:
    if report is None:
        st.info("Sem relatório disponível. Clique em **Correr Análise** para gerar um.")
        st.stop()

    # ── Extrair dados ─────────────────────────────────────────────────────
    ny_bias     = report.get("ny_bias", {})
    asia        = report.get("asia_session", {})
    london      = report.get("london_session", {})
    macro       = report.get("macro_sentiment", {})
    news        = report.get("news_sentiment", {})
    regime_data = report.get("market_regime", {})
    signal      = ny_bias.get("signal", "NEUTRAL")
    confidence  = ny_bias.get("confidence", 0.0)
    is_valid    = ny_bias.get("is_valid_signal", False)
    key_drivers = ny_bias.get("key_drivers", [])
    volatility  = ny_bias.get("volatility_expected", "—")
    weights_used = ny_bias.get("weights_used", {})
    ts_raw      = report.get("timestamp", "")

    try:
        ts = datetime.fromisoformat(ts_raw).strftime("%Y-%m-%d %H:%M UTC")
    except Exception:
        ts = ts_raw

    color = SIGNAL_COLORS.get(signal, "#888")
    icon  = SIGNAL_ICONS.get(signal, "●")
    label = traduz_sinal(signal)

    # ── Regime badge ──────────────────────────────────────────────────────
    REGIME_COLORS = {
        "inflation_fight": "#FF8C00",
        "recession_fear":  "#FF4B4B",
        "neutral":         "#888888",
    }
    REGIME_ICONS = {
        "inflation_fight": "🔥",
        "recession_fear":  "📉",
        "neutral":         "⚖️",
    }
    regime_key   = regime_data.get("regime", "neutral")
    regime_label = {"inflation_fight": "Combate à Inflação",
                    "recession_fear":  "Receio de Recessão",
                    "neutral":         "Neutro"}.get(regime_key, regime_key)
    regime_score = regime_data.get("score", 0)
    regime_color = REGIME_COLORS.get(regime_key, "#888")
    regime_icon  = REGIME_ICONS.get(regime_key, "⚖️")

    st.markdown(
        f"<div style='margin-bottom:8px;'>"
        f"<span style='background:{regime_color}22; border:1px solid {regime_color}66; "
        f"color:{regime_color}; border-radius:6px; padding:4px 12px; font-size:0.9rem; font-weight:600;'>"
        f"{regime_icon} Regime: {regime_label} &nbsp;|&nbsp; Score: {regime_score:+d}"
        f"</span></div>",
        unsafe_allow_html=True,
    )

    # ── Cartão principal ──────────────────────────────────────────────────
    c1, c2, c3 = st.columns([2, 1.5, 1.5])

    with c1:
        st.markdown(f"""
        <div class="signal-card" style="background:{color}18; border:2px solid {color}55;">
            <div class="signal-label">TENDÊNCIA ABERTURA NY (9:30–10:30)</div>
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
        weighted = ny_bias.get("weighted_score", 0.0)
        direcao  = "Alta" if weighted > 0 else "Baixa" if weighted < 0 else "Neutro"
        st.metric("Score Ponderado", f"{weighted:+.3f}", delta=direcao,
                  delta_color="normal" if weighted > 0 else "inverse" if weighted < 0 else "off")
        VOL_COLORS = {"ALTA": "#FF4B4B", "MÉDIA": "#FFA500", "BAIXA": "#00C805", "MUITO BAIXA": "#888"}
        vol_color = VOL_COLORS.get(volatility, "#888")
        st.markdown(
            f"<span style='font-size:0.85rem;'>Volatilidade esperada: "
            f"<b style='color:{vol_color};'>{volatility}</b></span>",
            unsafe_allow_html=True,
        )
        if weights_used:
            st.caption(
                f"Pesos: Sessões {weights_used.get('sessions',0):.0%} · "
                f"Macro {weights_used.get('macro',0):.0%} · "
                f"Notícias {weights_used.get('news',0):.0%}"
            )

    st.divider()

    # ── Regime — indicadores detalhados ───────────────────────────────────
    with st.expander(f"{regime_icon} Detalhe do Regime de Mercado — {regime_label}", expanded=False):
        indicators = regime_data.get("indicators", {})
        scores     = regime_data.get("scores", {})
        desc       = regime_data.get("description", "")
        if desc:
            st.caption(desc)
        ind_rows = [
            {"Indicador": "Curva de Yields (10Y-2Y)", "Valor": f"{indicators.get('yield_curve_spread'):+.2f}pp" if indicators.get('yield_curve_spread') is not None else "N/D", "Pontos": scores.get("yield_curve", 0), "Nota": "Invertida = recessão"},
            {"Indicador": "VIX",                      "Valor": f"{indicators.get('vix'):.1f}"               if indicators.get('vix') is not None else "N/D",                   "Pontos": scores.get("vix", 0),         "Nota": ">20 = medo elevado"},
            {"Indicador": "Core PCE (YoY %)",         "Valor": f"{indicators.get('pce_yoy'):.2f}%"          if indicators.get('pce_yoy') is not None else "N/D",               "Pontos": scores.get("pce", 0),         "Nota": "Objectivo Fed = 2% ★"},
            {"Indicador": "CPI (YoY %)",              "Valor": f"{indicators.get('cpi_yoy'):.1f}%"          if indicators.get('cpi_yoy') is not None else "N/D",               "Pontos": scores.get("cpi", 0),         "Nota": "Inflação ao consumidor"},
            {"Indicador": "Taxa Fed Funds",            "Valor": f"{indicators.get('fed_rate'):.2f}%"         if indicators.get('fed_rate') is not None else "N/D",               "Pontos": scores.get("fed_rate", 0),    "Nota": ">4% = restritivo"},
            {"Indicador": "Desemprego (Δ 3m)",         "Valor": f"{indicators.get('unemployment_delta'):+.2f}pp" if indicators.get('unemployment_delta') is not None else "N/D","Pontos": scores.get("unemployment", 0),"Nota": "Δ>0.5pp = alarme"},
            {"Indicador": "PMI",                       "Valor": f"{indicators.get('pmi'):.1f}"               if indicators.get('pmi') is not None else "N/D",                   "Pontos": scores.get("pmi", 0),         "Nota": "<50 = contracção"},
        ]
        st.dataframe(ind_rows, use_container_width=True, hide_index=True)
        st.caption(f"Score total: {regime_score:+d}  |  ≥+2 = Combate Inflação  |  ≤-2 = Receio Recessão  |  ★ = indicador preferido da Fed")

    # ── Sessões e Macro ───────────────────────────────────────────────────
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
                        "Ativo":     name,
                        "Tendência": f"{b_icon} {traduz_sinal(b)}",
                        "Padrão":    traduz_padrao(p),
                        "Conf.":     fmt_conf(c),
                        "Fecho":     f"{close:.2f}" if close else "N/D",
                    })
                st.dataframe(rows, use_container_width=True, hide_index=True)
            else:
                st.caption("Sem dados de ativos disponíveis.")

    render_sessao(col_asia,   "🌏 Sessão Ásia",    asia)
    render_sessao(col_london, "🇬🇧 Sessão Londres", london)

    # Coluna Macro
    with col_macro:
        macro_sinal = macro.get("sentiment", "N/A")
        macro_conf  = macro.get("confidence", 0.0)
        macro_color = SIGNAL_COLORS.get(macro_sinal, "#888")
        macro_icon  = BIAS_ICONS.get(macro_sinal, "⚪")
        macro_label = traduz_sinal(macro_sinal)
        upcoming    = macro.get("upcoming_events", [])
        regime_applied = macro.get("regime_applied", "neutral")

        st.markdown("**📰 Eventos Macroeconómicos**")
        st.markdown(
            f"<span style='color:{macro_color}; font-size:1.3rem; font-weight:700;'>"
            f"{macro_icon} {macro_label}</span> &nbsp; "
            f"<span style='color:#aaa; font-size:0.9rem;'>{fmt_conf(macro_conf)} de confiança</span>",
            unsafe_allow_html=True,
        )
        st.caption(f"Interpretados com regime: {regime_applied}")

        if upcoming:
            for ev in upcoming[:8]:
                impact_en  = ev.get("impact", "")
                impact_pt  = traduz_impacto(impact_en)
                tag_class  = {"Alto": "tag-alto", "Médio": "tag-medio"}.get(impact_pt, "tag-baixo")
                fc         = ev.get("forecast", "N/D")
                prev       = ev.get("previous", "N/D")
                actual_v   = ev.get("actual", "")
                fc_str     = f"Prev: {fc} / Ant: {prev}" if fc not in ("N/A", "N/D") else ""
                actual_str = f" | Real: <b>{actual_v}</b>" if actual_v not in ("N/A", "N/D", None, "") else ""
                st.markdown(
                    f"<div class='driver-line'>"
                    f"<span class='{tag_class}'>{impact_pt}</span> "
                    f"<b>{ev.get('event','')[:38]}</b><br>"
                    f"<span style='color:#888; font-size:0.8rem;'>"
                    f"{ev.get('date','')}&nbsp;&nbsp;{fc_str}{actual_str}</span>"
                    f"</div>",
                    unsafe_allow_html=True,
                )
        else:
            st.caption("Sem eventos próximos disponíveis.")

    st.divider()

    # ── Notícias SPY / QQQ / Magnificent 7 ───────────────────────────────
    news_bias_val  = news.get("bias", "NEUTRAL")
    news_conf_val  = news.get("confidence", 0.0)
    news_impact    = news.get("impact_level", "none")
    scored_items   = news.get("scored_items", [])
    total_hl       = news.get("total_headlines", 0)
    classified_hl  = news.get("classified_count", 0)
    hi_count       = news.get("high_impact_count", 0)

    news_color = SIGNAL_COLORS.get(news_bias_val, "#888")
    news_icon  = BIAS_ICONS.get(news_bias_val, "⚪")
    IMPACT_COLORS = {"high": "#FF4B4B", "medium": "#FFA500", "low": "#888", "none": "#555"}
    impact_color = IMPACT_COLORS.get(news_impact, "#555")
    IMPACT_PT_MAP = {"high": "Alto", "medium": "Médio", "low": "Baixo", "none": "Sem notícias relevantes"}

    st.markdown("**📰 Notícias — SPY / QQQ / Magnificent 7**")
    nc1, nc2, nc3 = st.columns([2, 1, 1])
    with nc1:
        st.markdown(
            f"<span style='color:{news_color}; font-size:1.2rem; font-weight:700;'>"
            f"{news_icon} {traduz_sinal(news_bias_val)}</span> &nbsp; "
            f"<span style='color:#aaa; font-size:0.85rem;'>{fmt_conf(news_conf_val)} confiança</span>",
            unsafe_allow_html=True,
        )
    with nc2:
        st.markdown(
            f"Impacto: <b style='color:{impact_color};'>{IMPACT_PT_MAP.get(news_impact,'—')}</b>",
            unsafe_allow_html=True,
        )
        st.caption(f"{total_hl} headlines · {classified_hl} classificadas · {hi_count} alto impacto")
    with nc3:
        vol_color2 = VOL_COLORS.get(volatility, "#888")
        st.markdown(
            f"Volatilidade: <b style='color:{vol_color2};'>{volatility}</b>",
            unsafe_allow_html=True,
        )

    CATEGORY_PT = {
        "tariff":            "🚧 Tarifas/Comércio",
        "fed_dovish":        "🕊️ Fed Dovish",
        "fed_hawkish":       "🦅 Fed Hawkish",
        "geopolitical":      "⚔️ Geopolítica",
        "corporate_positive":"📈 Corporativo +",
        "corporate_negative":"📉 Corporativo -",
        "political":         "🏛️ Política",
    }
    SIGNAL_BADGE = {"BULLISH": "🟢", "BEARISH": "🔴", "NEUTRAL": "🟡"}

    if scored_items:
        with st.expander(f"Ver headlines classificadas ({len(scored_items)})", expanded=news_impact == "high"):
            for item in scored_items[:15]:
                cat_label = CATEGORY_PT.get(item.get("category",""), item.get("category",""))
                sig_badge = SIGNAL_BADGE.get(item.get("signal","NEUTRAL"), "🟡")
                hi_badge  = " ⚡" if item.get("high_impact") else ""
                st.markdown(
                    f"{sig_badge}{hi_badge} **{item['title'][:80]}**  \n"
                    f"<span style='color:#888; font-size:0.78rem;'>"
                    f"{cat_label} · {item.get('ticker','')} · {item.get('publisher','')} · "
                    f"{item.get('published_at','')}</span>",
                    unsafe_allow_html=True,
                )
    elif total_hl == 0:
        st.caption("Sem headlines disponíveis nas últimas 48h — volatilidade reduzida esperada.")
    else:
        st.caption(f"{total_hl} headlines encontradas mas nenhuma classificada como relevante.")

    st.divider()

    # ── Contexto Histórico ────────────────────────────────────────────────
    hist = report.get("historical_context", {})
    hist_available = hist.get("available", False)

    with st.expander("📚 Contexto Histórico — Como o mercado reagiu no passado", expanded=hist_available):
        if hist_available:
            hb   = hist.get("overall_bias", "NEUTRAL")
            hc   = hist.get("overall_conf", 0.0)
            hn   = hist.get("total_samples", 0)
            hcolor = SIGNAL_COLORS.get(hb, "#888")
            hicon  = BIAS_ICONS.get(hb, "⚪")

            hc1, hc2 = st.columns([2, 1])
            with hc1:
                st.markdown(
                    f"Base histórica: <span style='color:{hcolor}; font-size:1.1rem; font-weight:700;'>"
                    f"{hicon} {traduz_sinal(hb)}</span> &nbsp; "
                    f"<span style='color:#aaa;'>({hc:.0%} conf | {hn} amostras)</span>",
                    unsafe_allow_html=True,
                )
                st.caption(f"Regime aplicado: {hist.get('regime','—')} | Últimos {5} anos de dados")
            with hc2:
                st.caption("Como interpretar: % das vezes em que o mercado subiu/desceu em condições similares")

            per_event = hist.get("per_event", [])
            if per_event:
                EVENT_LABELS = {
                    "NFP":     "Non-Farm Payrolls",
                    "CPI":     "CPI",
                    "PCE":     "Core PCE",
                    "PMI":     "ISM PMI",
                    "JOBLESS": "Jobless Claims",
                    "GDP":     "GDP",
                    "FOMC":    "FOMC",
                }
                rows = []
                for ev in per_event:
                    bull_pct = ev.get("bullish_pct", 0)
                    bear_pct = ev.get("bearish_pct", 0)
                    dom      = ev.get("dominant", "NEUTRAL")
                    dom_icon = BIAS_ICONS.get(dom, "⚪")
                    avg_ret  = ev.get("avg_spy_ret")
                    rows.append({
                        "Evento":       EVENT_LABELS.get(ev["event_key"], ev["event_key"]),
                        "Dado":         ev.get("hot_label", "—").capitalize(),
                        "N amostras":   ev.get("n_samples", 0),
                        "Bullish %":    f"{bull_pct:.0%}",
                        "Bearish %":    f"{bear_pct:.0%}",
                        "Dominante":    f"{dom_icon} {traduz_sinal(dom)}",
                        "SPY med. %":   f"{avg_ret:+.2f}%" if avg_ret is not None else "N/D",
                        "Peso":         f"{ev.get('weight', 0):.0%}",
                    })
                st.dataframe(rows, use_container_width=True, hide_index=True)
        elif hist.get("db_has_data"):
            st.info("Base de dados histórica existe mas sem eventos correspondentes às condições de hoje.")
        else:
            st.warning(
                "Base de dados histórica não encontrada.  \n"
                "Execute `python main.py --build-history` para construir o histórico de 5 anos "
                "(requer FRED_API_KEY configurado no ficheiro `.env`). "
                "Demora ~5-10 minutos na primeira vez; depois é actualizado semanalmente."
            )

    st.divider()

    # ── Fatores Determinantes ─────────────────────────────────────────────
    st.markdown("**🔍 Fatores Determinantes**")
    if key_drivers:
        for driver in key_drivers:
            clean = driver.lstrip("* ").strip()
            st.markdown(f"- {clean}")
    else:
        st.caption("Sem fatores disponíveis.")

    # ── Rodapé ────────────────────────────────────────────────────────────
    st.divider()
    st.caption(
        "Dados: yfinance (OHLC) · FRED API (histórico) · ForexFactory JSON (calendário macro) | "
        "Os sinais são meramente informativos — não constituem aconselhamento financeiro."
    )


# ════════════════════════════════════════════════════════════════════════════
# TAB 2 — AVALIAÇÃO
# ════════════════════════════════════════════════════════════════════════════
with tab_avaliacao:
    st.markdown("### 🎯 Avaliação de Previsões")
    st.caption(
        "Regista o resultado real do mercado após cada sessão para medir a taxa de acerto do bot."
    )

    # ── Estatísticas de Precisão ──────────────────────────────────────────
    stats = calculate_accuracy_stats()
    total_eval = stats.get("total_evaluated", 0)

    if total_eval > 0:
        acc = stats.get("accuracy", 0.0)
        acc_color = "#00C805" if acc >= 0.6 else "#FFA500" if acc >= 0.4 else "#FF4B4B"

        s1, s2, s3, s4 = st.columns(4)
        s1.metric("Total Avaliadas", total_eval)
        s2.metric("Corretas", stats.get("correct", 0))
        s3.metric("Taxa de Acerto", f"{acc:.0%}")
        valid_stats = stats.get("valid_signals_only", {})
        v_acc = valid_stats.get("accuracy", 0.0)
        v_total = valid_stats.get("total", 0)
        s4.metric("Acerto Sinais Válidos", f"{v_acc:.0%}", delta=f"{v_total} registos")

        # By regime
        by_regime = stats.get("by_regime", {})
        if by_regime:
            st.markdown("**Por Regime:**")
            regime_rows = []
            regime_names = {
                "inflation_fight": "🔥 Combate à Inflação",
                "recession_fear":  "📉 Receio de Recessão",
                "neutral":         "⚖️ Neutro",
            }
            for reg, data in by_regime.items():
                regime_rows.append({
                    "Regime":        regime_names.get(reg, reg),
                    "Avaliadas":     data["total"],
                    "Corretas":      data["correct"],
                    "Taxa de Acerto": f"{data['accuracy']:.0%}",
                })
            st.dataframe(regime_rows, use_container_width=True, hide_index=True)
    else:
        st.info("Ainda sem avaliações registadas. Preenche os resultados reais na tabela abaixo.")

    st.divider()

    # ── Previsões pendentes de avaliação ─────────────────────────────────
    pending = get_pending_evaluations()
    if pending:
        st.markdown(f"**⏳ Pendentes de avaliação ({len(pending)})**")
        for row in pending:
            events_list = []
            try:
                events_list = json.loads(row.get("key_events") or "[]")
            except Exception:
                pass
            events_str = ", ".join(events_list[:3]) if events_list else "—"

            pred_signal = row["predicted_bias"]
            pred_color  = SIGNAL_COLORS.get(pred_signal, "#888")
            pred_icon   = BIAS_ICONS.get(pred_signal, "⚪")

            with st.container(border=True):
                col_info, col_form = st.columns([2, 1])
                with col_info:
                    st.markdown(
                        f"**{row['session_date']}** &nbsp;|&nbsp; "
                        f"<span style='color:{pred_color}; font-weight:700;'>"
                        f"{pred_icon} {traduz_sinal(pred_signal)}</span> &nbsp;"
                        f"({row['predicted_conf']*100:.0f}% conf.)",
                        unsafe_allow_html=True,
                    )
                    regime_p = row.get("regime") or "neutral"
                    st.caption(
                        f"Regime: {regime_p.replace('_', ' ').title()} &nbsp;|&nbsp; "
                        f"Eventos: {events_str}"
                    )
                with col_form:
                    result_key = f"result_{row['id']}"
                    notes_key  = f"notes_{row['id']}"
                    actual_sel = st.selectbox(
                        "Resultado real",
                        options=["—", "BULLISH", "BEARISH", "NEUTRAL"],
                        key=result_key,
                        label_visibility="collapsed",
                    )
                    notes_inp = st.text_input(
                        "Notas (opcional)",
                        key=notes_key,
                        placeholder="ex: reversão após notícia...",
                        label_visibility="collapsed",
                    )
                    if st.button("💾 Guardar", key=f"save_{row['id']}", use_container_width=True):
                        if actual_sel == "—":
                            st.warning("Selecciona um resultado antes de guardar.")
                        else:
                            set_actual_result(row["id"], actual_sel, notes_inp)
                            st.success("Guardado!")
                            st.rerun()
    else:
        st.success("Todas as previsões estão avaliadas.")

    st.divider()

    # ── Histórico completo ────────────────────────────────────────────────
    with st.expander("📋 Histórico Completo", expanded=False):
        all_evals = get_all_evaluations(limit=100)
        if all_evals:
            table_rows = []
            for row in all_evals:
                pred   = row["predicted_bias"]
                actual = row.get("actual_result") or "—"
                match  = "✅" if pred == actual else ("❌" if actual != "—" else "⏳")
                table_rows.append({
                    "Data":        row["session_date"],
                    "Previsão":    f"{BIAS_ICONS.get(pred,'⚪')} {traduz_sinal(pred)}",
                    "Conf.":       f"{row['predicted_conf']*100:.0f}%",
                    "Regime":      (row.get("regime") or "—").replace("_", " "),
                    "Real":        f"{BIAS_ICONS.get(actual,'⚪')} {traduz_sinal(actual)}" if actual != "—" else "—",
                    "Resultado":   match,
                    "Notas":       row.get("notes") or "",
                })
            st.dataframe(table_rows, use_container_width=True, hide_index=True)

            # Delete row
            with st.form("delete_form"):
                del_id = st.number_input("ID a apagar", min_value=1, step=1)
                if st.form_submit_button("🗑️ Apagar registo"):
                    if delete_evaluation(int(del_id)):
                        st.success(f"Registo #{del_id} apagado.")
                        st.rerun()
                    else:
                        st.error(f"Registo #{del_id} não encontrado.")
        else:
            st.caption("Sem histórico disponível.")
