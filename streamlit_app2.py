import streamlit as st
import requests
import pandas as pd
from datetime import datetime
from zoneinfo import ZoneInfo  # Python 3.9+ 전용

# 1. API 키
API_KEY = st.secrets["weather"]["api_key"]

# 2. 한국 시각 기준 시간 설정
kst = ZoneInfo("Asia/Seoul")
now = datetime.now(tz=kst)
today = now.strftime("%Y%m%d")
current_time = now.strftime("%H:%M")
base_time = "0500"  # 안정적인 시간 선택 (2,5,8,11,14...)

# 3. 유성구 전민동 격자 좌표
nx, ny = 67, 100

# 4. API 요청
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

# 5. 데이터프레임 구성
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

# 7. 수치형 컬럼 처리
numeric_cols = ['기온(°C)', '습도(%)', '강수확률(%)']
existing_cols = [col for col in numeric_cols if col in df_pivot.columns]
df_pivot[existing_cols] = df_pivot[existing_cols].apply(pd.to_numeric, errors='coerce')

# 8. 하늘상태 해석
sky_map = {'1': '☀ 맑음', '3': '⛅ 구름많음', '4': '☁ 흐림'}
if '하늘상태' in df_pivot.columns:
    df_pivot['하늘상태'] = df_pivot['하늘상태'].map(sky_map)

# 9. 시간 가공
df_pivot['예보시각'] = df_pivot['예보시각'].str[:2] + ":00"
df_pivot['예보_시'] = df_pivot['예보시각'].str[:2].astype(int)
df_pivot['시간차'] = abs(df_pivot['예보_시'] - now.hour)

# 10. 현재 시각과 가장 가까운 예보 찾기
if '기온(°C)' in df_pivot.columns:
    df_temp = df_pivot[df_pivot['기온(°C)'].notna()]
    if not df_temp.empty:
        closest_row = df_temp.loc[df_temp['시간차'].idxmin()]
    else:
        closest_row = df_pivot.loc[df_pivot['시간차'].idxmin()]
else:
    closest_row = df_pivot.loc[df_pivot['시간차'].idxmin()]

# 11. 대시보드 출력
st.title("🌤️ 대전 유성구 전민동 기상청 예보")
st.write(f"📅 예보 기준일: `{today}`, ⏰ 현재 시각: `{current_time}`")

st.subheader(f"🔍 현재 시각 기준 가장 가까운 예보: `{closest_row['예보시각']}`")
st.markdown(f"""
- 🌡️ **기온:** `{closest_row.get('기온(°C)', 'N/A')}°C`  
- 💧 **습도:** `{closest_row.get('습도(%)', 'N/A')}%`  
- 🌧️ **강수확률:** `{closest_row.get('강수확률(%)', 'N/A')}%`  
- 🌥️ **하늘상태:** `{closest_row.get('하늘상태', 'N/A')}`
""")

# 12. 전체 예보 표 출력
st.subheader("📅 시간대별 예보 표")
표컬럼 = ['예보시각'] + existing_cols + (['하늘상태'] if '하늘상태' in df_pivot.columns else [])
st.dataframe(df_pivot[표컬럼], use_container_width=True)

# 13. 예보 차트
if existing_cols:
    st.subheader("📈 예보 차트 (온도/습도/강수확률)")
    st.line_chart(df_pivot.set_index('예보시각')[existing_cols])
else:
    st.warning("📉 수치형 예보 데이터가 제공되지 않았습니다.")