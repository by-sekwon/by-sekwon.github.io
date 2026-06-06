import streamlit as st
import yfinance as yf
import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

st.set_page_config(page_title="매수적절성 분석기", page_icon="📊", layout="wide")

st.markdown("""
<div style="background:linear-gradient(135deg,#1a3a2a,#2d6a4f);
            padding:1.2rem 1.6rem;border-radius:10px;color:#f5f0e8;margin-bottom:1.2rem;">
  <h2 style="margin:0;font-size:1.4rem;">📊 매수적절성 분석기</h2>
  <p style="margin:0.3rem 0 0;font-size:0.85rem;opacity:0.85;">
    yfinance 데이터 × 추세·모멘텀·거래량·변동성·이격도·캔들 6개 요인 베이지안 가중 점수
  </p>
</div>
""", unsafe_allow_html=True)

# ── 분석 함수 ─────────────────────────────────────────────
@st.cache_data(ttl=1800, show_spinner=False)
def analyze_stock(ticker: str) -> dict:
    if ticker.isdigit() or (ticker[:6].isdigit() and '.' not in ticker):
        ticker = ticker + ".KS"

    df = yf.Ticker(ticker).history(period="2y", auto_adjust=True)
    if df.empty:
        raise ValueError(f"데이터 없음: {ticker}")

    close  = df["Close"]
    high   = df["High"]
    low    = df["Low"]
    volume = df["Volume"]

    ma5  = close.rolling(5).mean()
    ma10 = close.rolling(10).mean()
    ma20 = close.rolling(20).mean()
    ma60 = close.rolling(60).mean()
    last = float(close.iloc[-1])

    tr = pd.concat([
        high - low,
        (high - close.shift(1)).abs(),
        (low  - close.shift(1)).abs()
    ], axis=1).max(axis=1)
    atr14     = tr.rolling(14).mean().iloc[-1]
    atr_pct   = atr14 / last * 100
    stop_loss = last - 1.5 * atr14
    target    = last + 3.0 * atr14

    delta = close.diff()
    gain  = delta.clip(lower=0).rolling(14).mean()
    loss  = (-delta.clip(upper=0)).rolling(14).mean()
    rs    = gain / loss.replace(0, np.nan)
    rsi   = float((100 - 100 / (1 + rs)).iloc[-1])

    ema12      = close.ewm(span=12, adjust=False).mean()
    ema26      = close.ewm(span=26, adjust=False).mean()
    macd       = ema12 - ema26
    signal_ln  = macd.ewm(span=9, adjust=False).mean()
    hist       = macd - signal_ln
    macd_slope = float(hist.iloc[-1] - hist.iloc[-2])
    macd_cross_up = bool((hist.iloc[-1] > 0) and (hist.iloc[-2] <= 0))

    low14   = low.rolling(14).min()
    high14  = high.rolling(14).max()
    stoch_k = float(((close - low14) / (high14 - low14).replace(0, np.nan) * 100).iloc[-1])

    std20   = close.rolling(20).std()
    bb_up   = ma20 + 2 * std20
    bb_dn   = ma20 - 2 * std20
    bb_pctB = float(((close - bb_dn) / (bb_up - bb_dn).replace(0, np.nan)).iloc[-1])

    plus_dm  = (high.diff()).clip(lower=0)
    minus_dm = (-low.diff()).clip(lower=0)
    mask     = plus_dm < minus_dm
    plus_dm[mask]   = 0
    mask2    = minus_dm <= plus_dm
    minus_dm[mask2] = 0
    atr14s   = tr.rolling(14).mean()
    pdi      = 100 * plus_dm.rolling(14).mean()  / atr14s.replace(0, np.nan)
    mdi      = 100 * minus_dm.rolling(14).mean() / atr14s.replace(0, np.nan)
    dx       = 100 * (pdi - mdi).abs() / (pdi + mdi).replace(0, np.nan)
    adx      = float(dx.rolling(14).mean().iloc[-1])

    disp_ma20    = float((close / ma20 - 1).iloc[-1] * 100)
    vol_ma20     = volume.rolling(20).mean()
    vol_surge    = float((volume.rolling(5).mean() / vol_ma20.replace(0, np.nan)).iloc[-1])
    vol_ratio_1d = float(volume.iloc[-1] / vol_ma20.iloc[-1])
    obv          = (np.sign(close.diff()) * volume).fillna(0).cumsum()
    obv_up       = bool(obv.iloc[-1] > obv.iloc[-6])

    o = df["Open"]
    body       = (close - o).abs()
    upper_wick = high - close.clip(lower=o)
    lower_wick = o.clip(upper=close) - low
    hammer  = bool((lower_wick.iloc[-1] >= 2 * body.iloc[-1]) and
                   (upper_wick.iloc[-1] < body.iloc[-1]) and
                   (close.iloc[-1] > o.iloc[-1]))
    bullish3 = bool(all(close.iloc[-i] > o.iloc[-i] for i in range(1, 4)))
    big_bull = bool((close.iloc[-1] > o.iloc[-1]) and (body.iloc[-1] >= 0.04 * last))

    low_1y     = float(low.iloc[-252:].min())
    rebound_1y = (last - low_1y) / low_1y * 100

    gc_dates = []
    for i in range(1, len(df)):
        if (ma20.iloc[i] > ma60.iloc[i]) and (ma20.iloc[i - 1] <= ma60.iloc[i - 1]):
            gc_dates.append(df.index[i])
    most_recent     = gc_dates[-1] if gc_dates else None
    days_since      = (df.index[-1] - most_recent).days if most_recent else None
    currently_above = bool(ma20.iloc[-1] > ma60.iloc[-1])

    ma_align = sum([
        float(ma5.iloc[-1])  > float(ma10.iloc[-1]),
        float(ma10.iloc[-1]) > float(ma20.iloc[-1]),
        float(ma20.iloc[-1]) > float(ma60.iloc[-1]),
    ])
    hv20     = float(close.pct_change().rolling(20).std().iloc[-1] * np.sqrt(252) * 100)
    price_up = bool(close.iloc[-1] > close.iloc[-2])

    # ── 점수 계산 ──────────────────────────────────────────
    trend_score = 0; trend_details = []
    if ma_align >= 3:
        trend_score += 4; trend_details.append(f"단기 MA 정배열 {ma_align}/3단계 (MA5>MA10>MA20>MA60)")
    elif ma_align == 2:
        trend_score += 2; trend_details.append(f"단기 MA 정배열 {ma_align}/3단계")
    if currently_above:
        trend_score += 3; trend_details.append("MA20 > MA60 유지 ✅")
    if adx >= 30:
        trend_score += 3; trend_details.append(f"ADX={adx:.1f} (강한 추세 ≥30) ✅")
    elif adx >= 20:
        trend_score += 1; trend_details.append(f"ADX={adx:.1f} (추세 진행 중)")
    trend_score = min(trend_score, 10)

    mom_score = 0; mom_details = []
    if 50 <= rsi <= 70:
        mom_score += 3; mom_details.append(f"RSI={rsi:.1f} (이상적 50~70) ✅")
    elif rsi > 70:
        mom_score += 1; mom_details.append(f"RSI={rsi:.1f} (과매수 주의)")
    else:
        mom_details.append(f"RSI={rsi:.1f} (약세)")
    if macd_cross_up:
        mom_score += 3; mom_details.append("MACD 시그널 상향돌파 ✅")
    if macd_slope > 0:
        mom_score += 2; mom_details.append(f"MACD 히스토 기울기↑ ({macd_slope:.4f})")
    else:
        mom_details.append(f"MACD 히스토 기울기↓ ({macd_slope:.4f}) ⚠️")
    if 40 <= stoch_k <= 80:
        mom_score += 2; mom_details.append(f"Stoch K={stoch_k:.1f} (중립/긍정)")
    else:
        mom_details.append(f"Stoch K={stoch_k:.1f} (중립/주의)")
    mom_score = min(mom_score, 10)

    vol_score = 0; vol_details = []
    if price_up and vol_ratio_1d >= 1.5:
        vol_score += 4; vol_details.append(f"가격↑ + 거래량 {vol_ratio_1d:.1f}x (강한 매수세) ✅")
    elif not price_up and vol_ratio_1d < 1.2:
        vol_score += 2; vol_details.append(f"가격↓ + 거래량 {vol_ratio_1d:.1f}x (약한 조정)")
    else:
        vol_details.append(f"가격{'↑' if price_up else '↓'} + 거래량 {vol_ratio_1d:.1f}x (보통)")
    if vol_surge >= 1.3:
        vol_score += 3; vol_details.append(f"5일 평균 거래량 {vol_surge:.1f}x (증가 중) ✅")
    else:
        vol_details.append(f"5일 평균 거래량 {vol_surge:.1f}x (보통 이하)")
    if obv_up:
        vol_score += 3; vol_details.append("OBV 5일 상승 추세 ✅")
    vol_score = min(vol_score, 10)

    vola_score = 0; vola_details = []
    if hv20 < 30:
        vola_score += 4; vola_details.append(f"HV20={hv20:.1f}% (저변동성) ✅")
    elif hv20 < 50:
        vola_score += 2; vola_details.append(f"HV20={hv20:.1f}% (보통 변동성)")
    else:
        vola_details.append(f"HV20={hv20:.1f}% (고변동성) ⚠️")
    if bb_pctB < 0.2:
        vola_score += 4; vola_details.append(f"BB %B={bb_pctB:.2f} (과매도 구간) ✅")
    elif bb_pctB < 0.8:
        vola_score += 2; vola_details.append(f"BB %B={bb_pctB:.2f} (중립 구간)")
    else:
        vola_details.append(f"BB %B={bb_pctB:.2f} (과매수 구간) ⚠️")
    vola_details.append(f"ATR={atr_pct:.2f}% → 손절 기준 -{1.5 * atr_pct:.2f}%")
    vola_score = min(vola_score, 10)

    disp_score = 0; disp_details = []
    if -3 <= disp_ma20 <= 5:
        disp_score += 5; disp_details.append(f"이격도(MA20) {disp_ma20:+.1f}% (매수 적정) ✅")
    elif disp_ma20 <= 10:
        disp_score += 3; disp_details.append(f"이격도(MA20) {disp_ma20:+.1f}% (다소 과열)")
    else:
        disp_details.append(f"이격도(MA20) {disp_ma20:+.1f}% (과열 주의)")
    if rebound_1y >= 30:
        disp_score += 5; disp_details.append(f"1년 저점 대비 +{rebound_1y:.1f}% (강한 반등) ✅")
    elif rebound_1y >= 15:
        disp_score += 3; disp_details.append(f"1년 저점 대비 +{rebound_1y:.1f}% (반등 진행)")
    else:
        disp_details.append(f"1년 저점 대비 +{rebound_1y:.1f}% (초기 반등)")
    disp_score = min(disp_score, 10)

    candle_score = 0; candle_details = []
    if big_bull:
        candle_score += 4; candle_details.append("장대양봉 감지 ✅")
    if hammer:
        candle_score += 3; candle_details.append("망치형 캔들 감지 ✅")
    if bullish3:
        candle_score += 3; candle_details.append("3연속 양봉 감지 ✅")
    if not candle_details:
        candle_details.append("특이 캔들 패턴 없음")
    candle_score = min(candle_score, 10)

    weights = {"trend":0.20,"momentum":0.20,"volume":0.15,
               "volatility":0.15,"dispersion":0.15,"candle":0.15}
    scores  = {"trend":trend_score,"momentum":mom_score,"volume":vol_score,
               "volatility":vola_score,"dispersion":disp_score,"candle":candle_score}
    total   = sum(scores[k] * weights[k] for k in weights)
    verdict = "✅ 매수 추천" if total >= 7 else ("🟠 관망 권고" if total >= 5 else "❌ 매수 비권고")

    try:
        info = yf.Ticker(ticker).info
        name = (info.get("longName") or info.get("shortName") or "").strip()[:20]
    except Exception:
        name = ""

    return {
        "ticker": ticker, "name": name,
        "total": round(total, 2), "verdict": verdict,
        "scores": scores, "weights": weights,
        "details": {"trend":trend_details,"momentum":mom_details,"volume":vol_details,
                    "volatility":vola_details,"dispersion":disp_details,"candle":candle_details},
        "golden_cross": {
            "most_recent": most_recent, "days_since_cross": days_since,
            "currently_above": currently_above,
            "ma20_current": float(ma20.iloc[-1]), "ma60_current": float(ma60.iloc[-1]),
            "gap_pct": float((ma20.iloc[-1] / ma60.iloc[-1] - 1) * 100),
            "cross_count": len(gc_dates),
        },
        "extra_signals": {
            "BB_pctB": round(bb_pctB,3), "MACD_slope": round(macd_slope,5),
            "Disp_MA20_pct": round(disp_ma20,2), "Vol_surge_5d": round(vol_surge,2),
            "Hammer": hammer, "Bullish3": bullish3, "BigBull": big_bull,
            "Rebound_1Y_pct": round(rebound_1y,2),
        },
        "last_price": last, "stop_loss": stop_loss, "target": target,
    }


