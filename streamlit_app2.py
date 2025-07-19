import streamlit as st
import requests
import pandas as pd
from datetime import datetime

# 1. API 키 (필요 시 직접 입력 or st.secrets 사용)
API_KEY = st.secrets["weather"]["api_key"]

# 2. 날짜
today = datetime.today().strftime("%Y%m%d")

# 3. 격자 좌표 (대전 유성구 전민동)
nx, ny = 67, 100

# 4. 사용할 base_times 목록 (기상청 기준)
base_times = ["0200", "0500", "0800", "1100", "1400", "1700", "2000", "2300"]

# 5. 예보 데이터 누적 리스트
all_items = []

# 6. 각 base_time에 대해 요청
for base_time in base_times:
    url = (
        "http://apis.data.go.kr/1360000/VilageFcstInfoService_2.0/getVilageFcst"
        f"?serviceKey={API_KEY}"
        f"&pageNo=1&numOfRows=1000&dataType=JSON"
        f"&base_date={today}&base_time={base_time}"
        f"&nx={nx}&ny={ny}"
    )
    try:
        response = requests.get(url, timeout=5)
        json_data = response.json()
        items = json_data.get("response", {}).get("body", {}).get("items", {}).get("item", [])
        all_items.extend(items)
    except Exception as e:
        st.warning(f"🚨 {base_time} 시 요청 실패: {e}")

# 7. DataFrame 생성 및 필터링
df = pd.DataFrame(all_items)
df = df[df['category'].isin(['T3H', 'REH', 'SKY', 'POP'])]

# 중복 제거 (동일 fcstDate, fcstTime, category)
df = df.drop_duplicates(subset=['fcstDate', 'fcstTime', 'category'])

# 예보시각 만들기
df['예보시각'] = df['fcstTime'].apply(lambda x: f"{x[:2]}:{x[2:]}")
df = df[['예보시각', 'category', 'fcstValue']]

# 피벗 테이블
df_pivot = df.pivot_table(index='예보시각', columns='category', values='fcstValue', aggfunc='first')
df_pivot = df_pivot.rename(columns={
    'T3H': '기온(°C)',
    'REH': '습도(%)',
    'POP': '강수확률(%)',
    'SKY': '하늘상태'
})
df_pivot.index.name = '예보시각'
df_pivot = df_pivot.sort_index()

# 숫자형 변환
numeric_cols = ['기온(°C)', '습도(%)', '강수확률(%)']
df_pivot[numeric_cols] = df_pivot[numeric_cols].apply(pd.to_numeric, errors='coerce')

# 하늘상태 매핑
sky_map = {
    '1': '☀ 맑음',
    '3': '⛅ 구름많음',
    '4': '☁ 흐림'
}
df_pivot['하늘상태'] = df_pivot['하늘상태'].map(sky_map)

# ✅ Streamlit 출력
st.title("🌤️ 대전 유성구 전민동 - 당일 24시간 기상청 예보")

st.subheader("📋 시간대별 예보 테이블")
st.dataframe(df_pivot)

st.subheader("📊 예보 시계열 차트 (기온/습도/강수확률)")
st.line_chart(df_pivot[numeric_cols])