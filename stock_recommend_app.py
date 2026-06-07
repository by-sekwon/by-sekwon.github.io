import warnings
warnings.filterwarnings('ignore')

import numpy as np
import pandas as pd
import FinanceDataReader as fdr
import matplotlib.pyplot as plt
import mplfinance as mpf
from datetime import datetime, timedelta
from IPython.display import HTML, display
from concurrent.futures import ThreadPoolExecutor, as_completed

try:
    from tqdm.notebook import tqdm
except ImportError:
    from tqdm import tqdm


def signal_alert(code, chart=True):
    """
    ─────────────────────────────────────────────────────────────────
    매수 / 매도 시그널 자동화 (조건 기반 점수 알림) + 차트 출력
    데이터 기간: 최근 1년 (고정)
    ─────────────────────────────────────────────────────────────────
    평가 지표 (최대 ±24점):
    ① MA 골든/데드크로스 (MA20 vs MA60)           ±2
    ② MACD 골든/데드크로스 (MACD vs Signal)        ±2
    ③ RSI 과매도(<30) / 과매수(>70)               ±2
    ④ 스토캐스틱 과매도(<20) / 과매수(>80)         ±2
    ⑤ 볼린저밴드 하단 이탈(매수) / 상단 돌파(매도)  ±2
    ⑥ OBV 5일 방향                                ±1
    ⑦ 종가 vs MA20                                ±1
    ⑧ 거래량 급증 (20일 평균 대비)                ±2
    ⑨ VWAP (20일 거래량가중평균)                   ±1
    ⑩ ADX 추세 강도 (14일)                        ±2
    ⑪ 이격도 (종가 vs MA20, %)                    ±2
    ⑫ 52주 신고가 돌파                            ±3
    ─────────────────────────────────────────────────────────────────
    """
    # ── 0) 종목명 ──────────────────────────────────────
    if not hasattr(signal_alert, "_krx"):
        signal_alert._krx = fdr.StockListing("KRX")
    krx = signal_alert._krx
    row = krx.loc[krx["Code"] == code]
    name   = row["Name"].values[0]   if not row.empty else code
    market = row["Market"].values[0] if (not row.empty and "Market" in row.columns) else ""

    # ── 1) 데이터 로드 (최근 1년 고정) ───────────────
    start_date = (datetime.today() - timedelta(days=365)).strftime("%Y-%m-%d")
    df = fdr.DataReader(code, start_date).copy()
    if df.empty:
        print(f"데이터 없음: {code}"); return

    # ── 2) 지표 계산 ──────────────────────────────────
    df["MA20"] = df["Close"].rolling(20).mean()
    df["MA60"] = df["Close"].rolling(60).mean()

    df["EMA12"]  = df["Close"].ewm(span=12, adjust=False).mean()
    df["EMA26"]  = df["Close"].ewm(span=26, adjust=False).mean()
    df["MACD"]   = df["EMA12"] - df["EMA26"]
    df["Signal"] = df["MACD"].ewm(span=9, adjust=False).mean()

    delta    = df["Close"].diff()
    gain     = delta.clip(lower=0)
    loss     = -delta.clip(upper=0)
    avg_gain = gain.rolling(14).mean()
    avg_loss = loss.rolling(14).mean()
    rs       = avg_gain / avg_loss.replace(0, np.nan)
    df["RSI"] = 100 - (100 / (1 + rs))

    low_min  = df["Low"].rolling(14).min()
    high_max = df["High"].rolling(14).max()
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
    df["ATR"] = tr.ewm(span=14, adjust=False).mean()

    direction  = np.sign(df["Close"].diff().fillna(0))
    df["OBV"]  = (direction * df["Volume"]).cumsum()

    df["Vol_MA20"] = df["Volume"].rolling(20).mean()
    df["VWAP"]     = (df["Close"] * df["Volume"]).rolling(20).sum() / df["Volume"].rolling(20).sum()

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

    # ── 3) 최근 값 기반 점수 ──────────────────────────
    r  = df.iloc[-1]
    r2 = df.iloc[-2]
    score = 0
    logs  = []

    # ① MA 크로스
    if r["MA20"] > r["MA60"] and r2["MA20"] <= r2["MA60"]:
        score += 2; logs.append(("▲ MA 골든크로스 발생", "+2", "BUY"))
    elif r["MA20"] < r["MA60"] and r2["MA20"] >= r2["MA60"]:
        score -= 2; logs.append(("▼ MA 데드크로스 발생", "-2", "SELL"))
    elif r["MA20"] > r["MA60"]:
        score += 1; logs.append(("● MA20 > MA60 (상승 추세 유지)", "+1", "BUY"))
    else:
        score -= 1; logs.append(("● MA20 < MA60 (하락 추세 유지)", "-1", "SELL"))

    # ② MACD 크로스
    if r["MACD"] > r["Signal"] and r2["MACD"] <= r2["Signal"]:
        score += 2; logs.append(("▲ MACD 골든크로스 발생", "+2", "BUY"))
    elif r["MACD"] < r["Signal"] and r2["MACD"] >= r2["Signal"]:
        score -= 2; logs.append(("▼ MACD 데드크로스 발생", "-2", "SELL"))
    elif r["MACD"] > r["Signal"]:
        score += 1; logs.append(("● MACD > Signal (상승 모멘텀)", "+1", "BUY"))
    else:
        score -= 1; logs.append(("● MACD < Signal (하락 모멘텀)", "-1", "SELL"))

    # ③ RSI
    rsi = r["RSI"]
    if rsi < 30:
        score += 2; logs.append((f"▲ RSI 과매도 ({rsi:.1f} < 30)", "+2", "BUY"))
    elif rsi > 70:
        score -= 2; logs.append((f"▼ RSI 과매수 ({rsi:.1f} > 70)", "-2", "SELL"))
    elif rsi < 50:
        score += 1; logs.append((f"● RSI 중립 하단 ({rsi:.1f})", "+1", "BUY"))
    else:
        score -= 1; logs.append((f"● RSI 중립 상단 ({rsi:.1f})", "-1", "SELL"))

    # ④ 스토캐스틱
    stk = r["Stoch_K"]
    if stk < 20:
        score += 2; logs.append((f"▲ 스토캐스틱 과매도 (%K={stk:.1f} < 20)", "+2", "BUY"))
    elif stk > 80:
        score -= 2; logs.append((f"▼ 스토캐스틱 과매수 (%K={stk:.1f} > 80)", "-2", "SELL"))
    else:
        logs.append((f"● 스토캐스틱 중립 (%K={stk:.1f})", "0", "NEUTRAL"))

    # ⑤ 볼린저밴드
    close      = r["Close"]
    ub, lb, mb = r["UB"], r["LB"], r["MB"]
    if close < lb:
        score += 2; logs.append((f"▲ 볼린저 하단 이탈 (종가 {close:,.0f} < LB {lb:,.0f})", "+2", "BUY"))
    elif close > ub:
        score -= 2; logs.append((f"▼ 볼린저 상단 돌파 (종가 {close:,.0f} > UB {ub:,.0f})", "-2", "SELL"))
    elif close < mb:
        score += 1; logs.append(("● 볼린저 중간선 하단 (매수 우위)", "+1", "BUY"))
    else:
        score -= 1; logs.append(("● 볼린저 중간선 상단 (매도 우위)", "-1", "SELL"))

    # ⑥ OBV 5일
    obv_5d = df["OBV"].iloc[-1] - df["OBV"].iloc[-6]
    if obv_5d > 0:
        score += 1; logs.append((f"▲ OBV 5일 상승 ({obv_5d:+,.0f})", "+1", "BUY"))
    else:
        score -= 1; logs.append((f"▼ OBV 5일 하락 ({obv_5d:+,.0f})", "-1", "SELL"))

    # ⑦ 종가 vs MA20
    if close > r["MA20"]:
        score += 1; logs.append((f"▲ 종가 > MA20 ({close:,.0f} > {r['MA20']:,.0f})", "+1", "BUY"))
    else:
        score -= 1; logs.append((f"▼ 종가 < MA20 ({close:,.0f} < {r['MA20']:,.0f})", "-1", "SELL"))

    # ⑧ 거래량 급증
    vol_ratio = r["Volume"] / r["Vol_MA20"] if r["Vol_MA20"] > 0 else 1.0
    if vol_ratio >= 2.0:
        score += 2; logs.append((f"▲ 거래량 급증 (평균 대비 {vol_ratio:.1f}배)", "+2", "BUY"))
    elif vol_ratio >= 1.5:
        score += 1; logs.append((f"▲ 거래량 증가 (평균 대비 {vol_ratio:.1f}배)", "+1", "BUY"))
    elif vol_ratio < 0.5:
        score -= 1; logs.append((f"▼ 거래량 급감 (평균 대비 {vol_ratio:.1f}배)", "-1", "SELL"))
    else:
        logs.append((f"● 거래량 보통 (평균 대비 {vol_ratio:.1f}배)", "0", "NEUTRAL"))

    # ⑨ VWAP
    vwap = r["VWAP"]
    if close > vwap:
        score += 1; logs.append((f"▲ 종가 > VWAP ({close:,.0f} > {vwap:,.0f})", "+1", "BUY"))
    else:
        score -= 1; logs.append((f"▼ 종가 < VWAP ({close:,.0f} < {vwap:,.0f})", "-1", "SELL"))

    # ⑩ ADX 추세 강도
    adx      = r["ADX"]
    plus_di  = r["Plus_DI"]
    minus_di = r["Minus_DI"]
    if adx > 25 and plus_di > minus_di:
        score += 2; logs.append((f"▲ ADX 강한 상승 추세 (ADX={adx:.1f}, +DI 우세)", "+2", "BUY"))
    elif adx > 25 and plus_di <= minus_di:
        score -= 2; logs.append((f"▼ ADX 강한 하락 추세 (ADX={adx:.1f}, -DI 우세)", "-2", "SELL"))
    elif adx > 20:
        logs.append((f"● ADX 추세 형성 중 (ADX={adx:.1f})", "0", "NEUTRAL"))
    else:
        score -= 1; logs.append((f"▼ ADX 추세 없음/횡보 (ADX={adx:.1f} < 20)", "-1", "SELL"))

    # ⑪ 이격도 (MA20 기준)
    gap_pct = (close - r["MA20"]) / r["MA20"] * 100 if r["MA20"] > 0 else 0
    if gap_pct < -7:
        score += 2; logs.append((f"▲ 이격도 심한 낙폭 ({gap_pct:.1f}%, 되돌림 기대)", "+2", "BUY"))
    elif gap_pct < -3:
        score += 1; logs.append((f"▲ 이격도 하단 ({gap_pct:.1f}%)", "+1", "BUY"))
    elif gap_pct > 12:
        score -= 2; logs.append((f"▼ 이격도 과열 ({gap_pct:.1f}%, 차익 실현 주의)", "-2", "SELL"))
    elif gap_pct > 6:
        score -= 1; logs.append((f"▼ 이격도 상단 ({gap_pct:.1f}%)", "-1", "SELL"))
    else:
        logs.append((f"● 이격도 정상 ({gap_pct:.1f}%)", "0", "NEUTRAL"))

    # ⑫ 52주 신고가 돌파
    if len(df) >= 252:
        high_52w = df["High"].iloc[-252:-1].max()
        if close > high_52w:
            score += 3; logs.append((f"▲ 52주 신고가 돌파 ({close:,.0f} > {high_52w:,.0f})", "+3", "BUY"))
        elif close > high_52w * 0.95:
            score += 1; logs.append(("▲ 52주 신고가 근접 (95% 이상)", "+1", "BUY"))
        elif close < df["Low"].iloc[-252:-1].min() * 1.05:
            score -= 2; logs.append(("▼ 52주 신저가 근처", "-2", "SELL"))

    # ── 4) 최종 판정 ──────────────────────────────────
    MAX_SCORE = 24
    if score >= 14:
        verdict, vcolor, vbg, hbg = "🔴 강한 매수",  "#CC0000", "#FFE0E0", "#CC0000"
    elif score >= 9:
        verdict, vcolor, vbg, hbg = "🟠 매수 고려",  "#CC5500", "#FFE8CC", "#CC5500"
    elif score >= 4:
        verdict, vcolor, vbg, hbg = "🟡 약한 매수",  "#886600", "#FFF3CC", "#886600"
    elif score >= -3:
        verdict, vcolor, vbg, hbg = "⬜ 중립 (관망)", "#444444", "#EEEEEE", "#666666"
    elif score >= -8:
        verdict, vcolor, vbg, hbg = "🟦 약한 매도",  "#003DAA", "#DDEAFF", "#003DAA"
    elif score >= -13:
        verdict, vcolor, vbg, hbg = "🔵 매도 고려",  "#002288", "#CCDAFF", "#002288"
    else:
        verdict, vcolor, vbg, hbg = "🟣 강한 매도",  "#550088", "#EDD8FF", "#550088"

    atr_pct = r["ATR"] / close * 100

    # ── 5) 등급 구간 테이블 HTML ──────────────────────
    grade_rows = [
        ("🔴 강한 매수",  "14 ~ 24", "#CC0000", "#FFF0F0"),
        ("🟠 매수 고려",  " 9 ~ 13", "#CC5500", "#FFF4EE"),
        ("🟡 약한 매수",  " 4 ~  8", "#886600", "#FFFBEE"),
        ("⬜ 중립 (관망)", "-3 ~  3", "#444444", "#F5F5F5"),
        ("🟦 약한 매도",  "-8 ~ -4", "#003DAA", "#EEF3FF"),
        ("🔵 매도 고려",  "-13 ~ -9","#002288", "#E8EEFF"),
        ("🟣 강한 매도",  "-24 ~-14","#550088", "#F5EEFF"),
    ]
    grade_html = ""
    for gv, gr, gc, gbg in grade_rows:
        fw = "900" if gv == verdict else "500"
        border = f"2px solid {gc}" if gv == verdict else "none"
        grade_html += f"""
        <tr style="background:{gbg}; outline:{border};">
          <td style="padding:6px 12px; font-size:14px; font-weight:{fw}; color:{gc};">{gv}</td>
          <td style="padding:6px 12px; text-align:center; font-size:14px; font-weight:{fw}; color:{gc};">{gr}점</td>
        </tr>"""

    # ── 6) 조건 테이블 HTML ───────────────────────────
    rows_html = ""
    for msg, pts, side in logs:
        if side == "BUY":
            bg, tc, pc = "#FFEAEA", "#8B0000", "#CC0000"
        elif side == "SELL":
            bg, tc, pc = "#E0E8FF", "#00008B", "#0033CC"
        else:
            bg, tc, pc = "#F5F5F5", "#333333", "#666666"
        rows_html += f"""
        <tr style="background:{bg}; border-bottom:1px solid #CCCCCC;">
          <td style="padding:9px 14px; font-size:15px; color:{tc}; font-weight:600;">{msg}</td>
          <td style="padding:9px 14px; text-align:center; font-size:17px; font-weight:800; color:{pc}; min-width:55px;">{pts}</td>
        </tr>"""

    pct  = int((score + MAX_SCORE) / (MAX_SCORE * 2) * 100)
    html = f"""
<div style="font-family:'Malgun Gothic','NanumGothic',sans-serif;
            max-width:720px; border:3px solid {vcolor}; border-radius:14px;
            overflow:hidden; box-shadow:0 4px 18px rgba(0,0,0,0.25); margin:14px 0;">

  <!-- 헤더 -->
  <div style="background:{hbg}; color:#FFFFFF; padding:16px 20px;">
    <span style="font-size:22px; font-weight:900;">{name}</span>
    <span style="font-size:14px; margin-left:12px; opacity:0.90;">
      {market} &nbsp;|&nbsp; {code} &nbsp;|&nbsp; 기준일: {df.index[-1].date()} &nbsp;|&nbsp; 데이터: 최근 1년
    </span>
  </div>

  <!-- 점수 요약 -->
  <div style="background:{vbg}; padding:16px 20px; border-bottom:2px solid {vcolor};">
    <div style="display:flex; align-items:center; gap:16px; flex-wrap:wrap;">
      <span style="font-size:26px; font-weight:900; color:{vcolor};">{verdict}</span>
      <span style="font-size:18px; font-weight:700; color:#111111;">
        종합 점수:&nbsp;
        <span style="color:{vcolor}; font-size:22px;">{score:+d}</span>
        <span style="color:#666666; font-size:15px;">&nbsp;/ ±{MAX_SCORE}</span>
      </span>
    </div>
    <div style="margin-top:10px; background:#DDDDDD; border-radius:6px; height:12px; overflow:hidden;">
      <div style="width:{pct}%; height:100%; background:{vcolor}; border-radius:6px;"></div>
    </div>
    <div style="margin-top:10px; font-size:14px; color:#222222; font-weight:600;">
      현재가&nbsp;<b style="font-size:16px;">{close:,.0f}원</b>
      &nbsp;|&nbsp; ATR&nbsp;<b>{r['ATR']:,.0f}원</b>&nbsp;({atr_pct:.1f}%)
      &nbsp;|&nbsp; RSI&nbsp;<b>{rsi:.1f}</b>
      &nbsp;|&nbsp; Stoch %K&nbsp;<b>{stk:.1f}</b>
      &nbsp;|&nbsp; ADX&nbsp;<b>{adx:.1f}</b>
    </div>
  </div>

  <!-- 등급 구간표 + 조건 테이블 (2단 레이아웃) -->
  <div style="display:flex; align-items:flex-start;">

    <!-- 왼쪽: 등급 구간표 -->
    <div style="min-width:210px; border-right:2px solid #DDDDDD;">
      <div style="background:#222; color:#FFF; padding:7px 12px; font-size:13px; font-weight:700;">
        📊 등급 구간 (최대 ±{MAX_SCORE}점)
      </div>
      <table style="width:100%; border-collapse:collapse;">
        <tbody>{grade_html}</tbody>
      </table>
    </div>

    <!-- 오른쪽: 조건별 점수 -->
    <div style="flex:1;">
      <table style="width:100%; border-collapse:collapse;">
        <thead><tr style="background:#333333; color:#FFFFFF;">
          <th style="padding:9px 14px; text-align:left; font-size:13px;">📋 조건 (①~⑫)</th>
          <th style="padding:9px 14px; text-align:center; font-size:13px; width:55px;">점수</th>
        </tr></thead>
        <tbody>{rows_html}</tbody>
      </table>
    </div>
  </div>

  <!-- ATR 가이드라인 -->
  <div style="background:#F0F0F0; padding:12px 20px; border-top:2px solid {vcolor};
              font-size:14px; color:#111111; font-weight:600;">
    <b>📐 ATR 기반 가이드라인</b><br>
    <span style="margin-left:8px;">
      손절가 (-1xATR): <b style="color:#CC0000;">{close - r['ATR']:,.0f}원</b>
      &nbsp;|&nbsp; 목표가 (+2xATR): <b style="color:#0033CC;">{close + 2*r['ATR']:,.0f}원</b>
    </span>
  </div>
</div>
"""
    display(HTML(html))

    # ── 7) 차트 출력 (chart=True) ─────────────────────
    if chart:
        plot_df = df.tail(180).copy()

        ma_s = plot_df["MA20"]
        ma_l = plot_df["MA60"]
        gc   = (ma_s.shift(1) <= ma_l.shift(1)) & (ma_s > ma_l)
        dc   = (ma_s.shift(1) >= ma_l.shift(1)) & (ma_s < ma_l)
        gc_y = plot_df["Low"].where(gc)  * 0.97
        dc_y = plot_df["High"].where(dc) * 1.03

        apds = [
            mpf.make_addplot(plot_df["MA20"],  color="orange", width=1.2),
            mpf.make_addplot(plot_df["MA60"],  color="purple", width=1.2),
            mpf.make_addplot(plot_df["UB"],    color="gray",   width=0.8, linestyle="--"),
            mpf.make_addplot(plot_df["LB"],    color="gray",   width=0.8, linestyle="--"),
            mpf.make_addplot(plot_df["MB"],    color="blue",   width=0.8, linestyle=":"),
            mpf.make_addplot(plot_df["VWAP"],  color="cyan",   width=1.0, linestyle="--"),
        ]
        if gc.any():
            apds.append(mpf.make_addplot(gc_y, type="scatter", marker="^", markersize=180, color="red"))
        if dc.any():
            apds.append(mpf.make_addplot(dc_y, type="scatter", marker="v", markersize=180, color="blue"))

        mpf.plot(
            plot_df, type="candle", style="yahoo",
            addplot=apds, volume=True, figsize=(12, 6),
            title=f"({code}) {name} · MA20/60 · Bollinger · VWAP",
            tight_layout=True,
        )

        fig, axes = plt.subplots(5, 1, figsize=(12, 12), sharex=True)

        axes[0].plot(plot_df.index, plot_df["RSI"], color="crimson")
        axes[0].axhline(70, color="red",  linestyle="--", linewidth=0.8)
        axes[0].axhline(30, color="blue", linestyle="--", linewidth=0.8)
        axes[0].set_ylabel("RSI"); axes[0].set_ylim(0, 100)
        axes[0].set_title("Secondary Indicators")

        axes[1].plot(plot_df.index, plot_df["MACD"],   label="MACD",   color="black")
        axes[1].plot(plot_df.index, plot_df["Signal"], label="Signal", color="red")
        hist = plot_df["MACD"] - plot_df["Signal"]
        axes[1].bar(plot_df.index, hist,
                    color=["red" if v >= 0 else "blue" for v in hist], alpha=0.4)
        axes[1].axhline(0, color="gray", linewidth=0.6)
        axes[1].set_ylabel("MACD"); axes[1].legend(loc="upper left", fontsize=9)
        m_a = plot_df["MACD"]; s_a = plot_df["Signal"]
        mgc = (m_a.shift(1) <= s_a.shift(1)) & (m_a > s_a)
        mdc = (m_a.shift(1) >= s_a.shift(1)) & (m_a < s_a)
        axes[1].scatter(plot_df.index[mgc], m_a[mgc], marker="^", s=120, color="red",  zorder=5)
        axes[1].scatter(plot_df.index[mdc], m_a[mdc], marker="v", s=120, color="blue", zorder=5)

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
        plt.show()


