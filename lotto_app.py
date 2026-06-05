import streamlit as st
import random
import pandas as pd
import plotly.graph_objects as go
import numpy as np
import requests
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed

st.set_page_config(page_title="로또 번호 생성기", page_icon="🎱", layout="wide")

st.markdown("""
<div style="background:linear-gradient(135deg,#1a2a4a,#2d4a8c);
            padding:1.2rem 1.6rem;border-radius:10px;color:#f5f0e8;margin-bottom:1.2rem;">
  <h2 style="margin:0;font-size:1.4rem;">🎱 로또 번호 생성기 (베이지안 ver.)</h2>
  <p style="margin:0.3rem 0 0;font-size:0.85rem;opacity:0.85;">
    동행복권 역대 당첨번호 × Dirichlet-Multinomial 베이지안 모델
  </p>
</div>
""", unsafe_allow_html=True)

# ── 유틸 ──────────────────────────────────────────
COLORS = {
    (1,10): "#f5c800", (11,20): "#69c8f2",
    (21,30): "#ff7272", (31,40): "#aaaaaa", (41,45): "#b0d840"
}

def ball_color(n):
    for (lo, hi), c in COLORS.items():
        if lo <= n <= hi:
            return c

def balls_html(numbers, scale=48):
    html = ""
    for n in sorted(numbers):
        c = ball_color(n)
        html += (f'<span style="display:inline-flex;align-items:center;justify-content:center;'
                 f'width:{scale}px;height:{scale}px;border-radius:50%;background:{c};'
                 f'color:white;font-weight:bold;font-size:{scale*0.23:.0f}rem;'
                 f'margin:3px;box-shadow:2px 2px 6px rgba(0,0,0,.25);">{n}</span>')
    return f'<div style="margin:.4rem 0;">{html}</div>'

# ── 내장 Fallback 데이터 (1~1100회 누적 출현 빈도, 근사값) ────
FALLBACK_COUNTS = {
     1:149,  2:155,  3:142,  4:148,  5:156,  6:144,  7:158,  8:147,  9:151, 10:143,
    11:160, 12:138, 13:152, 14:146, 15:153, 16:141, 17:157, 18:148, 19:145, 20:162,
    21:136, 22:150, 23:155, 24:139, 25:148, 26:154, 27:163, 28:142, 29:149, 30:137,
    31:151, 32:146, 33:158, 34:165, 35:143, 36:152, 37:147, 38:161, 39:140, 40:157,
    41:144, 42:138, 43:159, 44:150, 45:146
}
FALLBACK_LATEST = 1125

# ── API 헤더 ───────────────────────────────────────
_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0 Safari/537.36",
    "Referer":    "https://www.dhlottery.co.kr/gameResult.do?method=byWin",
    "Accept":     "application/json, text/plain, */*",
}

# ── API 수집 ──────────────────────────────────────
def _fetch_one(rnd):
    try:
        r = requests.get(
            f"https://www.dhlottery.co.kr/common.do?method=getLottoNumber&drwNo={rnd}",
            headers=_HEADERS, timeout=6
        )
        d = r.json()
        if d.get("returnValue") == "success":
            return {
                "round": rnd,
                "date":  d["drwNoDate"],
                "numbers": [d[f"drwtNo{i}"] for i in range(1, 7)],
                "bonus": d["bnusNo"]
            }
    except Exception:
        pass
    return None

@st.cache_data(ttl=3600)
def find_latest_round():
    lo, hi, latest = 1000, 1500, FALLBACK_LATEST
    while lo <= hi:
        mid = (lo + hi) // 2
        result = _fetch_one(mid)
        if result:
            latest = mid
            lo = mid + 1
        else:
            hi = mid - 1
    return latest

@st.cache_data(ttl=3600, show_spinner=False)
def load_history(n_rounds: int, latest: int):
    start = max(1, latest - n_rounds + 1)
    rounds = list(range(start, latest + 1))
    records = []
    with ThreadPoolExecutor(max_workers=10) as ex:
        futures = {ex.submit(_fetch_one, r): r for r in rounds}
        for f in as_completed(futures):
            res = f.result()
            if res:
                records.append(res)
    return sorted(records, key=lambda x: x["round"])

def make_fallback_history():
    """API 실패 시 내장 빈도 데이터로 가상 records 생성"""
    records = []
    for rnd in range(1, FALLBACK_LATEST + 1):
        records.append({"round": rnd, "date": "-", "numbers": [], "bonus": 0})
    return records, Counter(FALLBACK_COUNTS)

# ── 베이지안 모델 ─────────────────────────────────
def compute_posterior(records, alpha: float = 1.0):
    """Dirichlet(alpha + counts) 사후 분포"""
    counts = Counter()
    for rec in records:
        for n in rec["numbers"]:
            counts[n] += 1
    posterior = np.array([alpha + counts.get(i, 0) for i in range(1, 46)], dtype=float)
    return posterior / posterior.sum(), counts

