import streamlit as st
import yfinance as yf
import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import requests
import datetime
import os

try:
    from pykrx import stock as pykrx_stock
    _PYKRX_OK = True
except Exception:
    _PYKRX_OK = False

# ── 주요 한국 종목명 매핑 ─────────────────────────────────
_KR_MAP = {
    # KOSPI 대형주
    "삼성전자":"005930.KS","sk하이닉스":"000660.KS","하이닉스":"000660.KS",
    "현대차":"005380.KS","현대자동차":"005380.KS","기아":"000270.KS","기아차":"000270.KS",
    "lg에너지솔루션":"373220.KS","삼성sdi":"006400.KS","현대모비스":"012330.KS",
    "posco홀딩스":"005490.KS","포스코홀딩스":"005490.KS","포스코":"005490.KS",
    "삼성바이오로직스":"207940.KS","lg화학":"051910.KS","카카오":"035720.KS",
    "네이버":"035420.KS","naver":"035420.KS","삼성물산":"028260.KS",
    "한국전력":"015760.KS","한전":"015760.KS","신한지주":"055550.KS","신한":"055550.KS",
    "kb금융":"105560.KS","하나금융지주":"086790.KS","하나금융":"086790.KS",
    "우리금융지주":"316140.KS","우리금융":"316140.KS","ktg":"033780.KS","kt&g":"033780.KS",
    "sk텔레콤":"017670.KS","skt":"017670.KS","kt":"030200.KS",
    "lg전자":"066570.KS","삼성전기":"009150.KS","셀트리온":"068270.KS",
    "고려아연":"010130.KS","아모레퍼시픽":"090430.KS","아모레":"090430.KS",
    "한화에어로스페이스":"012450.KS","한화에어로":"012450.KS",
    "hd현대":"267250.KS","cj제일제당":"097950.KS","크래프톤":"259960.KS",
    "카카오뱅크":"323410.KS","카카오페이":"377300.KS","lg":"003550.KS",
    "sk이노베이션":"096770.KS","현대건설":"000720.KS","hmm":"011200.KS",
    "두산에너빌리티":"034020.KS","롯데케미칼":"011170.KS","gs":"078930.KS",
    "삼성엔지니어링":"028050.KS","호텔신라":"008770.KS","오리온":"271560.KS",
    "롯데쇼핑":"023530.KS","sk":"034730.KS","lotte":"023530.KS",
    # KOSDAQ
    "에코프로비엠":"247540.KQ","에코프로":"086520.KQ","포스코퓨처엠":"003670.KS",
    "엔씨소프트":"036570.KS","넷마블":"251270.KS","펄어비스":"263750.KQ",
    "카카오게임즈":"293490.KS","하이브":"352820.KS","sm":"041510.KQ",
    "jyp":"035900.KQ","와이지엔터":"122870.KQ","셀트리온헬스케어":"091990.KS",
    "알테오젠":"196170.KQ","리가켐바이오":"141080.KQ","휴젤":"145020.KQ",
}

# ── 종목명 → 티커 변환 ────────────────────────────────────
def resolve_ticker(raw: str) -> str:
    raw = raw.strip()
    has_korean = any('가' <= c <= '힣' for c in raw)
    if not has_korean:
        if raw.isdigit() or (len(raw) >= 6 and raw[:6].isdigit() and '.' not in raw):
            return raw + ".KS"
        return raw  # AAPL 등 해외 티커

    # 매핑 테이블 우선 검색 (소문자 비교)
    key = raw.lower().replace(" ", "")
    if key in _KR_MAP:
        return _KR_MAP[key]

    # 부분 일치 검색
    for k, v in _KR_MAP.items():
        if key in k or k in key:
            return v

    # Yahoo Finance 검색 (fallback)
    try:
        resp = requests.get(
            "https://query2.finance.yahoo.com/v1/finance/search",
            params={"q": raw, "lang": "ko-KR", "region": "KR", "quotesCount": 10},
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=5,
        )
        for q in resp.json().get("quotes", []):
            sym = q.get("symbol", "")
            if sym.endswith(".KS") or sym.endswith(".KQ"):
                return sym
    except Exception:
        pass
    return raw


