import streamlit as st
import FinanceDataReader as fdr
from datetime import datetime, timedelta
import pandas as pd

# 수동 종목 리스트 정의
data = {
    "Name": ["삼성전자", "네이버", "카카오", "현대자동차", "SK텔레콤"],
    "Symbol": ["005930", "035420", "035720", "005380", "017670"]
}
df_krx = pd.DataFrame(data)

# Streamlit UI
st.title("📈 한국 주식 시세 분석기")
selected_name = st.selectbox("종목 선택", df_krx["Name"])
selected_code = df_krx[df_krx["Name"] == selected_name]["Symbol"].values[0]

# 주가 데이터
start = datetime.today() - timedelta(days=90)
df_price = fdr.DataReader(selected_code, start)

st.subheader(f"{selected_name}의 최근 30일 종가")
st.line_chart(df_price['Close'])