# ======================================================================
# 전체 KRX 스캔 → 매수 점수 기준 종목 추천 + TOP N 차트 리포트
# ======================================================================

# ── 0) 파라미터 ────────────────────────────────────────────────
cutoff      = 10000                 # 최소 주가 (원)
min_score   = 10                    # 매수 추천 컷오프 (+-24점 체계)
TOP_N       = 5                     # 차트 포함 상세 리포트 출력 개수
MAX_WORKERS = 10                    # 병렬 스레드 수
MIN_MARCAP  = 100_000_000_000       # 최소 시가총액 (1000억원)
MIN_VOLUME  = 30_000                # 최소 거래량 (3만주)

start_date = (datetime.today() - timedelta(days=365)).strftime("%Y-%m-%d")

# ── 1) KRX 종목 리스트 필터링 ─────────────────────────────────
krx = fdr.StockListing("KRX")
krx = krx[krx["Market"] != "KONEX"].copy()

krx["Close"] = pd.to_numeric(
    krx["Close"].astype(str).str.replace(",", "", regex=False), errors="coerce"
)
krx["Volume"] = pd.to_numeric(
    krx["Volume"].astype(str).str.replace(",", "", regex=False), errors="coerce"
)

if "Marcap" in krx.columns:
    krx["Marcap"] = pd.to_numeric(
        krx["Marcap"].astype(str).str.replace(",", "", regex=False), errors="coerce"
    )
    krx = krx[krx["Marcap"] >= MIN_MARCAP]

