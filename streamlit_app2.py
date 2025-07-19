import streamlit as st
import requests
import pandas as pd
from datetime import datetime

# 1. API 키 (secrets.toml 에 등록된 키 사용)
API_KEY = st.secrets["weather"]["api_key"]

# 2. 현재 날짜/시각
now = datetime.now()
today = now.strftime("%Y%m%d")
current_time = now.strftime("%H:%M")

# 3. base_time 자동 설정
def get_base_time(now):
    base_times = ["2300", "2000", "1700", "1400", "1100", "0800", "0500", "0200"]
    current = int(now.strftime("%H%M"))
    for bt in base_times:
        if current >= int(bt):
            return bt
    return "2300"

base_time = get_base_time(now)

# 4. 대전 유성구 격자
nx, ny = 67, 100

# 5. API 요청
url = (
    "http://apis.data.go.kr/1360000/VilageFcstInfoService_2.0/getVilageFcst"
    f"?serviceKey={API_KEY}"
    f"&pageNo=1&numOfRows=1000&dataType=JSON"
    f"&base_date={today}&base_time={base_time}"
    f"&nx={nx}&ny={ny}"
)

response = requests.get(url)
items = response.json().get("response", {}).get("body", {}).get("items", {}).get("item", [])

# 6. 데이터 처리
df = pd.DataFrame(items)
df = df[df['category'].isin(['T3H', 'REH', 'SKY', 'POP'])]
df = df[['fcstTime', 'category', 'fcstValue']]

# 7. 피벗
df_pivot = df.pivot_table(index='fcstTime', columns='category', values='fcstValue', aggfunc='first')
df_pivot = df_pivot.rename(columns={
    'T3H': '기온(°C)',
    'REH': '습도(%)',
    'POP': '강수확률(%)',
    'SKY': '하늘상태'
})

# 8. 타입 변환
numeric_cols = ['기온(°C)', '습도(%)', '강수확률(%)']
existing_cols = [col for col in numeric_cols if col in df_pivot.columns]
if existing_cols:
    df_pivot[existing_cols] = df_pivot[existing_cols].astype(float)

# 9. 하늘상태 매핑
sky_map = {'1': '☀ 맑음', '3': '⛅ 구름많음', '4': '☁ 흐림'}
if '하늘상태' in df_pivot.columns:
    df_pivot['하늘상태'] = df_pivot['하늘상태'].map(sky_map)

# 10. 보기 좋은 시각 형식
df_pivot.index.name = '예보시각'
df_pivot.reset_index(inplace=True)
df_pivot['예보시각'] = df_pivot['예보시각'].apply(lambda x: f"{x[:2]}:{x[2:]}")

# 11. 가장 가까운 예보 추출
current_hour = int(now.strftime("%H"))
df_pivot['예보_시'] = df_pivot['예보시각'].str[:2].astype(int)
df_pivot['시간차'] = abs(df_pivot['예보_시'] - current_hour)
closest_row = df_pivot.loc[df_pivot['시간차'].idxmin()]

# 12. 출력
st.title("🌤️ 대전 유성구 전민동 기상청 예보")
st.write(f"📅 예보 기준일: `{today}`, ⏰ 현재 시각: `{current_time}`")
st.subheader(f"🔎 현재 시각 기준 가장 가까운 예보: `{closest_row['예보시각']}`")

st.markdown(f"""
- 🌡️ **기온:** `{closest_row.get('기온(°C)', 'N/A')}°C`  
- 💧 **습도:** `{closest_row.get('습도(%)', 'N/A')}%`  
- 🌧️ **강수확률:** `{closest_row.get('강수확률(%)', 'N/A')}%`  
- 🌥️ **하늘상태:** `{closest_row.get('하늘상태', 'N/A')}`
""")

# 13. 예보 표
st.subheader("🗓️ 시간대별 예보 표")
st.dataframe(df_pivot[['예보시각'] + existing_cols + (['하늘상태'] if '하늘상태' in df_pivot.columns else [])])

# 14. 차트
if existing_cols:
    st.subheader("📊 예보 차트 (온도/습도/강수확률)")
    st.line_chart(df_pivot.set_index('예보시각')[existing_cols])
else:
    st.warning("📉 예보 데이터가 아직 제공되지 않았습니다.")