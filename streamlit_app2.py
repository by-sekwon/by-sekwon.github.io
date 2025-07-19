import streamlit as st
import requests
import pandas as pd
from datetime import datetime, timedelta
import pytz

# 한국 시간 설정
kst = pytz.timezone("Asia/Seoul")
now = datetime.now(kst)
today = now.strftime("%Y%m%d")
current_time = now.strftime("%H:%M")

# 💡 기온(T3H) 포함된 기준 시각 고정
base_time = "1100"  # T3H가 포함된 안정적인 시간대 중 하나

# 대전 유성구 전민동 격자 좌표
nx, ny = 67, 100

# API KEY
API_KEY = st.secrets["weather"]["api_key"]

# 기상청 API 요청 URL
url = (
    "http://apis.data.go.kr/1360000/VilageFcstInfoService_2.0/getVilageFcst"
    f"?serviceKey={API_KEY}"
    f"&pageNo=1&numOfRows=1000&dataType=JSON"
    f"&base_date={today}&base_time={base_time}"
    f"&nx={nx}&ny={ny}"
)

# 데이터 요청
response = requests.get(url)
items = response.json().get("response", {}).get("body", {}).get("items", {}).get("item", [])

# 데이터프레임 생성 및 필터링
df = pd.DataFrame(items)
df = df[df['category'].isin(['T3H', 'REH', 'SKY', 'POP'])]
df = df[['fcstTime', 'category', 'fcstValue']]

# 피벗
df_pivot = df.pivot_table(index='fcstTime', columns='category', values='fcstValue', aggfunc='first')
df_pivot = df_pivot.rename(columns={
    'T3H': '기온(°C)',
    'REH': '습도(%)',
    'POP': '강수확률(%)',
    'SKY': '하늘상태'
})

# 수치형 변환
numeric_cols = ['기온(°C)', '습도(%)', '강수확률(%)']
existing_cols = [col for col in numeric_cols if col in df_pivot.columns]
if existing_cols:
    df_pivot[existing_cols] = df_pivot[existing_cols].apply(pd.to_numeric, errors='coerce')

# 하늘상태 이모지 매핑
sky_map = {
    '1': '☀ 맑음',
    '3': '⛅ 구름많음',
    '4': '☁ 흐림'
}
if '하늘상태' in df_pivot.columns:
    df_pivot['하늘상태'] = df_pivot['하늘상태'].map(sky_map)

# 예보시각 포맷 변경
df_pivot.index.name = '예보시각'
df_pivot.reset_index(inplace=True)
df_pivot['예보시각'] = df_pivot['예보시각'].apply(lambda x: f"{x[:2]}:{x[2:]}")

# 현재 시각과 가장 가까운 예보 찾기
df_pivot['예보_시'] = df_pivot['예보시각'].str[:2].astype(int)
current_hour = int(now.strftime("%H"))
df_pivot['시간차'] = abs(df_pivot['예보_시'] - current_hour)
closest_row = df_pivot.loc[df_pivot['시간차'].idxmin()]

# ✅ Streamlit 출력
st.title("🌤️ 대전 유성구 전민동 기상청 예보")
st.write(f"📅 예보 기준일: `{today}` | 🕐 현재 시각: `{current_time}`")
st.markdown(f"📌 사용된 예보 기준시간(base_time): `{base_time}`")

# 현재 예보 정보
st.subheader(f"🔍 현재 시각 기준 가장 가까운 예보: `{closest_row['예보시각']}`")
st.markdown(f"""
- 🌡️ **기온:** `{closest_row.get('기온(°C)', 'N/A')}°C`  
- 💧 **습도:** `{closest_row.get('습도(%)', 'N/A')}%`  
- 🌧️ **강수확률:** `{closest_row.get('강수확률(%)', 'N/A')}%`  
- 🌥️ **하늘상태:** `{closest_row.get('하늘상태', 'N/A')}`
""")

# 예보 표
st.subheader("🗓️ 시간대별 예보 표")
st.dataframe(df_pivot[['예보시각'] + existing_cols + (['하늘상태'] if '하늘상태' in df_pivot.columns else [])])

# 차트 출력
if existing_cols:
    st.subheader("📊 예보 차트 (온도/습도/강수확률)")
    st.line_chart(df_pivot.set_index('예보시각')[existing_cols])
else:
    st.warning("📉 예보 데이터가 아직 충분히 제공되지 않았습니다.")