krx = krx.dropna(subset=["Close", "Volume"])
krx = krx[(krx["Close"] >= cutoff) & (krx["Volume"] >= MIN_VOLUME)].reset_index(drop=True)

print(f"스캔 대상 종목 수: {len(krx):,}  (KONEX 제외 | 주가>={cutoff:,} | 거래량>={MIN_VOLUME:,} | 시총>={MIN_MARCAP//100_000_000}억)")
print(f"데이터 기간: {start_date} ~ 오늘 (최근 1년)")


# ── 2) 경량 점수 계산 함수 (signal_alert 와 동일 로직, +-24점) ──
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
    tr = pd.concat([h - l, (h - prev_c).abs(), (l - prev_c).abs()], axis=1).max(axis=1)
    atr = tr.ewm(span=14, adjust=False).mean()

    direction = np.sign(c.diff().fillna(0))
    obv = (direction * v).cumsum()

    vol_ma20 = v.rolling(20).mean()
    vwap = (c * v).rolling(20).sum() / v.rolling(20).sum()

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
    score = 0

    # ① MA
    if ma20.iloc[r1] > ma60.iloc[r1] and ma20.iloc[r2] <= ma60.iloc[r2]:
        score += 2
    elif ma20.iloc[r1] < ma60.iloc[r1] and ma20.iloc[r2] >= ma60.iloc[r2]:
        score -= 2
    elif ma20.iloc[r1] > ma60.iloc[r1]:
        score += 1
    else:
        score -= 1

    # ② MACD
    if macd.iloc[r1] > sig.iloc[r1] and macd.iloc[r2] <= sig.iloc[r2]:
        score += 2
    elif macd.iloc[r1] < sig.iloc[r1] and macd.iloc[r2] >= sig.iloc[r2]:
        score -= 2
    elif macd.iloc[r1] > sig.iloc[r1]:
        score += 1
    else:
        score -= 1

    # ③ RSI
    rv = rsi.iloc[r1]
    if rv < 30:
        score += 2
    elif rv > 70:
        score -= 2
    elif rv < 50:
        score += 1
    else:
        score -= 1

    # ④ 스토캐스틱
    kv = stk.iloc[r1]
    if kv < 20:
        score += 2
    elif kv > 80:
        score -= 2

    # ⑤ 볼린저밴드
    cv = c.iloc[r1]
    if cv < lb.iloc[r1]:
        score += 2
    elif cv > ub.iloc[r1]:
        score -= 2
    elif cv < mb.iloc[r1]:
        score += 1
    else:
        score -= 1

    # ⑥ OBV 5일
    if len(obv) >= 6:
        score += 1 if (obv.iloc[-1] - obv.iloc[-6]) > 0 else -1

    # ⑦ 종가 vs MA20
    score += 1 if cv > ma20.iloc[r1] else -1

    # ⑧ 거래량 급증
    vm = vol_ma20.iloc[r1]
    if vm > 0:
        vr = v.iloc[r1] / vm
        if vr >= 2.0:
            score += 2
        elif vr >= 1.5:
            score += 1
        elif vr < 0.5:
            score -= 1

    # ⑨ VWAP
    score += 1 if cv > vwap.iloc[r1] else -1

    # ⑩ ADX
    adx_v = adx.iloc[r1]
    pd_v  = plus_di.iloc[r1]
    md_v  = minus_di.iloc[r1]
    if adx_v > 25 and pd_v > md_v:
        score += 2
    elif adx_v > 25 and pd_v <= md_v:
        score -= 2
    elif adx_v <= 20:
        score -= 1

    # ⑪ 이격도
    gap = (cv - ma20.iloc[r1]) / ma20.iloc[r1] * 100 if ma20.iloc[r1] > 0 else 0
    if gap < -7:
        score += 2
    elif gap < -3:
        score += 1
    elif gap > 12:
        score -= 2
    elif gap > 6:
        score -= 1

    # ⑫ 52주 신고가 돌파
    if len(df) >= 252:
        high_52w = h.iloc[-252:-1].max()
        if cv > high_52w:
            score += 3
        elif cv > high_52w * 0.95:
            score += 1
        elif cv < l.iloc[-252:-1].min() * 1.05:
            score -= 2

    return {
        "score": score,
        "close": cv,
        "rsi":   rv,
        "stoch": kv,
        "atr":   atr.iloc[r1],
        "ma20":  ma20.iloc[r1],
        "ma60":  ma60.iloc[r1],
    }