# ── KRX 전종목 마스터 (코드 ↔ 한글 종목명, 검색 자동완성용) ────
# Streamlit Cloud 등 일부 호스팅 환경에서는 KRX 실시간 조회 자체가 막혀
# pykrx 라이브 호출이 조용히 실패한다. 그래서 라이브 조회를 먼저 시도하되,
# 실패하면 저장소에 함께 배포되는 정적 스냅샷(stock_kr_tickers.csv)으로 폴백한다.
@st.cache_data(ttl=86400, show_spinner=False)
def load_kr_master():
    if _PYKRX_OK:
        try:
            from pykrx.website.krx.market.ticker import StockTicker
            df = StockTicker().listed.copy()[["종목", "시장"]]
            if df is not None and not df.empty:
                return df
        except Exception:
            pass
    try:
        csv_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "stock_kr_tickers.csv")
        df = pd.read_csv(csv_path, dtype={"티커": str}, encoding="utf-8-sig").set_index("티커")
        return df
    except Exception:
        return None


def search_kr_candidates(query: str, master_df, limit: int = 12):
    if master_df is None or master_df.empty or not query:
        return master_df.iloc[0:0] if master_df is not None else None
    matches = master_df[master_df["종목"].str.contains(query, na=False, regex=False)].copy()
    if matches.empty:
        return matches
    matches["exact"] = matches["종목"] == query
    matches["length"] = matches["종목"].str.len()
    matches = matches.sort_values(["exact", "length"], ascending=[False, True])
    return matches.head(limit)


def kr_name_from_master(code: str, master_df):
    if master_df is None or code not in master_df.index:
        return None
    return master_df.loc[code, "종목"]

st.set_page_config(page_title="매수적절성 분석기", page_icon="📊", layout="wide")

