import warnings
warnings.filterwarnings('ignore')

import streamlit as st
import numpy as np
import pandas as pd
import FinanceDataReader as fdr
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import mplfinance as mpf
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed

st.set_page_config(page_title="KRX 매수 추천 스캐너", page_icon="🔍", layout="wide")

st.markdown("""
<div style="background:linear-gradient(135deg,#1a2a6c,#2d5a8c);
            padding:1.2rem 1.6rem;border-radius:10px;color:#f5f0e8;margin-bottom:1.2rem;">
  <h2 style="margin:0;font-size:1.4rem;">🔍 KRX 매수 추천 스캐너</h2>
  <p style="margin:0.3rem 0 0;font-size:0.85rem;opacity:0.85;">
    KRX 전체 종목 × 기술적 분석 12개 지표 × 점수 기반 스캔 (최대 ±24점)
  </p>
</div>
""", unsafe_allow_html=True)

# ── 파라미터 사이드바 ──────────────────────────────────────────
with st.sidebar:
    st.header("⚙️ 스캔 파라미터")
    cutoff      = st.number_input("최소 주가 (원)", value=10_000, step=1_000, min_value=0)
    min_score   = st.slider("매수 추천 컷오프 점수", 1, 20, 10,
                            help="이 점수 이상인 종목만 추천 목록에 표시됩니다.")
    TOP_N       = st.slider("상세 리포트 종목 수", 1, 10, 5)
    min_marcap  = st.number_input("최소 시가총액 (억원)", value=1_000, step=100, min_value=0) * 100_000_000
    min_vol     = st.number_input("최소 거래량", value=30_000, step=10_000, min_value=0)
    max_workers = st.slider("병렬 스레드 수", 5, 20, 10)
    st.caption("⚠️ 전체 스캔은 5~15분 소요됩니다.\n결과는 세션 내 유지됩니다.")

start_date = (datetime.today() - timedelta(days=365)).strftime("%Y-%m-%d")