# ── 3) 단일 종목 스캔 함수 ───────────────────────────────────
def scan_one(row):
    code   = row["Code"]
    name   = row["Name"]
    market = row.get("Market", "")
    try:
        df = fdr.DataReader(code, start_date)
        if df.empty:
            return None
        res = compute_score(df)
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


# ── 4) ThreadPoolExecutor 병렬 실행 ───────────────────────────
print(f"\n🚀 병렬 스캔 시작 (workers={MAX_WORKERS}) ...")
all_scores = []
rows_list  = [row for _, row in krx.iterrows()]

with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
    futures = {executor.submit(scan_one, row): row["Code"] for row in rows_list}
    for f in tqdm(as_completed(futures), total=len(futures), desc="스캔중"):
        result = f.result()
        if result:
            all_scores.append(result)

all_df = pd.DataFrame(all_scores)
errors = len(rows_list) - len(all_scores)
print(f"\n✅ 스캔 완료 | 유효 {len(all_df):,}건 | 스킵/오류 {errors}건")

# ── 5) 등급 구간 출력 ──────────────────────────────────────────
grade_info = [
    ("🔴 강한 매수",  "14 ~ 24점", "#CC0000"),
    ("🟠 매수 고려",  " 9 ~ 13점", "#CC5500"),
    ("🟡 약한 매수",  " 4 ~  8점", "#886600"),
    ("⬜ 중립 (관망)", "-3 ~  3점", "#444444"),
    ("🟦 약한 매도",  "-8 ~ -4점", "#003DAA"),
    ("🔵 매도 고려",  "-13 ~ -9점","#002288"),
    ("🟣 강한 매도",  "-24 ~-14점","#550088"),
]
grade_table = "".join([
    f'<td style="padding:5px 10px; color:{gc}; font-weight:700; font-size:13px;">{gv}&nbsp;<span style="color:#888;">{gr}</span></td>'
    for gv, gr, gc in grade_info
])
display(HTML(f"""
<div style="font-family:'Malgun Gothic',sans-serif; margin:10px 0 4px 0;">
  <b style="font-size:14px;">📊 등급 구간 (최대 ±24점)</b>
  <table style="border-collapse:collapse; margin-top:4px; background:#FAFAFA; border:1px solid #DDD; border-radius:6px; overflow:hidden;">
    <tr>{grade_table}</tr>
  </table>
</div>
"""))

