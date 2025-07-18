import streamlit as st
import FinanceDataReader as fdr
from datetime import datetime, timedelta

# 종목 목록
df_krx = fdr.StockListing('KRX')
df_krx = df_krx[['Symbol', 'Name']]

# 사용자 선택
st.title("📈 한국 주식 시세 분석기")
selected_name = st.selectbox("종목 선택", df_krx['Name'].sort_values())
selected_code = df_krx[df_krx['Name'] == selected_name]['Symbol'].values[0]

# 주가 데이터
start = datetime.today() - timedelta(days=30)
df = fdr.DataReader(selected_code, start)

# 출력
st.subheader(f"{selected_name}의 최근 30일 주가")
st.line_chart(df['Close'])