# ── 점수 계산 (±24점) ──────────────────────────────────────────
def compute_score(df):
    if df is None or len(df) < 70:
        return None
    c, h, l, v = df["Close"], df["High"], df["Low"], df["Volume"]

    ma20  = c.rolling(20).mean()
    ma60  = c.rolling(60).mean()
    ema12 = c.ewm(span=12, adjust=False).mean()
    ema26 = c.ewm(span=26, adjust=False).mean()
    macd  = ema12 - ema26
    sig   = macd.ewm(span=9, adjust=False).mean()

    delta = c.diff()
    gain  = delta.clip(lower=0).rolling(14).mean()
    loss  = (-delta.clip(upper=0)).rolling(14).mean()
    rs    = gain / loss.replace(0, np.nan)
    rsi   = 100 - (100 / (1 + rs))

    low14  = l.rolling(14).min()
    high14 = h.rolling(14).max()
    stk    = (c - low14) / (high14 - low14) * 100

    mb  = c.rolling(20).mean()
    std = c.rolling(20).std()
    ub  = mb + 2 * std
    lb  = mb - 2 * std

    prev_c = c.shift(1)
    tr  = pd.concat([h - l, (h - prev_c).abs(), (l - prev_c).abs()], axis=1).max(axis=1)
    atr = tr.ewm(span=14, adjust=False).mean()

    direction = np.sign(c.diff().fillna(0))
    obv       = (direction * v).cumsum()
    vol_ma20  = v.rolling(20).mean()
    vwap      = (c * v).rolling(20).sum() / v.rolling(20).sum()

    up_move  = h.diff()
    dn_move  = -l.diff()
    plus_dm  = np.where((up_move > dn_move) & (up_move > 0), up_move, 0.0)
    minus_dm = np.where((dn_move > up_move) & (dn_move > 0), dn_move, 0.0)
    tr_s     = pd.Series(tr.values, index=df.index)
    plus_di  = 100 * pd.Series(plus_dm,  index=df.index).ewm(span=14, adjust=False).mean() / tr_s.ewm(span=14, adjust=False).mean()
    minus_di = 100 * pd.Series(minus_dm, index=df.index).ewm(span=14, adjust=False).mean() / tr_s.ewm(span=14, adjust=False).mean()
    dx       = (abs(plus_di - minus_di) / (plus_di + minus_di).replace(0, np.nan)) * 100
    adx      = dx.ewm(span=14, adjust=False).mean()

    if pd.isna(ma60.iloc[-1]) or pd.isna(rsi.iloc[-1]):
        return None

    r1, r2 = -1, -2
    score  = 0

    # ① MA 크로스
    if   ma20.iloc[r1] > ma60.iloc[r1] and ma20.iloc[r2] <= ma60.iloc[r2]: score += 2
    elif ma20.iloc[r1] < ma60.iloc[r1] and ma20.iloc[r2] >= ma60.iloc[r2]: score -= 2
    elif ma20.iloc[r1] > ma60.iloc[r1]:                                      score += 1
    else:                                                                     score -= 1

    # ② MACD 크로스
    if   macd.iloc[r1] > sig.iloc[r1] and macd.iloc[r2] <= sig.iloc[r2]: score += 2
    elif macd.iloc[r1] < sig.iloc[r1] and macd.iloc[r2] >= sig.iloc[r2]: score -= 2
    elif macd.iloc[r1] > sig.iloc[r1]:                                     score += 1
    else:                                                                   score -= 1

    # ③ RSI
    rv = rsi.iloc[r1]
    if rv < 30:   score += 2
    elif rv > 70: score -= 2
    elif rv < 50: score += 1
    else:         score -= 1

    # ④ 스토캐스틱
    kv = stk.iloc[r1]
    if kv < 20:   score += 2
    elif kv > 80: score -= 2

    # ⑤ 볼린저밴드
    cv = c.iloc[r1]
    if   cv < lb.iloc[r1]: score += 2
    elif cv > ub.iloc[r1]: score -= 2
    elif cv < mb.iloc[r1]: score += 1
    else:                  score -= 1

    # ⑥ OBV 5일
    if len(obv) >= 6:
        score += 1 if (obv.iloc[-1] - obv.iloc[-6]) > 0 else -1

    # ⑦ 종가 vs MA20
    score += 1 if cv > ma20.iloc[r1] else -1

    # ⑧ 거래량 급증
    vm = vol_ma20.iloc[r1]
    if vm > 0:
        vr = v.iloc[r1] / vm
        if vr >= 2.0:   score += 2
        elif vr >= 1.5: score += 1
        elif vr < 0.5:  score -= 1

    # ⑨ VWAP
    score += 1 if cv > vwap.iloc[r1] else -1

    # ⑩ ADX
    adx_v = adx.iloc[r1]; pd_v = plus_di.iloc[r1]; md_v = minus_di.iloc[r1]
    if   adx_v > 25 and pd_v > md_v:  score += 2
    elif adx_v > 25 and pd_v <= md_v: score -= 2
    elif adx_v <= 20:                 score -= 1

    # ⑪ 이격도
    gap = (cv - ma20.iloc[r1]) / ma20.iloc[r1] * 100 if ma20.iloc[r1] > 0 else 0
    if   gap < -7:  score += 2
    elif gap < -3:  score += 1
    elif gap > 12:  score -= 2
    elif gap > 6:   score -= 1

    # ⑫ 52주 신고가
    if len(df) >= 252:
        high_52w = h.iloc[-252:-1].max()
        if   cv > high_52w:                      score += 3
        elif cv > high_52w * 0.95:               score += 1
        elif cv < l.iloc[-252:-1].min() * 1.05: score -= 2

    return {
        "score": score, "close": cv, "rsi": rv, "stoch": kv,
        "atr": atr.iloc[r1], "ma20": ma20.iloc[r1], "ma60": ma60.iloc[r1],
    }


# ── 단일 종목 스캔 ─────────────────────────────────────────────
def scan_one(row):
    code = row["Code"]; name = row["Name"]; market = row.get("Market", "")
    try:
        df  = fdr.DataReader(code, start_date)
        res = compute_score(df if not df.empty else None)
        if res is None:
            return None
        atr_pct = res["atr"] / res["close"] * 100 if res["close"] else np.nan
        return {
            "종목코드":      code,
            "종목명":        name,
            "시장":          market,
            "점수":          res["score"],
            "현재가":        round(res["close"]),
            "RSI":           round(res["rsi"],   1),
            "Stoch%K":       round(res["stoch"], 1),
            "ATR%":          round(atr_pct,      2),
            "손절가(-1ATR)": round(res["close"] - res["atr"]),
            "목표가(+2ATR)": round(res["close"] + 2 * res["atr"]),
        }
    except Exception:
        return None