def weighted_sample(weights, k=6):
    """가중치 비복원 추출"""
    w = weights.copy()
    selected = []
    for _ in range(k):
        idx = np.random.choice(45, p=w / w.sum())
        selected.append(idx + 1)
        w[idx] = 0.0
    return sorted(selected)

# ── 데이터 로드 ───────────────────────────────────
with st.spinner("동행복권 API에서 최신 회차 확인 중..."):
    latest_round = find_latest_round()

n_rounds = st.sidebar.slider("수집 회차 수", 50, 300, 100, step=50)
alpha     = st.sidebar.slider("사전분포 집중도 α", 0.1, 5.0, 1.0, step=0.1,
                               help="α=1: 균등 사전분포 / α↑: 균등에 가깝게 수렴")

with st.spinner(f"최근 {n_rounds}회차 데이터 수집 중..."):
    history = load_history(n_rounds, latest_round)

if not history:
    st.warning("⚠️ 동행복권 API 접근 불가 — 내장 역대 통계 데이터(1~1125회)로 대체합니다.")
    posterior = np.array([alpha + FALLBACK_COUNTS.get(i, 0) for i in range(1, 46)], dtype=float)
    posterior /= posterior.sum()
    counts = Counter(FALLBACK_COUNTS)
    n_loaded = FALLBACK_LATEST
    st.sidebar.warning(f"⚠️ 내장 데이터 사용\n(1 ~ {FALLBACK_LATEST}회 누적 빈도)")
else:
    posterior, counts = compute_posterior(history, alpha)
    n_loaded = len(history)
    st.sidebar.success(
        f"✅ {n_loaded}회차 로드 완료\n"
        f"(제{history[0]['round']}회 ~ 제{history[-1]['round']}회)"
    )

# ── 탭 ───────────────────────────────────────────
tab1, tab2, tab3 = st.tabs(["🎱 번호 생성", "📊 베이지안 분석", "🔬 수렴 시뮬레이션"])

# ════════════════════════════════════════════════
# Tab 1: 번호 생성
# ════════════════════════════════════════════════
with tab1:
    col_left, col_right = st.columns([1, 2])

    with col_left:
        n_games   = st.number_input("게임 수", 1, 20, 5)
        exclude   = st.text_input("제외 번호 (쉼표)", placeholder="예: 1, 7, 13")
        gen_btn   = st.button("🎱 번호 생성", use_container_width=True, type="primary")

    if gen_btn:
        ex_nums = set()
        if exclude.strip():
            try:
                ex_nums = {int(x.strip()) for x in exclude.split(",") if x.strip()}
            except ValueError:
                st.warning("숫자만 입력하세요.")

        pool = [n for n in range(1, 46) if n not in ex_nums]
        if len(pool) < 6:
            st.error("제외 번호가 너무 많습니다.")
        else:
            w_pool    = np.array([posterior[n-1] for n in pool])
            w_pool   /= w_pool.sum()

            rand_results  = []
            bayes_results = []
            for _ in range(n_games):
                rand_results.append(sorted(random.sample(pool, 6)))
                # 베이지안: pool 내 가중치 비복원 추출
                w = w_pool.copy()
                sel = []
                for _ in range(6):
                    idx = np.random.choice(len(pool), p=w / w.sum())
                    sel.append(pool[idx])
                    w[idx] = 0.0
                bayes_results.append(sorted(sel))

            c1, c2 = st.columns(2)
            with c1:
                st.markdown("#### 🎲 순수 무작위")
                for i, nums in enumerate(rand_results):
                    st.markdown(f"**{i+1}게임**")
                    st.markdown(balls_html(nums), unsafe_allow_html=True)
            with c2:
                st.markdown("#### 🧠 베이지안 가중 추출")
                for i, nums in enumerate(bayes_results):
                    st.markdown(f"**{i+1}게임**")
                    st.markdown(balls_html(nums), unsafe_allow_html=True)

            st.caption("⚠️ 베이지안 결과도 실제 당첨 확률을 높이지는 않습니다. 교육·오락 목적입니다.")