# ── 6) 매수 점수 >= min_score 추천 / 없으면 상위 30개 ──────────
if len(all_df) == 0:
    display(HTML("<div style='padding:14px;background:#EEE;border-radius:8px;"
                 "font-family:NanumGothic;'>데이터가 없습니다.</div>"))
    rec = pd.DataFrame()
else:
    rec = (all_df[all_df["점수"] >= min_score]
           .sort_values(["점수", "RSI"], ascending=[False, True])
           .reset_index(drop=True))

    if len(rec) == 0:
        print(f"\n⚠️ 매수 점수 {min_score}점 이상 종목이 없습니다. 상위 30개를 대신 표시합니다.")
        display(HTML(
            "<div style='padding:14px;background:#FFF4E5;border:2px solid #CC8800;"
            "border-radius:10px;font-family:NanumGothic;font-size:15px;color:#663300;'>"
            f"🔎 <b>매수 점수 {min_score}점 이상 종목이 없습니다.</b><br>"
            "조건을 완화하려면 <code>min_score</code> 값을 낮춰 재실행하세요. "
            "아래는 <b>점수 상위 30종목</b>입니다."
            "</div>"
        ))
        rec = (all_df.sort_values(["점수", "RSI"], ascending=[False, True])
               .head(30)
               .reset_index(drop=True))
    else:
        print(f"🔴 매수 점수 {min_score}점 이상 종목: {len(rec)}개\n")

    display(
        rec.style
        .format({"현재가": "{:,}", "손절가(-1ATR)": "{:,}", "목표가(+2ATR)": "{:,}"})
        .background_gradient(subset=["점수"], cmap="Reds")
        .set_properties(**{"text-align": "center", "font-family": "NanumGothic"})
        .set_table_styles([{"selector": "th",
                            "props": [("background", "#333"), ("color", "#fff"),
                                      ("text-align", "center")]}])
    )

# ── 7) TOP_N 종목 상세 리포트 (HTML + 차트) ───────────────────
if len(rec) > 0:
    print(f"\n📊 상위 {TOP_N} 종목 상세 리포트 + 차트")
    for code in rec["종목코드"].head(TOP_N):
        try:
            signal_alert(code, chart=True)
        except Exception as e:
            print(f"{code} 상세 리포트 실패: {e}")