# ── 개별 종목 상세 리포트 (Streamlit 버전) ────────────────────
def show_signal(code, name, market):
    df = fdr.DataReader(code, start_date)
    if df.empty:
        st.warning(f"데이터 없음: {code}")
        return

    df["MA20"]    = df["Close"].rolling(20).mean()
    df["MA60"]    = df["Close"].rolling(60).mean()
    df["EMA12"]   = df["Close"].ewm(span=12, adjust=False).mean()
    df["EMA26"]   = df["Close"].ewm(span=26, adjust=False).mean()
    df["MACD"]    = df["EMA12"] - df["EMA26"]
    df["Signal"]  = df["MACD"].ewm(span=9, adjust=False).mean()

    delta     = df["Close"].diff()
    gain      = delta.clip(lower=0)
    loss      = -delta.clip(upper=0)
    avg_gain  = gain.rolling(14).mean()
    avg_loss  = loss.rolling(14).mean()
    rs        = avg_gain / avg_loss.replace(0, np.nan)
    df["RSI"] = 100 - (100 / (1 + rs))

    low_min       = df["Low"].rolling(14).min()
    high_max      = df["High"].rolling(14).max()
    df["Stoch_K"] = (df["Close"] - low_min) / (high_max - low_min) * 100
    df["Stoch_D"] = df["Stoch_K"].rolling(3).mean()

    df["MB"]  = df["Close"].rolling(20).mean()
    df["STD"] = df["Close"].rolling(20).std()
    df["UB"]  = df["MB"] + 2 * df["STD"]
    df["LB"]  = df["MB"] - 2 * df["STD"]

    prev_close = df["Close"].shift(1)
    tr = pd.concat([df["High"] - df["Low"],
                    (df["High"] - prev_close).abs(),
                    (df["Low"]  - prev_close).abs()], axis=1).max(axis=1)
    df["ATR"]     = tr.ewm(span=14, adjust=False).mean()
    direction     = np.sign(df["Close"].diff().fillna(0))
    df["OBV"]     = (direction * df["Volume"]).cumsum()
    df["Vol_MA20"]= df["Volume"].rolling(20).mean()
    df["VWAP"]    = (df["Close"] * df["Volume"]).rolling(20).sum() / df["Volume"].rolling(20).sum()

    up_move   = df["High"].diff()
    down_move = -df["Low"].diff()
    plus_dm   = np.where((up_move > down_move) & (up_move > 0), up_move, 0.0)
    minus_dm  = np.where((down_move > up_move) & (down_move > 0), down_move, 0.0)
    tr_s      = pd.Series(tr.values, index=df.index)
    plus_di   = 100 * pd.Series(plus_dm,  index=df.index).ewm(span=14, adjust=False).mean() / tr_s.ewm(span=14, adjust=False).mean()
    minus_di  = 100 * pd.Series(minus_dm, index=df.index).ewm(span=14, adjust=False).mean() / tr_s.ewm(span=14, adjust=False).mean()
    dx        = (abs(plus_di - minus_di) / (plus_di + minus_di).replace(0, np.nan)) * 100
    df["ADX"]      = dx.ewm(span=14, adjust=False).mean()
    df["Plus_DI"]  = plus_di
    df["Minus_DI"] = minus_di

    r  = df.iloc[-1]; r2 = df.iloc[-2]
    score = 0; logs = []

    if r["MA20"] > r["MA60"] and r2["MA20"] <= r2["MA60"]:
        score += 2; logs.append(("▲ MA 골든크로스 발생", "+2", "BUY"))
    elif r["MA20"] < r["MA60"] and r2["MA20"] >= r2["MA60"]:
        score -= 2; logs.append(("▼ MA 데드크로스 발생", "-2", "SELL"))
    elif r["MA20"] > r["MA60"]:
        score += 1; logs.append(("● MA20 > MA60 (상승 추세 유지)", "+1", "BUY"))
    else:
        score -= 1; logs.append(("● MA20 < MA60 (하락 추세 유지)", "-1", "SELL"))

    if r["MACD"] > r["Signal"] and r2["MACD"] <= r2["Signal"]:
        score += 2; logs.append(("▲ MACD 골든크로스 발생", "+2", "BUY"))
    elif r["MACD"] < r["Signal"] and r2["MACD"] >= r2["Signal"]:
        score -= 2; logs.append(("▼ MACD 데드크로스 발생", "-2", "SELL"))
    elif r["MACD"] > r["Signal"]:
        score += 1; logs.append(("● MACD > Signal (상승 모멘텀)", "+1", "BUY"))
    else:
        score -= 1; logs.append(("● MACD < Signal (하락 모멘텀)", "-1", "SELL"))

    rsi = r["RSI"]
    if rsi < 30:   score += 2; logs.append((f"▲ RSI 과매도 ({rsi:.1f} < 30)", "+2", "BUY"))
    elif rsi > 70: score -= 2; logs.append((f"▼ RSI 과매수 ({rsi:.1f} > 70)", "-2", "SELL"))
    elif rsi < 50: score += 1; logs.append((f"● RSI 중립 하단 ({rsi:.1f})", "+1", "BUY"))
    else:          score -= 1; logs.append((f"● RSI 중립 상단 ({rsi:.1f})", "-1", "SELL"))

    stk = r["Stoch_K"]
    if stk < 20:   score += 2; logs.append((f"▲ 스토캐스틱 과매도 (%K={stk:.1f})", "+2", "BUY"))
    elif stk > 80: score -= 2; logs.append((f"▼ 스토캐스틱 과매수 (%K={stk:.1f})", "-2", "SELL"))
    else:                       logs.append((f"● 스토캐스틱 중립 (%K={stk:.1f})", "0", "NEUTRAL"))

    close = r["Close"]; ub = r["UB"]; lb = r["LB"]; mb = r["MB"]
    if close < lb:   score += 2; logs.append((f"▲ 볼린저 하단 이탈 ({close:,.0f} < {lb:,.0f})", "+2", "BUY"))
    elif close > ub: score -= 2; logs.append((f"▼ 볼린저 상단 돌파 ({close:,.0f} > {ub:,.0f})", "-2", "SELL"))
    elif close < mb: score += 1; logs.append(("● 볼린저 중간선 하단 (매수 우위)", "+1", "BUY"))
    else:            score -= 1; logs.append(("● 볼린저 중간선 상단 (매도 우위)", "-1", "SELL"))

    obv_5d = df["OBV"].iloc[-1] - df["OBV"].iloc[-6]
    if obv_5d > 0: score += 1; logs.append((f"▲ OBV 5일 상승 ({obv_5d:+,.0f})", "+1", "BUY"))
    else:          score -= 1; logs.append((f"▼ OBV 5일 하락 ({obv_5d:+,.0f})", "-1", "SELL"))

    if close > r["MA20"]: score += 1; logs.append((f"▲ 종가 > MA20 ({close:,.0f})", "+1", "BUY"))
    else:                 score -= 1; logs.append((f"▼ 종가 < MA20 ({close:,.0f})", "-1", "SELL"))

    vol_ratio = r["Volume"] / r["Vol_MA20"] if r["Vol_MA20"] > 0 else 1.0
    if vol_ratio >= 2.0:   score += 2; logs.append((f"▲ 거래량 급증 ({vol_ratio:.1f}배)", "+2", "BUY"))
    elif vol_ratio >= 1.5: score += 1; logs.append((f"▲ 거래량 증가 ({vol_ratio:.1f}배)", "+1", "BUY"))
    elif vol_ratio < 0.5:  score -= 1; logs.append((f"▼ 거래량 급감 ({vol_ratio:.1f}배)", "-1", "SELL"))
    else:                              logs.append((f"● 거래량 보통 ({vol_ratio:.1f}배)", "0", "NEUTRAL"))

    vwap = r["VWAP"]
    if close > vwap: score += 1; logs.append((f"▲ 종가 > VWAP ({close:,.0f})", "+1", "BUY"))
    else:            score -= 1; logs.append((f"▼ 종가 < VWAP ({close:,.0f})", "-1", "SELL"))

    adx = r["ADX"]; pdi = r["Plus_DI"]; mdi = r["Minus_DI"]
    if adx > 25 and pdi > mdi:   score += 2; logs.append((f"▲ ADX 강한 상승 추세 (ADX={adx:.1f})", "+2", "BUY"))
    elif adx > 25 and pdi <= mdi: score -= 2; logs.append((f"▼ ADX 강한 하락 추세 (ADX={adx:.1f})", "-2", "SELL"))
    elif adx > 20:                             logs.append((f"● ADX 추세 형성 중 (ADX={adx:.1f})", "0", "NEUTRAL"))
    else:                         score -= 1; logs.append((f"▼ ADX 횡보 (ADX={adx:.1f} < 20)", "-1", "SELL"))

    gap_pct = (close - r["MA20"]) / r["MA20"] * 100 if r["MA20"] > 0 else 0
    if gap_pct < -7:   score += 2; logs.append((f"▲ 이격도 낙폭 ({gap_pct:.1f}%)", "+2", "BUY"))
    elif gap_pct < -3: score += 1; logs.append((f"▲ 이격도 하단 ({gap_pct:.1f}%)", "+1", "BUY"))
    elif gap_pct > 12: score -= 2; logs.append((f"▼ 이격도 과열 ({gap_pct:.1f}%)", "-2", "SELL"))
    elif gap_pct > 6:  score -= 1; logs.append((f"▼ 이격도 상단 ({gap_pct:.1f}%)", "-1", "SELL"))
    else:                           logs.append((f"● 이격도 정상 ({gap_pct:.1f}%)", "0", "NEUTRAL"))

    if len(df) >= 252:
        high_52w = df["High"].iloc[-252:-1].max()
        if close > high_52w:
            score += 3; logs.append((f"▲ 52주 신고가 돌파 ({close:,.0f})", "+3", "BUY"))
        elif close > high_52w * 0.95:
            score += 1; logs.append(("▲ 52주 신고가 근접 (95%+)", "+1", "BUY"))
        elif close < df["Low"].iloc[-252:-1].min() * 1.05:
            score -= 2; logs.append(("▼ 52주 신저가 근처", "-2", "SELL"))

    MAX_SCORE = 24
    if   score >= 14: verdict, vcolor, vbg, hbg = "🔴 강한 매수",  "#CC0000", "#FFE0E0", "#CC0000"
    elif score >= 9:  verdict, vcolor, vbg, hbg = "🟠 매수 고려",  "#CC5500", "#FFE8CC", "#CC5500"
    elif score >= 4:  verdict, vcolor, vbg, hbg = "🟡 약한 매수",  "#886600", "#FFF3CC", "#886600"
    elif score >= -3: verdict, vcolor, vbg, hbg = "⬜ 중립 (관망)", "#444444", "#EEEEEE", "#666666"
    elif score >= -8: verdict, vcolor, vbg, hbg = "🟦 약한 매도",  "#003DAA", "#DDEAFF", "#003DAA"
    elif score >=-13: verdict, vcolor, vbg, hbg = "🔵 매도 고려",  "#002288", "#CCDAFF", "#002288"
    else:             verdict, vcolor, vbg, hbg = "🟣 강한 매도",  "#550088", "#EDD8FF", "#550088"

    atr_pct = r["ATR"] / close * 100

    grade_rows = [
        ("🔴 강한 매수",  "14~24",  "#CC0000", "#FFF0F0"),
        ("🟠 매수 고려",  " 9~13",  "#CC5500", "#FFF4EE"),
        ("🟡 약한 매수",  " 4~ 8",  "#886600", "#FFFBEE"),
        ("⬜ 중립",       "-3~ 3",  "#444444", "#F5F5F5"),
        ("🟦 약한 매도",  "-8~-4",  "#003DAA", "#EEF3FF"),
        ("🔵 매도 고려",  "-13~-9", "#002288", "#E8EEFF"),
        ("🟣 강한 매도",  "-24~-14","#550088", "#F5EEFF"),
    ]
    grade_html = "".join([
        f'<tr style="background:{gbg};outline:{"2px solid "+gc if gv==verdict else "none"};">'
        f'<td style="padding:5px 10px;font-size:13px;font-weight:{"900" if gv==verdict else "500"};color:{gc};">{gv}</td>'
        f'<td style="padding:5px 10px;text-align:center;font-size:13px;font-weight:{"900" if gv==verdict else "500"};color:{gc};">{gr}점</td></tr>'
        for gv, gr, gc, gbg in grade_rows
    ])
    rows_html = "".join([
        f'<tr style="background:{"#FFEAEA" if s=="BUY" else "#E0E8FF" if s=="SELL" else "#F5F5F5"};border-bottom:1px solid #CCC;">'
        f'<td style="padding:8px 12px;font-size:14px;color:{"#8B0000" if s=="BUY" else "#00008B" if s=="SELL" else "#333"};font-weight:600;">{msg}</td>'
        f'<td style="padding:8px 12px;text-align:center;font-size:16px;font-weight:800;color:{"#CC0000" if s=="BUY" else "#0033CC" if s=="SELL" else "#666"};">{pts}</td></tr>'
        for msg, pts, s in logs
    ])

    pct = int((score + MAX_SCORE) / (MAX_SCORE * 2) * 100)
    st.markdown(f"""
<div style="font-family:'Malgun Gothic','NanumGothic',sans-serif;
            border:3px solid {vcolor};border-radius:14px;overflow:hidden;
            box-shadow:0 4px 18px rgba(0,0,0,.25);margin:10px 0;">
  <div style="background:{hbg};color:#FFF;padding:14px 18px;">
    <span style="font-size:20px;font-weight:900;">{name}</span>
    <span style="font-size:13px;margin-left:12px;opacity:.9;">
      {market} | {code} | 기준일: {df.index[-1].date()} | 최근 1년
    </span>
  </div>
  <div style="background:{vbg};padding:14px 18px;border-bottom:2px solid {vcolor};">
    <div style="display:flex;align-items:center;gap:16px;flex-wrap:wrap;">
      <span style="font-size:24px;font-weight:900;color:{vcolor};">{verdict}</span>
      <span style="font-size:17px;font-weight:700;">종합 점수:&nbsp;
        <span style="color:{vcolor};font-size:20px;">{score:+d}</span>
        <span style="color:#666;font-size:14px;">&nbsp;/ ±{MAX_SCORE}</span>
      </span>
    </div>
    <div style="margin-top:8px;background:#DDD;border-radius:6px;height:10px;overflow:hidden;">
      <div style="width:{pct}%;height:100%;background:{vcolor};border-radius:6px;"></div>
    </div>
    <div style="margin-top:8px;font-size:13px;color:#222;font-weight:600;">
      현재가 <b style="font-size:15px;">{close:,.0f}원</b>
      &nbsp;|&nbsp; ATR <b>{r['ATR']:,.0f}원</b> ({atr_pct:.1f}%)
      &nbsp;|&nbsp; RSI <b>{rsi:.1f}</b>
      &nbsp;|&nbsp; Stoch %K <b>{stk:.1f}</b>
      &nbsp;|&nbsp; ADX <b>{adx:.1f}</b>
    </div>
  </div>
  <div style="display:flex;align-items:flex-start;">
    <div style="min-width:190px;border-right:2px solid #DDD;">
      <div style="background:#222;color:#FFF;padding:6px 10px;font-size:12px;font-weight:700;">
        📊 등급 구간 (±{MAX_SCORE}점)
      </div>
      <table style="width:100%;border-collapse:collapse;"><tbody>{grade_html}</tbody></table>
    </div>
    <div style="flex:1;">
      <table style="width:100%;border-collapse:collapse;">
        <thead><tr style="background:#333;color:#FFF;">
          <th style="padding:8px 12px;text-align:left;font-size:12px;">📋 조건 (①~⑫)</th>
          <th style="padding:8px 12px;text-align:center;font-size:12px;width:50px;">점수</th>
        </tr></thead>
        <tbody>{rows_html}</tbody>
      </table>
    </div>
  </div>
  <div style="background:#F0F0F0;padding:10px 18px;border-top:2px solid {vcolor};
              font-size:13px;color:#111;font-weight:600;">
    📐 손절가(-1ATR): <b style="color:#CC0000;">{close - r['ATR']:,.0f}원</b>
    &nbsp;|&nbsp; 목표가(+2ATR): <b style="color:#0033CC;">{close + 2*r['ATR']:,.0f}원</b>
  </div>
</div>
""", unsafe_allow_html=True)

    # ── 캔들 차트 (mplfinance) ──────────────────────────────────
    plot_df = df.tail(180).copy()
    ma_s = plot_df["MA20"]; ma_l = plot_df["MA60"]
    gc   = (ma_s.shift(1) <= ma_l.shift(1)) & (ma_s > ma_l)
    dc   = (ma_s.shift(1) >= ma_l.shift(1)) & (ma_s < ma_l)
    gc_y = plot_df["Low"].where(gc)  * 0.97
    dc_y = plot_df["High"].where(dc) * 1.03

    apds = [
        mpf.make_addplot(plot_df["MA20"], color="orange", width=1.2),
        mpf.make_addplot(plot_df["MA60"], color="purple", width=1.2),
        mpf.make_addplot(plot_df["UB"],   color="gray",   width=0.8, linestyle="--"),
        mpf.make_addplot(plot_df["LB"],   color="gray",   width=0.8, linestyle="--"),
        mpf.make_addplot(plot_df["MB"],   color="blue",   width=0.8, linestyle=":"),
        mpf.make_addplot(plot_df["VWAP"], color="cyan",   width=1.0, linestyle="--"),
    ]
    if gc.any():
        apds.append(mpf.make_addplot(gc_y, type="scatter", marker="^", markersize=120, color="red"))
    if dc.any():
        apds.append(mpf.make_addplot(dc_y, type="scatter", marker="v", markersize=120, color="blue"))

    fig1, _ = mpf.plot(
        plot_df, type="candle", style="yahoo",
        addplot=apds, volume=True, figsize=(12, 5),
        title=f"({code}) {name}  ·  MA20/60 · Bollinger · VWAP",
        tight_layout=True, returnfig=True,
    )
    st.pyplot(fig1)
    plt.close(fig1)

    # ── 보조 지표 차트 (RSI / MACD / Stoch / OBV / ADX) ──────────
    fig2, axes = plt.subplots(5, 1, figsize=(12, 11), sharex=True)

    axes[0].plot(plot_df.index, plot_df["RSI"], color="crimson")
    axes[0].axhline(70, color="red",  linestyle="--", linewidth=0.8)
    axes[0].axhline(30, color="blue", linestyle="--", linewidth=0.8)
    axes[0].set_ylabel("RSI"); axes[0].set_ylim(0, 100)
    axes[0].set_title("Secondary Indicators")

    axes[1].plot(plot_df.index, plot_df["MACD"],   label="MACD",   color="black")
    axes[1].plot(plot_df.index, plot_df["Signal"], label="Signal", color="red")
    hist_v = plot_df["MACD"] - plot_df["Signal"]
    axes[1].bar(plot_df.index, hist_v,
                color=["red" if v >= 0 else "blue" for v in hist_v], alpha=0.4)
    axes[1].axhline(0, color="gray", linewidth=0.6)
    axes[1].set_ylabel("MACD"); axes[1].legend(loc="upper left", fontsize=9)
    m_a = plot_df["MACD"]; s_a = plot_df["Signal"]
    mgc = (m_a.shift(1) <= s_a.shift(1)) & (m_a > s_a)
    mdc = (m_a.shift(1) >= s_a.shift(1)) & (m_a < s_a)
    axes[1].scatter(plot_df.index[mgc], m_a[mgc], marker="^", s=100, color="red",  zorder=5)
    axes[1].scatter(plot_df.index[mdc], m_a[mdc], marker="v", s=100, color="blue", zorder=5)

    axes[2].plot(plot_df.index, plot_df["Stoch_K"], label="%K", color="navy")
    axes[2].plot(plot_df.index, plot_df["Stoch_D"], label="%D", color="orange")
    axes[2].axhline(80, color="red",  linestyle="--", linewidth=0.8)
    axes[2].axhline(20, color="blue", linestyle="--", linewidth=0.8)
    axes[2].set_ylabel("Stoch"); axes[2].legend(loc="upper left", fontsize=9)

    axes[3].plot(plot_df.index, plot_df["OBV"], color="teal")
    axes[3].set_ylabel("OBV")

    axes[4].plot(plot_df.index, plot_df["ADX"],      label="ADX", color="black", linewidth=1.5)
    axes[4].plot(plot_df.index, plot_df["Plus_DI"],  label="+DI", color="red",   linewidth=0.9)
    axes[4].plot(plot_df.index, plot_df["Minus_DI"], label="-DI", color="blue",  linewidth=0.9)
    axes[4].axhline(25, color="gray", linestyle="--", linewidth=0.8)
    axes[4].axhline(20, color="gray", linestyle=":",  linewidth=0.6)
    axes[4].set_ylabel("ADX"); axes[4].legend(loc="upper left", fontsize=9)

    plt.tight_layout()
    st.pyplot(fig2)
    plt.close(fig2)