# ── 차트 함수 ──────────────────────────────────────────────
@st.cache_data(ttl=1800, show_spinner=False)
def build_chart(ticker: str):
    if ticker.isdigit() or (ticker[:6].isdigit() and '.' not in ticker):
        ticker = ticker + ".KS"
    df = yf.Ticker(ticker).history(period="1y", auto_adjust=True)
    if df.empty:
        return None
    df = df.copy()
    if df.index.tz is not None:
        df.index = df.index.tz_convert(None)  # Plotly 타임존 호환
    df['MA20'] = df['Close'].rolling(20).mean()
    df['MA60'] = df['Close'].rolling(60).mean()

    prev_ma20 = df['MA20'].shift(1)
    prev_ma60 = df['MA60'].shift(1)
    golden = df[(df['MA20'] > df['MA60']) & (prev_ma20 <= prev_ma60)].copy()
    dead   = df[(df['MA20'] < df['MA60']) & (prev_ma20 >= prev_ma60)].copy()

    fig = make_subplots(rows=2, cols=1, shared_xaxes=True,
                        row_heights=[0.75, 0.25], vertical_spacing=0.03)

    fig.add_trace(go.Candlestick(
        x=df.index, open=df['Open'], high=df['High'],
        low=df['Low'], close=df['Close'], name='주가',
        increasing_line_color='#ef5350', decreasing_line_color='#26a69a',
        increasing_fillcolor='#ef5350', decreasing_fillcolor='#26a69a',
    ), row=1, col=1)
    fig.add_trace(go.Scatter(x=df.index, y=df['MA20'], mode='lines',
        name='MA20', line=dict(color='#42A5F5', width=1.8)), row=1, col=1)
    fig.add_trace(go.Scatter(x=df.index, y=df['MA60'], mode='lines',
        name='MA60', line=dict(color='#EF5350', width=1.8)), row=1, col=1)

    if not golden.empty:
        fig.add_trace(go.Scatter(
            x=golden.index, y=golden['Low'] * 0.982,
            mode='markers+text', name='골든크로스',
            marker=dict(symbol='triangle-up', size=16, color='#FFD600',
                        line=dict(color='#FFF176', width=1)),
            text=['GC'] * len(golden), textposition='bottom center',
            textfont=dict(size=10, color='#FFD600'),
        ), row=1, col=1)
    if not dead.empty:
        fig.add_trace(go.Scatter(
            x=dead.index, y=dead['High'] * 1.018,
            mode='markers+text', name='데드크로스',
            marker=dict(symbol='triangle-down', size=16, color='#CE93D8',
                        line=dict(color='#F3E5F5', width=1)),
            text=['DC'] * len(dead), textposition='top center',
            textfont=dict(size=10, color='#CE93D8'),
        ), row=1, col=1)

    colors = ['#ef5350' if c >= o else '#26a69a'
              for c, o in zip(df['Close'], df['Open'])]
    fig.add_trace(go.Bar(x=df.index, y=df['Volume'], name='거래량',
        marker_color=colors, opacity=0.7, showlegend=False), row=2, col=1)

    shapes, annotations = [], []
    for dt in golden.index:
        shapes.append(dict(type='line', xref='x', yref='paper',
            x0=dt, x1=dt, y0=0, y1=1,
            line=dict(color='#FFD600', width=1.2, dash='dot'), opacity=0.6))
        annotations.append(dict(x=dt, y=1.01, xref='x', yref='paper',
            text='GC', showarrow=False,
            font=dict(size=10, color='#FFD600'),
            bgcolor='rgba(50,50,50,0.7)', borderpad=2))
    for dt in dead.index:
        shapes.append(dict(type='line', xref='x', yref='paper',
            x0=dt, x1=dt, y0=0, y1=1,
            line=dict(color='#CE93D8', width=1.2, dash='dot'), opacity=0.6))
        annotations.append(dict(x=dt, y=1.01, xref='x', yref='paper',
            text='DC', showarrow=False,
            font=dict(size=10, color='#CE93D8'),
            bgcolor='rgba(50,50,50,0.7)', borderpad=2))

    try:
        info = yf.Ticker(ticker).info
        name = info.get("shortName", info.get("longName", ticker))
    except Exception:
        name = ticker

    parts = []
    if len(golden) > 0: parts.append(f"골든크로스 {len(golden)}회")
    if len(dead) > 0:   parts.append(f"데드크로스 {len(dead)}회")
    cross_info = "  |  " + ", ".join(parts) if parts else ""

    fig.update_layout(
        title=dict(text=f"<b>{ticker} ({name})</b> 주가 차트 (1년){cross_info}",
                   font=dict(size=15)),
        template='plotly_dark', height=600,
        legend=dict(orientation='h', y=1.02, x=0),
        margin=dict(l=50, r=20, t=70, b=20),
        xaxis_rangeslider_visible=False,
        shapes=shapes, annotations=annotations,
    )
    fig.update_yaxes(title_text="가격", row=1, col=1)
    fig.update_yaxes(title_text="거래량", row=2, col=1)
    fig.update_xaxes(rangebreaks=[dict(bounds=["sat", "mon"])], row=2, col=1)
    return fig


