import streamlit as st
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt

st.set_page_config(page_title="온누리상품권 대시보드", layout="wide")

st.title("📊 온누리상품권 월별 거래액 시뮬레이터")

mean_val = st.slider("📈 월평균 거래액 (단위: 억원)", 100, 1000, 500, 50)
std_val = st.slider("📉 표준편차", 10, 300, 100, 10)

months = [f"{i}월" for i in range(1, 13)]
sim_data = np.random.normal(loc=mean_val, scale=std_val, size=12).clip(min=0)
df = pd.DataFrame({"월": months, "거래액(억원)": sim_data.astype(int)})

fig, ax = plt.subplots()
ax.bar(df["월"], df["거래액(억원)"], color='skyblue')
ax.set_title("온누리상품권 거래액 시뮬레이션")
st.pyplot(fig)

with st.expander("📋 시뮬레이션 데이터"):
    st.dataframe(df)