# ══════════════════════════════════════════════════════════════
# Main UI
# ══════════════════════════════════════════════════════════════
if "scan_df" not in st.session_state:
    st.session_state.scan_df  = None
    st.session_state.scan_krx = None

col_btn, col_status = st.columns([2, 8])
run_btn = col_btn.button("🚀 스캔 시작", type="primary", use_container_width=True)

if run_btn:
    with st.spinner("KRX 종목 목록 로딩 중..."):
        krx = fdr.StockListing("KRX")
        krx = krx[krx["Market"] != "KONEX"].copy()
        krx["Close"]  = pd.to_numeric(krx["Close"].astype(str).str.replace(",","",regex=False), errors="coerce")
        krx["Volume"] = pd.to_numeric(krx["Volume"].astype(str).str.replace(",","",regex=False), errors="coerce")
        if "Marcap" in krx.columns:
            krx["Marcap"] = pd.to_numeric(krx["Marcap"].astype(str).str.replace(",","",regex=False), errors="coerce")
            krx = krx[krx["Marcap"] >= min_marcap]
        krx = krx.dropna(subset=["Close","Volume"])
        krx = krx[(krx["Close"] >= cutoff) & (krx["Volume"] >= min_vol)].reset_index(drop=True)

    col_status.info(f"스캔 대상: **{len(krx):,}개** 종목 | 기간: {start_date} ~ 오늘")

    pbar = st.progress(0, text="스캔 준비 중...")
    all_scores = []; completed = 0
    rows_list  = [row for _, row in krx.iterrows()]

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(scan_one, row): row["Code"] for row in rows_list}
        for f in as_completed(futures):
            result = f.result()
            if result:
                all_scores.append(result)
            completed += 1
            pct = completed / len(futures)
            pbar.progress(pct, text=f"스캔 중... {completed}/{len(futures)} ({pct*100:.0f}%)")

    pbar.empty()
    st.session_state.scan_df  = pd.DataFrame(all_scores)
    st.session_state.scan_krx = krx
    errors = len(rows_list) - len(all_scores)
    st.success(f"✅ 스캔 완료 | 유효 {len(all_scores):,}건 | 스킵/오류 {errors}건")