st.markdown("""
<div style="background:linear-gradient(135deg,#1a3a2a,#2d6a4f);
            padding:1.2rem 1.6rem;border-radius:10px;color:#f5f0e8;margin-bottom:1.2rem;">
  <h2 style="margin:0;font-size:1.4rem;">📊 매수적절성 분석기 v2</h2>
  <p style="margin:0.3rem 0 0;font-size:0.85rem;opacity:0.85;">
    기술적(추세·모멘텀·거래량·변동성·이격도·캔들) + 펀더멘털·재무건전성·상대강도·수급·애널리스트·유동성·52주위치 — 13개 요인 가중 점수
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
    df = df[df["Close"].notna()]  # 장중 미확정 봉 등으로 마지막 행이 NaN인 경우 제외
    if df.empty:
        raise ValueError(f"유효한 데이터 없음: {ticker}")

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
    gain  = delta.clip(lower=0)
    loss  = (-delta.clip(upper=0))
    avg_gain = gain.ewm(alpha=1/14, adjust=False).mean()  # Wilder's smoothing
    avg_loss = loss.ewm(alpha=1/14, adjust=False).mean()
    rs    = avg_gain / avg_loss.replace(0, np.nan)
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
    high_1y    = float(high.iloc[-252:].max())
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

    # ── 펀더멘털 데이터 (PER·PBR·배당수익률) ────────────────
    try:
        info = yf.Ticker(ticker).info
    except Exception:
        info = {}
    per = info.get("trailingPE")
    pbr = info.get("priceToBook")
    # yfinance는 dividendYield를 이미 퍼센트 단위(예: 2.5 = 2.5%)로 제공한다.
    div_pct = info.get("dividendYield")
    fundamental_available = any(v is not None for v in (per, pbr, div_pct))

    # ── 재무 건전성/수익성 (ROE·부채비율·영업이익률·매출성장률) ──
    roe        = info.get("returnOnEquity")
    d2e        = info.get("debtToEquity")
    op_margin  = info.get("operatingMargins")
    rev_growth = info.get("revenueGrowth")
    financial_health_available = any(v is not None for v in (roe, d2e, op_margin, rev_growth))

    # ── 애널리스트 컨센서스 (목표주가·투자의견) ────────────────
    target_mean   = info.get("targetMeanPrice")
    rec_key       = info.get("recommendationKey")
    num_analysts  = info.get("numberOfAnalystOpinions")
    analyst_available = (target_mean is not None) or (rec_key is not None)

    # ── 공매도/유동성 리스크 ──────────────────────────────────
    short_pct = info.get("shortPercentOfFloat")
    mcap      = info.get("marketCap")
    avg_vol   = info.get("averageVolume") or info.get("averageDailyVolume10Day")
    liquidity_available = any(v is not None for v in (short_pct, mcap, avg_vol))
    is_kr_stock = ticker.endswith(".KS") or ticker.endswith(".KQ")

    # ── 시장 대비 상대강도 (KOSPI/KOSDAQ/S&P500) ──────────────
    if ticker.endswith(".KS"):
        bench_ticker = "^KS11"
    elif ticker.endswith(".KQ"):
        bench_ticker = "^KQ11"
    else:
        bench_ticker = "^GSPC"
    rs_available = False
    rs_20 = rs_60 = None
    try:
        bench = yf.Ticker(bench_ticker).history(period="2y", auto_adjust=True)["Close"].dropna()
        close_valid = close.dropna()
        if len(bench) > 61 and len(close_valid) > 61:
            stock_ret_20 = float(close_valid.iloc[-1] / close_valid.iloc[-21] - 1)
            stock_ret_60 = float(close_valid.iloc[-1] / close_valid.iloc[-61] - 1)
            bench_ret_20 = float(bench.iloc[-1] / bench.iloc[-21] - 1)
            bench_ret_60 = float(bench.iloc[-1] / bench.iloc[-61] - 1)
            rs_20 = (stock_ret_20 - bench_ret_20) * 100
            rs_60 = (stock_ret_60 - bench_ret_60) * 100
            if not (np.isnan(rs_20) or np.isnan(rs_60)):
                rs_available = True
    except Exception:
        pass

    # ── 외국인·기관 수급 (KRX, 국내 종목 한정) ─────────────────
    flow_available = False
    foreign_net_5d = inst_net_5d = foreign_net_20d = inst_net_20d = None
    if _PYKRX_OK and (ticker.endswith(".KS") or ticker.endswith(".KQ")):
        try:
            code = ticker.split(".")[0]
            end_d = datetime.date.today()
            start_d = end_d - datetime.timedelta(days=45)
            flow_df = pykrx_stock.get_market_trading_value_by_date(
                start_d.strftime("%Y%m%d"), end_d.strftime("%Y%m%d"), code
            )
            if flow_df is not None and not flow_df.empty and \
               "외국인합계" in flow_df.columns and "기관합계" in flow_df.columns:
                foreign_net_5d  = float(flow_df["외국인합계"].tail(5).sum())
                inst_net_5d     = float(flow_df["기관합계"].tail(5).sum())
                foreign_net_20d = float(flow_df["외국인합계"].tail(20).sum())
                inst_net_20d    = float(flow_df["기관합계"].tail(20).sum())
                flow_available  = True
        except Exception:
            pass

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

    fundamental_score = 0; fundamental_details = []
    if per is not None:
        if per <= 0:
            fundamental_details.append(f"PER={per:.1f} (적자, 이익 미실현) ⚠️")
        elif per <= 12:
            fundamental_score += 4; fundamental_details.append(f"PER={per:.1f} (저평가 ≤12) ✅")
        elif per <= 20:
            fundamental_score += 2; fundamental_details.append(f"PER={per:.1f} (적정 수준)")
        else:
            fundamental_details.append(f"PER={per:.1f} (고평가 주의)")
    else:
        fundamental_details.append("PER 정보 없음")
    if pbr is not None:
        if pbr < 1:
            fundamental_score += 3; fundamental_details.append(f"PBR={pbr:.2f} (자산가치 대비 저평가) ✅")
        elif pbr < 2:
            fundamental_score += 1; fundamental_details.append(f"PBR={pbr:.2f} (보통)")
        else:
            fundamental_details.append(f"PBR={pbr:.2f} (고평가 주의)")
    else:
        fundamental_details.append("PBR 정보 없음")
    if div_pct is not None:
        if div_pct >= 3:
            fundamental_score += 3; fundamental_details.append(f"배당수익률 {div_pct:.2f}% (고배당) ✅")
        elif div_pct >= 1:
            fundamental_score += 1; fundamental_details.append(f"배당수익률 {div_pct:.2f}% (보통)")
        else:
            fundamental_details.append(f"배당수익률 {div_pct:.2f}% (낮음)")
    else:
        fundamental_details.append("배당 정보 없음")
    if not fundamental_available:
        fundamental_details = ["펀더멘털 데이터를 가져올 수 없습니다 (데이터 제공 제한)"]
    fundamental_score = min(fundamental_score, 10)

    rs_score = 0; rs_details = []
    if rs_available:
        if rs_20 >= 5:
            rs_score += 4; rs_details.append(f"20일 상대강도 {rs_20:+.1f}%p (시장 대비 강세) ✅")
        elif rs_20 >= 0:
            rs_score += 2; rs_details.append(f"20일 상대강도 {rs_20:+.1f}%p (시장과 비슷)")
        else:
            rs_details.append(f"20일 상대강도 {rs_20:+.1f}%p (시장 대비 약세) ⚠️")
        if rs_60 >= 10:
            rs_score += 4; rs_details.append(f"60일 상대강도 {rs_60:+.1f}%p (시장 대비 강세) ✅")
        elif rs_60 >= 0:
            rs_score += 2; rs_details.append(f"60일 상대강도 {rs_60:+.1f}%p (시장과 비슷)")
        else:
            rs_details.append(f"60일 상대강도 {rs_60:+.1f}%p (시장 대비 약세) ⚠️")
        if rs_20 > 0 and rs_60 > 0:
            rs_score += 2; rs_details.append("단기·중기 모두 시장 대비 초과수익 지속 ✅")
    else:
        rs_details.append(f"벤치마크({bench_ticker}) 데이터를 가져올 수 없습니다")
    rs_score = min(rs_score, 10)

    flow_score = 0; flow_details = []
    if flow_available:
        if foreign_net_5d > 0:
            flow_score += 3; flow_details.append(f"외국인 5일 순매수 {foreign_net_5d:,.0f}원 ✅")
        else:
            flow_details.append(f"외국인 5일 순매도 {foreign_net_5d:,.0f}원")
        if inst_net_5d > 0:
            flow_score += 3; flow_details.append(f"기관 5일 순매수 {inst_net_5d:,.0f}원 ✅")
        else:
            flow_details.append(f"기관 5일 순매도 {inst_net_5d:,.0f}원")
        if foreign_net_20d > 0 and inst_net_20d > 0:
            flow_score += 4; flow_details.append("외국인·기관 20일 동반 순매수 (강한 수급) ✅")
        elif foreign_net_20d > 0 or inst_net_20d > 0:
            flow_score += 2; flow_details.append("외국인·기관 중 한쪽만 20일 순매수")
        else:
            flow_details.append("외국인·기관 모두 20일 순매도 ⚠️")
    else:
        reason = "해외 종목" if not (ticker.endswith(".KS") or ticker.endswith(".KQ")) else "KRX 데이터 조회 실패"
        flow_details.append(f"수급 데이터를 가져올 수 없습니다 ({reason})")
    flow_score = min(flow_score, 10)

    fh_score = 0; fh_details = []
    if roe is not None:
        roe_pct = roe * 100
        if roe_pct >= 15:
            fh_score += 3; fh_details.append(f"ROE {roe_pct:.1f}% (우수 ≥15%) ✅")
        elif roe_pct >= 8:
            fh_score += 1; fh_details.append(f"ROE {roe_pct:.1f}% (보통)")
        else:
            fh_details.append(f"ROE {roe_pct:.1f}% (저조) ⚠️")
    else:
        fh_details.append("ROE 정보 없음")
    if d2e is not None:
        if d2e <= 100:
            fh_score += 3; fh_details.append(f"부채비율 {d2e:.0f}% (안정적 ≤100%) ✅")
        elif d2e <= 200:
            fh_score += 1; fh_details.append(f"부채비율 {d2e:.0f}% (보통)")
        else:
            fh_details.append(f"부채비율 {d2e:.0f}% (과다 주의) ⚠️")
    else:
        fh_details.append("부채비율 정보 없음")
    if op_margin is not None:
        op_pct = op_margin * 100
        if op_pct >= 15:
            fh_score += 2; fh_details.append(f"영업이익률 {op_pct:.1f}% (우수) ✅")
        elif op_pct >= 5:
            fh_score += 1; fh_details.append(f"영업이익률 {op_pct:.1f}% (보통)")
        else:
            fh_details.append(f"영업이익률 {op_pct:.1f}% (저조) ⚠️")
    else:
        fh_details.append("영업이익률 정보 없음")
    if rev_growth is not None:
        rg_pct = rev_growth * 100
        if rg_pct >= 10:
            fh_score += 2; fh_details.append(f"매출성장률 {rg_pct:.1f}% (고성장) ✅")
        elif rg_pct >= 0:
            fh_score += 1; fh_details.append(f"매출성장률 {rg_pct:.1f}% (성장 유지)")
        else:
            fh_details.append(f"매출성장률 {rg_pct:.1f}% (역성장) ⚠️")
    else:
        fh_details.append("매출성장률 정보 없음")
    if not financial_health_available:
        fh_details = ["재무 데이터를 가져올 수 없습니다"]
    fh_score = min(fh_score, 10)

    analyst_score = 0; analyst_details = []
    if target_mean is not None and target_mean > 0:
        target_gap = (target_mean - last) / last * 100
        if target_gap >= 15:
            analyst_score += 5; analyst_details.append(f"목표주가 대비 상승여력 +{target_gap:.1f}% (매력적) ✅")
        elif target_gap >= 0:
            analyst_score += 3; analyst_details.append(f"목표주가 대비 상승여력 +{target_gap:.1f}%")
        else:
            analyst_details.append(f"목표주가 대비 {target_gap:.1f}% (목표가 하회) ⚠️")
    else:
        target_gap = None
        analyst_details.append("목표주가 정보 없음")
    if rec_key is not None:
        rk = rec_key.lower()
        opinions = f"{num_analysts}명" if num_analysts else "?명"
        if rk in ("strong_buy", "buy"):
            analyst_score += 5; analyst_details.append(f"투자의견: {rec_key} (긍정적, 분석가 {opinions}) ✅")
        elif rk == "hold":
            analyst_score += 2; analyst_details.append(f"투자의견: {rec_key} (중립)")
        else:
            analyst_details.append(f"투자의견: {rec_key} (부정적) ⚠️")
    else:
        analyst_details.append("투자의견 정보 없음")
    if not analyst_available:
        analyst_details = ["애널리스트 컨센서스 데이터를 가져올 수 없습니다"]
    analyst_score = min(analyst_score, 10)

    liq_score = 0; liq_details = []
    trade_value = None
    if short_pct is not None:
        sp = short_pct * 100
        if sp < 2:
            liq_score += 3; liq_details.append(f"공매도 비중 {sp:.2f}% (부담 낮음) ✅")
        elif sp < 5:
            liq_score += 1; liq_details.append(f"공매도 비중 {sp:.2f}% (보통)")
        else:
            liq_details.append(f"공매도 비중 {sp:.2f}% (높음, 변동성 확대 우려) ⚠️")
    else:
        liq_details.append("공매도 비중 정보 없음")
    if avg_vol is not None:
        trade_value = avg_vol * last
        vol_hi, vol_lo, unit = (5e10, 5e9, "억원") if is_kr_stock else (5e7, 5e6, "달러")
        disp_val = trade_value / 1e8 if is_kr_stock else trade_value / 1e6
        if trade_value >= vol_hi:
            liq_score += 4; liq_details.append(f"평균 거래대금 {disp_val:,.0f}{unit} (유동성 풍부) ✅")
        elif trade_value >= vol_lo:
            liq_score += 2; liq_details.append(f"평균 거래대금 {disp_val:,.0f}{unit} (보통)")
        else:
            liq_details.append(f"평균 거래대금 {disp_val:,.1f}{unit} (유동성 부족 주의) ⚠️")
    else:
        liq_details.append("거래대금 정보 없음")
    if mcap is not None:
        cap_hi, cap_lo, unit = (1e13, 1e12, "조원") if is_kr_stock else (1e11, 1e10, "억달러")
        disp_cap = mcap / 1e12 if is_kr_stock else mcap / 1e8
        if mcap >= cap_hi:
            liq_score += 3; liq_details.append(f"시가총액 {disp_cap:,.1f}{unit} (대형주 안정성) ✅")
        elif mcap >= cap_lo:
            liq_score += 1; liq_details.append(f"시가총액 {disp_cap:,.1f}{unit} (중형주)")
        else:
            liq_details.append(f"시가총액 {disp_cap:,.1f}{unit} (중소형주, 변동성 유의) ⚠️")
    else:
        liq_details.append("시가총액 정보 없음")
    if not liquidity_available:
        liq_details = ["시가총액·거래대금 데이터를 가져올 수 없습니다"]
    liq_score = min(liq_score, 10)

    gap_high52 = (last - high_1y) / high_1y * 100
    gap_low52  = (last - low_1y) / low_1y * 100
    high52_score = 0; high52_details = []
    if -15 <= gap_high52 <= -3:
        high52_score += 5; high52_details.append(f"52주 고점 대비 {gap_high52:.1f}% (건전한 조정 구간, 매수 매력적) ✅")
    elif -3 < gap_high52 <= 0:
        high52_score += 3; high52_details.append(f"52주 고점 대비 {gap_high52:.1f}% (신고가 근접, 돌파 시도)")
    elif -30 <= gap_high52 < -15:
        high52_score += 2; high52_details.append(f"52주 고점 대비 {gap_high52:.1f}% (조정 진행 중)")
    else:
        high52_details.append(f"52주 고점 대비 {gap_high52:.1f}% (큰 폭 하락, 추세 훼손 우려) ⚠️")
    if gap_low52 >= 20:
        high52_score += 5; high52_details.append(f"52주 저점 대비 +{gap_low52:.1f}% (바닥 탈출 확인) ✅")
    elif gap_low52 >= 5:
        high52_score += 3; high52_details.append(f"52주 저점 대비 +{gap_low52:.1f}% (반등 진행)")
    else:
        high52_details.append(f"52주 저점 대비 +{gap_low52:.1f}% (저점권 근접)")
    high52_score = min(high52_score, 10)

    # 13개 요인 가중치 — 데이터를 가져오지 못한 요인은 제외하고
    # 남은 요인들의 가중치를 재정규화한다.
    weights = {"trend":0.12,"momentum":0.12,"volume":0.08,
               "volatility":0.08,"dispersion":0.07,"candle":0.05,
               "fundamental":0.09,"financial_health":0.09,
               "relative_strength":0.08,"flow":0.08,
               "analyst":0.06,"liquidity":0.04,"high52":0.04}
    scores  = {"trend":trend_score,"momentum":mom_score,"volume":vol_score,
               "volatility":vola_score,"dispersion":disp_score,"candle":candle_score,
               "fundamental":fundamental_score,"financial_health":fh_score,
               "relative_strength":rs_score,"flow":flow_score,
               "analyst":analyst_score,"liquidity":liq_score,"high52":high52_score}
    availability = {"trend":True,"momentum":True,"volume":True,"volatility":True,
                     "dispersion":True,"candle":True,
                     "fundamental":fundamental_available,"financial_health":financial_health_available,
                     "relative_strength":rs_available,"flow":flow_available,
                     "analyst":analyst_available,"liquidity":liquidity_available,"high52":True}
    active_sum  = sum(w for k, w in weights.items() if availability[k]) or 1.0
    norm_weights = {k: (w / active_sum if availability[k] else 0.0) for k, w in weights.items()}
    total   = sum(scores[k] * norm_weights[k] for k in weights)
    verdict = "✅ 매수 추천" if total >= 7 else ("🟠 관망 권고" if total >= 5 else "❌ 매수 비권고")

    name = None
    if is_kr_stock:
        name = kr_name_from_master(ticker.split(".")[0], load_kr_master())
    if not name:
        name = (info.get("longName") or info.get("shortName") or "").strip()[:20]

    return {
        "ticker": ticker, "name": name,
        "total": round(total, 2), "verdict": verdict,
        "scores": scores, "weights": norm_weights,
        "details": {"trend":trend_details,"momentum":mom_details,"volume":vol_details,
                    "volatility":vola_details,"dispersion":disp_details,"candle":candle_details,
                    "fundamental":fundamental_details,"financial_health":fh_details,
                    "relative_strength":rs_details,"flow":flow_details,
                    "analyst":analyst_details,"liquidity":liq_details,"high52":high52_details},
        "fundamentals": {"PER": per, "PBR": pbr, "DivYield_pct": div_pct},
        "financial_health": {"ROE_pct": roe*100 if roe is not None else None,
                              "DebtToEquity_pct": d2e, "OperatingMargin_pct": op_margin*100 if op_margin is not None else None,
                              "RevenueGrowth_pct": rev_growth*100 if rev_growth is not None else None},
        "relative_strength": {"RS_20d_pct": rs_20, "RS_60d_pct": rs_60, "benchmark": bench_ticker},
        "investor_flow": {"Foreign_5d": foreign_net_5d, "Inst_5d": inst_net_5d,
                           "Foreign_20d": foreign_net_20d, "Inst_20d": inst_net_20d},
        "analyst": {"TargetMean": target_mean, "TargetGap_pct": target_gap,
                    "Recommendation": rec_key, "NumAnalysts": num_analysts},
        "liquidity": {"ShortPct": short_pct*100 if short_pct is not None else None,
                      "MarketCap": mcap, "AvgTradeValue": trade_value, "IsKR": is_kr_stock},
        "high52": {"High_1Y": high_1y, "Low_1Y": low_1y,
                   "GapFromHigh_pct": gap_high52, "GapFromLow_pct": gap_low52},
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
    df = df[df["Close"].notna()].copy()
    if df.empty:
        return None
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
kr_master = load_kr_master()

c1, c2, _ = st.columns([2, 1, 3])
with c1:
    ticker_input = st.text_input("종목코드 또는 종목명", value="005930",
                                 placeholder="예: 005930 / 삼성전자 / AAPL")
query_stripped = ticker_input.strip()
has_korean_query = any('가' <= c <= '힣' for c in query_stripped)

candidates = None
if has_korean_query and kr_master is not None:
    candidates = search_kr_candidates(query_stripped, kr_master)

selected_ticker = None
if candidates is not None and len(candidates) > 0:
    if len(candidates) == 1:
        row = candidates.iloc[0]
        selected_ticker = candidates.index[0] + (".KS" if row["시장"] == "STK" else ".KQ")
    else:
        def _fmt_candidate(code, _c=candidates):
            row = _c.loc[code]
            market_label = "코스피" if row["시장"] == "STK" else "코스닥"
            return f"{row['종목']} ({code}) · {market_label}"
        selected_code = st.selectbox(
            f"🔎 '{query_stripped}' 검색 결과 {len(candidates)}건 — 종목을 선택하세요",
            options=list(candidates.index), format_func=_fmt_candidate,
        )
        row = candidates.loc[selected_code]
        selected_ticker = selected_code + (".KS" if row["시장"] == "STK" else ".KQ")

with c2:
    st.markdown("<div style='height:28px'></div>", unsafe_allow_html=True)
    run = st.button("▶ 분석 실행", type="primary", use_container_width=True)

if run and query_stripped:
    resolved = selected_ticker if selected_ticker else resolve_ticker(query_stripped)
    has_korean_resolved = any('가' <= c <= '힣' for c in resolved)
    if has_korean_resolved:
        st.error(
            f"❌ '{ticker_input.strip()}' 종목을 찾지 못했습니다.  \n"
            "**해결 방법**: 종목코드(예: `005380`)를 직접 입력해 주세요.  \n"
            "[KRX 종목코드 조회](http://www.krx.co.kr)"
        )
        st.stop()
    with st.spinner(f"{ticker_input.strip()} ({resolved}) 분석 중..."):
        try:
            r   = analyze_stock(resolved)
            fig = build_chart(resolved)
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
        f"<span style='font-size:1.5rem;font-weight:800;color:#163c2e;'>{r['name'] or r['ticker']}</span>"
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
            ("trend",             "추세"),
            ("momentum",          "모멘텀"),
            ("volume",            "거래량"),
            ("volatility",        "변동성"),
            ("dispersion",        "이격/반등"),
            ("candle",            "캔들패턴"),
            ("fundamental",       "펀더멘털(밸류에이션)"),
            ("financial_health",  "재무건전성"),
            ("relative_strength", "상대강도"),
            ("flow",              "수급"),
            ("analyst",           "애널리스트"),
            ("liquidity",         "공매도/유동성"),
            ("high52",            "52주 위치"),
        ]
        rows = []
        for k, lb in factor_labels:
            v  = float(sc[k])
            wt = W[k]
            if wt == 0:
                mark = "— 데이터없음"
            else:
                mark = "✅ 양호" if v >= 7 else ("⚠️ 주의" if v >= 5 else "❌ 부정")
            rows.append({"요인": lb, "가중치": f"{wt:.0%}", "점수": v,
                         "바": "█" * int(v*1.4) + "░" * (14 - int(v*1.4)),
                         "판정": mark})
        df_sc = pd.DataFrame(rows)
        st.dataframe(df_sc, hide_index=True, use_container_width=True)
        st.caption("가중치는 데이터를 가져오지 못한 요인을 제외하고 재정규화됩니다.")

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

        st.divider()
        st.markdown("**펀더멘털 · 재무건전성**")
        fd = r["fundamentals"]; fh = r["financial_health"]; h52 = r["high52"]
        extra2 = {
            "항목": ["PER", "PBR", "배당수익률", "ROE", "부채비율", "영업이익률", "매출성장률",
                    "52주 고점 대비", "52주 저점 대비"],
            "값": [
                f"{fd['PER']:.1f}" if fd['PER'] is not None else "N/A",
                f"{fd['PBR']:.2f}" if fd['PBR'] is not None else "N/A",
                f"{fd['DivYield_pct']:.2f}%" if fd['DivYield_pct'] is not None else "N/A",
                f"{fh['ROE_pct']:.1f}%" if fh['ROE_pct'] is not None else "N/A",
                f"{fh['DebtToEquity_pct']:.0f}%" if fh['DebtToEquity_pct'] is not None else "N/A",
                f"{fh['OperatingMargin_pct']:.1f}%" if fh['OperatingMargin_pct'] is not None else "N/A",
                f"{fh['RevenueGrowth_pct']:.1f}%" if fh['RevenueGrowth_pct'] is not None else "N/A",
                f"{h52['GapFromHigh_pct']:.1f}%",
                f"+{h52['GapFromLow_pct']:.1f}%",
            ],
        }
        st.dataframe(pd.DataFrame(extra2), hide_index=True, use_container_width=True)

        st.divider()
        st.markdown("**상대강도 · 수급 · 애널리스트 · 유동성**")
        rsd = r["relative_strength"]; fl = r["investor_flow"]
        an  = r["analyst"]; lq = r["liquidity"]
        cap_unit = "조원" if lq["IsKR"] else "억달러"
        cap_val  = (lq["MarketCap"] / 1e12) if lq["IsKR"] else (lq["MarketCap"] / 1e8) if lq["MarketCap"] else None
        extra3 = {
            "항목": [f"상대강도 20일 (vs {rsd['benchmark']})", "상대강도 60일",
                    "외국인 5일 순매수", "기관 5일 순매수",
                    "목표주가 괴리율", "투자의견", "공매도 비중", "시가총액"],
            "값": [
                f"{rsd['RS_20d_pct']:+.1f}%p" if rsd['RS_20d_pct'] is not None else "N/A",
                f"{rsd['RS_60d_pct']:+.1f}%p" if rsd['RS_60d_pct'] is not None else "N/A",
                f"{fl['Foreign_5d']:,.0f}원" if fl['Foreign_5d'] is not None else "N/A",
                f"{fl['Inst_5d']:,.0f}원" if fl['Inst_5d'] is not None else "N/A",
                f"{an['TargetGap_pct']:+.1f}%" if an['TargetGap_pct'] is not None else "N/A",
                an['Recommendation'] or "N/A",
                f"{lq['ShortPct']:.2f}%" if lq['ShortPct'] is not None else "N/A",
                f"{cap_val:,.1f}{cap_unit}" if cap_val is not None else "N/A",
            ],
        }
        st.dataframe(pd.DataFrame(extra3), hide_index=True, use_container_width=True)

    # ③ 주가 차트
    with tab2:
        if fig:
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.warning("차트 데이터를 가져올 수 없습니다.")

    # ④ 상세 사유
    with tab3:
        label_map = {"trend":"추세","momentum":"모멘텀","volume":"거래량",
                     "volatility":"변동성","dispersion":"이격/반등","candle":"캔들패턴",
                     "fundamental":"펀더멘털(밸류에이션)","financial_health":"재무건전성",
                     "relative_strength":"상대강도","flow":"수급",
                     "analyst":"애널리스트","liquidity":"공매도/유동성","high52":"52주 위치"}
        for k, lb in label_map.items():
            with st.expander(f"**{lb}** — 점수 {sc[k]}/10"):
                for d in r["details"].get(k, []):
                    st.markdown(f"- {d}")

    st.caption("⚠️ 본 분석은 교육·참고 목적입니다. 실제 투자 결정에 대한 책임은 본인에게 있습니다.")
