import streamlit as st
import requests
import pandas as pd
from datetime import datetime

# 1. API 키 (Streamlit secrets)
API_KEY = st.secrets["weather"]["api_key"]

# 2. 날짜와 시각
now = datetime.now()
today = now.strftime("%Y%m%d")
current_time = now.strftime("%H:%M")
base_time = "0500"

# 3. 대전 유성구 전민동 격자
nx, ny = 67, 100

# 4. API 호출
url = (
    "http://apis.data.go.kr/1360000/VilageFcstInfoService_2.0/getVilageFcst"
    f"?serviceKey={API_KEY}&pageNo=1&numOfRows=1000&dataType=JSON"
    f"&base_date={today}&base_time={base_time}&nx={nx}&ny={ny}"
)

try:
    response = requests.get(url, timeout=5)
    items = response.json().get("response", {}).get("body", {}).get("items", {}).get("item", [])
except Exception as e:
    st.error(f"⛔ API 호출 실패: {e}")
    st.stop()

# 5. 데이터프레임 생성 및 필터
df = pd.DataFrame(items)
df = df[df['fcstDate'] == today]
df = df[df['category'].isin(['T3H', 'REH', 'POP', 'SKY'])][['fcstTime', 'category', 'fcstValue']]

# 6. 피벗
df_pivot = df.pivot(index='fcstTime', columns='category', values='fcstValue').reset_index()
df_pivot = df_pivot.rename(columns={
    'fcstTime': '예보시각',
    'T3H': '기온(°C)', 'REH': '습도(%)',
    'POP': '강수확률(%)', 'SKY': '하늘상태'
})

# 7. 숫자 변환
for col in ['기온(°C)', '습도(%)', '강수확률(%)']:
    if col in df_pivot.columns:
        df_pivot[col] = pd.to_numeric(df_pivot[col], errors='coerce')

# 8. 하늘상태 이모지 처리
sky_map = {'1': '☀ 맑음', '3': '⛅ 구름많음', '4': '☁ 흐림'}
if '하늘상태' in df_pivot.columns:
    df_pivot['하늘상태'] = df_pivot['하늘상태'].map(sky_map)

# 9. 시간 포맷 보기 좋게
df_pivot['예보시각'] = df_pivot['예보시각'].str[:2] + ":00"
df_pivot['예보_시'] = df_pivot['예보시각'].str[:2].astype(int)
df_pivot['시간차'] = abs(df_pivot['예보_시'] - now.hour)

# 10. 현재 시각 기준 예보 찾기 (기온이 존재하는 시각 기준)
기온있는 = df_pivot[df_pivot['기온(°C)'].notna()]
if not 기온있는.empty:
    closest_row = 기온있는.loc[기온있는['시간차'].idxmin()]
else:
    closest_row = df_pivot.loc[df_pivot['시간차'].idxmin()]

# 11. 출력
st.title("🌤️ 대전 유성구 전민동 기상청 예보")
st.write(f"📅 예보 기준일: `{today}`, ⏰ 현재 시각: `{current_time}`")

# 12. 현재 예보 요약
st.subheader(f"🔍 현재 시각 기준 가장 가까운 예보: `{closest_row['예보시각']}`")
st.markdown(f"""
- 🌡️ **기온:** `{closest_row.get('기온(°C)', 'N/A')}°C`  
- 💧 **습도:** `{closest_row.get('습도(%)', 'N/A')}%`  
- 🌧️ **강수확률:** `{closest_row.get('강수확률(%)', 'N/A')}%`  
- 🌥️ **하늘상태:** `{closest_row.get('하늘상태', 'N/A')}`
""")

# 13. 표 출력
st.subheader("📅 시간대별 예보 표")
표컬럼 = ['예보시각', '기온(°C)', '습도(%)', '강수확률(%)', '하늘상태']
st.dataframe(df_pivot[표컬럼], use_container_width=True)

# 14. 차트
st.subheader("📈 예보 차트 (온도/습도/강수확률)")
chart_cols = ['기온(°C)', '습도(%)', '강수확률(%)']
st.line_chart(df_pivot.set_index('예보시각')[chart_cols])