# ── 결과 출력 ──────────────────────────────────────────────────
if st.session_state.scan_df is not None and len(st.session_state.scan_df) > 0:
    all_df = st.session_state.scan_df

    # 등급 구간 안내
    grade_info = [
        ("🔴 강한 매수","14~24점","#CC0000"),("🟠 매수 고려"," 9~13점","#CC5500"),
        ("🟡 약한 매수"," 4~ 8점","#886600"),("⬜ 중립",      "-3~ 3점","#444444"),
        ("🟦 약한 매도","-8~-4점","#003DAA"),("🔵 매도 고려","-13~-9점","#002288"),
        ("🟣 강한 매도","-24~-14점","#550088"),
    ]
    grade_cells = "".join([
        f'<td style="padding:5px 10px;color:{gc};font-weight:700;font-size:13px;">'
        f'{gv}&nbsp;<span style="color:#888;">{gr}</span></td>'
        for gv, gr, gc in grade_info
    ])
    st.markdown(f"""
<div style="font-family:'Malgun Gothic',sans-serif;margin:12px 0 6px 0;">
  <b style="font-size:13px;">📊 등급 구간 (최대 ±24점)</b>
  <table style="border-collapse:collapse;margin-top:4px;background:#FAFAFA;
                border:1px solid #DDD;border-radius:6px;overflow:hidden;">
    <tr>{grade_cells}</tr>
  </table>
</div>
""", unsafe_allow_html=True)

    # 추천 필터링
    rec = (all_df[all_df["점수"] >= min_score]
           .sort_values(["점수","RSI"], ascending=[False,True])
           .reset_index(drop=True))

    if len(rec) == 0:
        st.warning(f"매수 점수 {min_score}점 이상 종목 없음 → 상위 30개 표시")
        rec = (all_df.sort_values(["점수","RSI"], ascending=[False,True])
               .head(30).reset_index(drop=True))
    else:
        st.success(f"🔴 매수 점수 {min_score}점 이상: **{len(rec)}개** 종목")

    st.dataframe(
        rec.style
           .format({"현재가":"{:,}","손절가(-1ATR)":"{:,}","목표가(+2ATR)":"{:,}"})
           .background_gradient(subset=["점수"], cmap="Reds")
           .set_properties(**{"text-align":"center","font-family":"NanumGothic"})
           .set_table_styles([{"selector":"th",
                               "props":[("background","#333"),("color","#fff"),
                                        ("text-align","center")]}]),
        use_container_width=True,
    )

    # 상위 TOP_N 상세 리포트
    if len(rec) > 0:
        st.subheader(f"📈 상위 {TOP_N} 종목 상세 리포트")
        for _, row in rec.head(TOP_N).iterrows():
            with st.expander(
                f"📊 {row['종목명']} ({row['종목코드']})  ·  점수: {row['점수']:+d}  ·  "
                f"RSI: {row['RSI']}  ·  현재가: {row['현재가']:,}원",
                expanded=True,
            ):
                try:
                    show_signal(row["종목코드"], row["종목명"], row["시장"])
                except Exception as e:
                    st.error(f"리포트 실패: {e}")
