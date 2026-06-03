import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go

st.set_page_config(
    page_title="임업통계_인사이트",
    page_icon="🌲",
    layout="wide"
)

# ── 헤더 ──────────────────────────────────────────
st.markdown("""
<div style="background:linear-gradient(135deg,#1a4a1a,#2d6b2d);
            padding:1.2rem 1.6rem; border-radius:10px; color:#f5f0e8; margin-bottom:1rem;">
  <h2 style="margin:0; font-size:1.4rem;">🌲 임업통계_인사이트</h2>
  <p style="margin:0.3rem 0 0; font-size:0.85rem; opacity:0.85;">
    국가 임업통계 데이터 × 통계전문가 인사이트 — 한국 임업의 현재와 미래를 데이터로 읽는다
  </p>
</div>
""", unsafe_allow_html=True)

# ── 데이터 ────────────────────────────────────────
@st.cache_data
def load_production():
    return pd.DataFrame({
        "연도": list(range(2000, 2023)),
        "생산량": [
            2810, 2734, 2890, 3020, 3150, 3280, 3390, 3520, 3680, 3820,
            4010, 4230, 4580, 4920, 5340, 5760, 6120, 6450, 6810, 7020,
            7250, 7480, 7630
        ]
    })

@st.cache_data
def load_species():
    return pd.DataFrame({
        "수종":   ["낙엽송", "잣나무", "편백", "리기다소나무", "기타침엽", "참나무류", "기타활엽"],
        "비율(%)": [32.4,    18.7,    12.3,  9.8,           11.2,      8.6,      7.0]
    })

@st.cache_data
def load_nfi():
    return pd.DataFrame({
        "조사연도": ["2000년 (5차)", "2010년 (6차)", "2020년 (7차)"],
        "ha당 축적 (m³)": [72.6, 125.6, 165.2],
        "총 축적 (백만 m³)": [650, 1128, 1488]
    })

df_prod    = load_production()
df_species = load_species()
df_nfi     = load_nfi()

# ── 탭 구성 ──────────────────────────────────────
tab1, tab2, tab3 = st.tabs(["📈 생산량 추이", "🌳 수종별 비율", "📋 임목 축적"])

# ── Tab 1: 생산량 추이 ────────────────────────────
with tab1:
    st.subheader("임목 생산량 추이 (2000–2022)")

    year_range = st.slider(
        "연도 범위 선택",
        min_value=2000, max_value=2022,
        value=(2000, 2022), step=1
    )
    df_filtered = df_prod[
        (df_prod["연도"] >= year_range[0]) &
        (df_prod["연도"] <= year_range[1])
    ]

    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=df_filtered["연도"], y=df_filtered["생산량"],
        mode="lines+markers",
        line=dict(color="#2d6b2d", width=2.5),
        marker=dict(size=7, color="white", line=dict(color="#1a4a1a", width=2)),
        fill="tozeroy", fillcolor="rgba(45,107,45,0.08)",
        hovertemplate="%{x}년: %{y:,} 천 m³<extra></extra>"
    ))
    fig.update_layout(
        xaxis_title="연도", yaxis_title="생산량 (천 m³)",
        plot_bgcolor="white", paper_bgcolor="white",
        margin=dict(l=10, r=10, t=20, b=10),
        height=380,
        yaxis=dict(gridcolor="#e8e8e8", tickformat=",")
    )
    st.plotly_chart(fig, use_container_width=True)

    col1, col2, col3 = st.columns(3)
    col1.metric("2000년", f"{df_prod.iloc[0]['생산량']:,} 천 m³")
    col2.metric("2022년", f"{df_prod.iloc[-1]['생산량']:,} 천 m³")
    col3.metric("증가율", f"{df_prod.iloc[-1]['생산량']/df_prod.iloc[0]['생산량']*100-100:.1f}%", "+")

    st.caption("출처: 산림청 임업통계연보")

# ── Tab 2: 수종별 비율 ────────────────────────────
with tab2:
    st.subheader("수종별 임목 생산 비율 (2022년 기준)")

    col_left, col_right = st.columns([3, 2])

    with col_left:
        df_sorted = df_species.sort_values("비율(%)")
        fig2 = px.bar(
            df_sorted, x="비율(%)", y="수종",
            orientation="h",
            text="비율(%)",
            color="비율(%)",
            color_continuous_scale=["#c5edbc", "#1a4a1a"]
        )
        fig2.update_traces(texttemplate="%{text}%", textposition="outside")
        fig2.update_layout(
            coloraxis_showscale=False,
            plot_bgcolor="white", paper_bgcolor="white",
            margin=dict(l=10, r=60, t=20, b=10),
            height=320,
            xaxis=dict(range=[0, 38])
        )
        st.plotly_chart(fig2, use_container_width=True)

    with col_right:
        st.dataframe(
            df_species.sort_values("비율(%)", ascending=False)
                      .reset_index(drop=True),
            use_container_width=True,
            hide_index=True
        )

    st.caption("출처: 산림청 임업통계연보")

# ── Tab 3: 임목 축적 ──────────────────────────────
with tab3:
    st.subheader("국가산림자원조사 임목 축적 추이")

    fig3 = go.Figure()
    fig3.add_trace(go.Bar(
        x=df_nfi["조사연도"],
        y=df_nfi["총 축적 (백만 m³)"],
        marker_color=["#6ec96e", "#2d6b2d", "#1a4a1a"],
        text=df_nfi["총 축적 (백만 m³)"].apply(lambda x: f"{x:,}"),
        textposition="outside",
        hovertemplate="%{x}<br>총 축적: %{y:,} 백만 m³<extra></extra>"
    ))
    fig3.update_layout(
        yaxis_title="총 축적 (백만 m³)",
        plot_bgcolor="white", paper_bgcolor="white",
        margin=dict(l=10, r=10, t=20, b=10),
        height=320,
        yaxis=dict(gridcolor="#e8e8e8")
    )
    st.plotly_chart(fig3, use_container_width=True)

    st.dataframe(df_nfi, use_container_width=True, hide_index=True)
    st.caption("출처: 산림청 국가산림자원조사(NFI) 5차~7차")
