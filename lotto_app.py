import streamlit as st
import random
import pandas as pd
import plotly.express as px
from collections import Counter

st.set_page_config(page_title="로또 번호 생성기", page_icon="🎱", layout="wide")

st.markdown("""
<div style="background:linear-gradient(135deg,#1a2a4a,#2d4a8c);
            padding:1.2rem 1.6rem; border-radius:10px; color:#f5f0e8; margin-bottom:1.2rem;">
  <h2 style="margin:0; font-size:1.4rem;">🎱 로또 번호 생성기</h2>
  <p style="margin:0.3rem 0 0; font-size:0.85rem; opacity:0.85;">
    통계적으로 완전 무작위 · 1~45 중 6개 추출
  </p>
</div>
""", unsafe_allow_html=True)

# ── 번호 색상 ─────────────────────────────────────
def ball_color(n):
    if n <= 10:  return "#f5c800"   # 노랑
    elif n <= 20: return "#69c8f2"  # 파랑
    elif n <= 30: return "#ff7272"  # 빨강
    elif n <= 40: return "#aaaaaa"  # 회색
    else:         return "#b0d840"  # 초록

def draw_balls(numbers):
    balls = ""
    for n in sorted(numbers):
        color = ball_color(n)
        balls += f"""
        <span style="
            display:inline-flex; align-items:center; justify-content:center;
            width:48px; height:48px; border-radius:50%;
            background:{color}; color:white; font-weight:bold;
            font-size:1.1rem; margin:4px; box-shadow:2px 2px 6px rgba(0,0,0,0.25);
        ">{n}</span>"""
    return f'<div style="margin:0.5rem 0;">{balls}</div>'

# ── 탭 ───────────────────────────────────────────
tab1, tab2 = st.tabs(["🎱 번호 생성", "📊 통계 분석"])

# ── Tab 1: 번호 생성 ──────────────────────────────
with tab1:
    col1, col2 = st.columns([1, 2])

    with col1:
        n_draws = st.number_input("생성 게임 수", min_value=1, max_value=20, value=5)
        exclude = st.text_input("제외 번호 (쉼표 구분)", placeholder="예: 1, 7, 13")
        gen_btn = st.button("🎱 번호 생성", use_container_width=True, type="primary")

    if gen_btn:
        exclude_nums = set()
        if exclude.strip():
            try:
                exclude_nums = {int(x.strip()) for x in exclude.split(",") if x.strip()}
            except ValueError:
                st.warning("제외 번호는 숫자만 입력하세요.")

        pool = [n for n in range(1, 46) if n not in exclude_nums]

        if len(pool) < 6:
            st.error("제외 번호가 너무 많아 6개를 뽑을 수 없습니다.")
        else:
            st.markdown("### 생성된 번호")
            all_numbers = []
            for i in range(n_draws):
                nums = sorted(random.sample(pool, 6))
                all_numbers.extend(nums)
                st.markdown(f"**{i+1}게임**", unsafe_allow_html=False)
                st.markdown(draw_balls(nums), unsafe_allow_html=True)

            st.session_state["all_numbers"] = all_numbers

# ── Tab 2: 통계 분석 ──────────────────────────────
with tab2:
    st.subheader("번호 구간별 출현 분포")

    n_sim = st.slider("시뮬레이션 횟수", 100, 10000, 1000, step=100)
    sim_btn = st.button("📊 시뮬레이션 실행", use_container_width=True)

    if sim_btn:
        sim_numbers = []
        for _ in range(n_sim):
            sim_numbers.extend(random.sample(range(1, 46), 6))

        counter = Counter(sim_numbers)
        df_freq = pd.DataFrame({
            "번호": list(range(1, 46)),
            "출현횟수": [counter.get(i, 0) for i in range(1, 46)]
        })
        df_freq["구간"] = pd.cut(
            df_freq["번호"],
            bins=[0, 10, 20, 30, 40, 45],
            labels=["1~10", "11~20", "21~30", "31~40", "41~45"]
        )
        color_map = {"1~10":"#f5c800","11~20":"#69c8f2","21~30":"#ff7272","31~40":"#aaaaaa","41~45":"#b0d840"}

        fig = px.bar(
            df_freq, x="번호", y="출현횟수",
            color="구간", color_discrete_map=color_map,
            title=f"{n_sim:,}회 시뮬레이션 번호별 출현 빈도"
        )
        fig.update_layout(
            plot_bgcolor="white", paper_bgcolor="white",
            legend_title="구간", height=380,
            margin=dict(l=10, r=10, t=40, b=10)
        )
        st.plotly_chart(fig, use_container_width=True)

        expected = n_sim * 6 / 45
        st.caption(f"기댓값: 번호당 약 {expected:.1f}회 · 완전 무작위이므로 모든 번호의 확률은 동일합니다.")

        st.info("💡 로또는 독립 시행입니다. 지난 회차 결과가 이번 회차에 영향을 주지 않습니다.")