# ── UI ────────────────────────────────────────────────────
c1, c2, _ = st.columns([2, 1, 3])
with c1:
    ticker_input = st.text_input("종목코드", value="005930",
                                 placeholder="예: 005930 / 035720 / AAPL")
with c2:
    st.markdown("<div style='height:28px'></div>", unsafe_allow_html=True)
    run = st.button("▶ 분석 실행", type="primary", use_container_width=True)

if run and ticker_input.strip():
    with st.spinner(f"{ticker_input.strip()} 분석 중..."):
        try:
            r   = analyze_stock(ticker_input.strip())
            fig = build_chart(ticker_input.strip())
        except Exception as e:
            st.error(f"❌ 오류: {e}")
            st.stop()

    gc = r["golden_cross"]
    ex = r["extra_signals"]
    sc = r["scores"]
    W  = r["weights"]

    name_str = f" ({r['name']})" if r['name'] else ""
    rr_ratio = (r['target'] - r['last_price']) / max(r['last_price'] - r['stop_loss'], 1)
    verdict_color = {"✅": "#2e7d32", "🟠": "#e65100", "❌": "#c62828"}
    v_color = next((c for k, c in verdict_color.items() if r['verdict'].startswith(k)), "#555")

    # ① 종합 요약
    st.markdown(
        f"<div style='margin-bottom:.6rem;'>"
        f"<span style='font-size:1.5rem;font-weight:800;color:#f5f0e8;'>{r['name'] or r['ticker']}</span>"
        f"<span style='font-size:1rem;color:#aaa;margin-left:.6rem;'>{r['ticker']}</span>"
        f"</div>",
        unsafe_allow_html=True
    )
    st.markdown(
        f"<div style='background:{v_color};color:white;padding:.5rem 1rem;"
        f"border-radius:8px;display:inline-block;font-size:1.1rem;font-weight:700;"
        f"margin-bottom:.8rem;'>{r['verdict']}</div>",
        unsafe_allow_html=True
    )
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("종합 매수점수", f"{r['total']} / 10")
    m2.metric("현재가", f"{r['last_price']:,.0f}")
    m3.metric("손절선 (ATR×1.5)", f"{r['stop_loss']:,.0f}")
    m4.metric("목표가 (ATR×3.0)", f"{r['target']:,.0f}")
    st.caption(f"R:R 비율  1 : {rr_ratio:.1f}")

    tab1, tab2, tab3 = st.tabs(["📊 요인별 점수", "📈 주가 차트", "🔍 상세 사유"])

    # ② 요인별 점수
    with tab1:
        factor_labels = [
            ("trend",      "추세"),
            ("momentum",   "모멘텀"),
            ("volume",     "거래량"),
            ("volatility", "변동성"),
            ("dispersion", "이격/반등"),
            ("candle",     "캔들패턴"),
        ]
        rows = []
        for k, lb in factor_labels:
            v  = float(sc[k])
            wt = W[k]
            mark = "✅ 양호" if v >= 7 else ("⚠️ 주의" if v >= 5 else "❌ 부정")
            rows.append({"요인": lb, "가중치": f"{wt:.0%}", "점수": v,
                         "바": "█" * int(v*1.4) + "░" * (14 - int(v*1.4)),
                         "판정": mark})
        df_sc = pd.DataFrame(rows)
        st.dataframe(df_sc, hide_index=True, use_container_width=True)

        st.divider()
        st.markdown("**추가 신호**")
        pctB  = ex['BB_pctB'];    slope = ex['MACD_slope']
        disp  = ex['Disp_MA20_pct']; surge = ex['Vol_surge_5d']
        reb   = ex['Rebound_1Y_pct']
        patterns = [p for p, v in [("장대양봉", ex.get("BigBull")),
                                    ("망치형",   ex.get("Hammer")),
                                    ("3연양봉",  ex.get("Bullish3"))] if v]
        sig_data = {
            "지표":   ["BB %B", "MACD 히스토 기울기", "이격도 MA20", "거래량 Surge(5d)", "캔들 패턴", "1년 저점 반등률"],
            "값":     [f"{pctB:.3f}", f"{slope:.5f}", f"{disp:+.2f}%", f"{surge:.2f}x",
                       ", ".join(patterns) if patterns else "없음", f"{reb:.1f}%"],
            "해석":   [
                "과매도" if pctB < 0.2 else ("과매수" if pctB > 0.8 else "중립"),
                "모멘텀 가속↑" if slope > 0 else "모멘텀 감속↓",
                "매수적정" if -3 <= disp <= 5 else ("다소과열" if disp <= 10 else "과열"),
                "급증" if surge >= 2.0 else ("증가" if surge >= 1.3 else "보통"),
                "반등 신호" if patterns else "해당없음",
                "강한반등" if reb >= 30 else ("반등중" if reb >= 15 else "초기"),
            ],
        }
        st.dataframe(pd.DataFrame(sig_data), hide_index=True, use_container_width=True)

        st.divider()
        st.markdown("**골든크로스 (MA20 / MA60)**")
        gc_d   = gc["most_recent"].strftime("%Y-%m-%d") if gc["most_recent"] else "감지 안됨"
        days_s = f"{gc['days_since_cross']}일 전" if gc["days_since_cross"] else "—"
        gc_data = {
            "항목": ["최근 발생일", "경과일", "총 발생 횟수", "MA20 현재값", "MA60 현재값",
                    "MA20/MA60 괴리율", "MA20 > MA60 상태"],
            "값":   [gc_d, days_s, f"{gc['cross_count']}회",
                    f"{gc['ma20_current']:,.0f}", f"{gc['ma60_current']:,.0f}",
                    f"{gc['gap_pct']:.2f}%",
                    "✅ 유지 중" if gc["currently_above"] else "❌ 이탈"],
        }
        st.dataframe(pd.DataFrame(gc_data), hide_index=True, use_container_width=True)

    # ③ 주가 차트
    with tab2:
        if fig:
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.warning("차트 데이터를 가져올 수 없습니다.")

    # ④ 상세 사유
    with tab3:
        label_map = {"trend":"추세","momentum":"모멘텀","volume":"거래량",
                     "volatility":"변동성","dispersion":"이격/반등","candle":"캔들패턴"}
        for k, lb in label_map.items():
            with st.expander(f"**{lb}** — 점수 {sc[k]}/10"):
                for d in r["details"].get(k, []):
                    st.markdown(f"- {d}")

    st.caption("⚠️ 본 분석은 교육·참고 목적입니다. 실제 투자 결정에 대한 책임은 본인에게 있습니다.")