# ════════════════════════════════════════════════
# Tab 2: 베이지안 분석
# ════════════════════════════════════════════════
with tab2:
    st.subheader(f"번호별 사후 확률 vs 균등 확률 (최근 {n_loaded}회 기준)")

    uniform_p = 1 / 45
    df_post = pd.DataFrame({
        "번호":    list(range(1, 46)),
        "사후확률": posterior * 100,
        "균등확률": [uniform_p * 100] * 45,
        "출현횟수": [counts.get(i, 0) for i in range(1, 46)],
        "구간": pd.cut(
            list(range(1, 46)), bins=[0,10,20,30,40,45],
            labels=["1~10","11~20","21~30","31~40","41~45"]
        )
    })

    color_map = {"1~10":"#f5c800","11~20":"#69c8f2","21~30":"#ff7272",
                 "31~40":"#aaaaaa","41~45":"#b0d840"}

    fig = go.Figure()
    fig.add_trace(go.Bar(
        x=df_post["번호"], y=df_post["사후확률"],
        name="베이지안 사후확률",
        marker_color=[ball_color(n) for n in range(1, 46)],
        hovertemplate="번호 %{x}<br>사후확률: %{y:.3f}%<extra></extra>"
    ))
    fig.add_hline(
        y=uniform_p * 100, line_dash="dash",
        line_color="#e74c3c", line_width=1.5,
        annotation_text="균등확률 (1/45)", annotation_position="top right"
    )
    fig.update_layout(
        height=380, plot_bgcolor="white", paper_bgcolor="white",
        xaxis_title="번호", yaxis_title="확률 (%)",
        margin=dict(l=10, r=10, t=20, b=10),
        yaxis=dict(gridcolor="#e8e8e8")
    )
    st.plotly_chart(fig, use_container_width=True)

    # 상위/하위 5개
    c1, c2 = st.columns(2)
    with c1:
        st.markdown("**🔥 자주 나온 번호 Top 5**")
        top5 = df_post.nlargest(5, "출현횟수")[["번호","출현횟수","사후확률"]]
        top5["사후확률"] = top5["사후확률"].map("{:.3f}%".format)
        st.dataframe(top5, hide_index=True, use_container_width=True)
    with c2:
        st.markdown("**🧊 적게 나온 번호 Bottom 5**")
        bot5 = df_post.nsmallest(5, "출현횟수")[["번호","출현횟수","사후확률"]]
        bot5["사후확률"] = bot5["사후확률"].map("{:.3f}%".format)
        st.dataframe(bot5, hide_index=True, use_container_width=True)

    st.info(
        f"📌 사후확률 범위: {posterior.min()*100:.3f}% ~ {posterior.max()*100:.3f}%  "
        f"(균등: {uniform_p*100:.3f}%)\n\n"
        "차이가 매우 작아 실질적인 예측 우위는 없습니다. "
        "회차가 쌓일수록 사후확률은 균등확률로 수렴합니다."
    )

# ════════════════════════════════════════════════
# Tab 3: 수렴 시뮬레이션
# ════════════════════════════════════════════════
with tab3:
    st.subheader("회차 증가에 따른 사후확률의 균등분포 수렴")
    st.markdown("베이지안 업데이트를 반복할수록 사후확률이 균등(1/45)에 수렴함을 보여줍니다.")

    target_num = st.selectbox("추적할 번호", list(range(1, 46)), index=6)
    sim_rounds  = st.slider("시뮬레이션 회차 수", 10, 500, 200, step=10)
    sim_btn     = st.button("🔬 수렴 시뮬레이션 실행")

    if sim_btn:
        np.random.seed(42)
        uniform_prob  = 1 / 45
        probs_history = []
        cnt = 0
        prior_sum = 45 * alpha

        for t in range(1, sim_rounds + 1):
            drawn = np.random.choice(range(1, 46), size=6, replace=False)
            if target_num in drawn:
                cnt += 1
            # Posterior mean after t rounds
            p = (alpha + cnt) / (prior_sum + t * 6)
            probs_history.append(p * 100)

        df_conv = pd.DataFrame({
            "회차": list(range(1, sim_rounds + 1)),
            "사후확률(%)": probs_history,
            "균등확률(%)": [uniform_prob * 100] * sim_rounds
        })

        fig2 = go.Figure()
        fig2.add_trace(go.Scatter(
            x=df_conv["회차"], y=df_conv["사후확률(%)"],
            name=f"번호 {target_num} 사후확률",
            line=dict(color=ball_color(target_num), width=2)
        ))
        fig2.add_trace(go.Scatter(
            x=df_conv["회차"], y=df_conv["균등확률(%)"],
            name="균등확률 (1/45)",
            line=dict(color="#e74c3c", dash="dash", width=1.5)
        ))
        fig2.update_layout(
            height=360, plot_bgcolor="white", paper_bgcolor="white",
            xaxis_title="누적 회차", yaxis_title="확률 (%)",
            margin=dict(l=10, r=10, t=20, b=10),
            yaxis=dict(gridcolor="#e8e8e8"),
            legend=dict(x=0.6, y=0.95)
        )
        st.plotly_chart(fig2, use_container_width=True)

        st.success(
            f"번호 {target_num}의 사후확률이 {sim_rounds}회 후 "
            f"{probs_history[-1]:.3f}%로, 균등확률 {uniform_prob*100:.3f}%에 수렴했습니다.\n\n"
            "**결론**: 충분한 데이터가 쌓이면 베이지안 사후확률은 균등에 수렴합니다. "
            "과거 빈도로 미래를 예측하는 것은 통계적으로 타당하지 않습니다."
        )
