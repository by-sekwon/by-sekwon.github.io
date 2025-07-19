import streamlit as st
import requests
import pandas as pd
from datetime import datetime

# 1. API 키
API_KEY = "ruuUkmag89d29McI%2BctxcVAsnsv%2BfAPzunUfmNjVf5R9StYJJes8edUq1wRm48DMu0rBodNw9Mit0EEX01p6EA%3D%3D"

# 2. 날짜와 현재 시각
now = datetime.now()
today = now.strftime("%Y%m%d")
current_time = now.strftime("%H:%M")
base_time = "0500"  # 안정적인 시간 추천: 0200, 0500, 0800, 1100, 1400 등

# 3. 대전 유성구 격자 좌표
nx, ny = 67, 100

# 4. API 요청 URL
url = (
    "http://apis.data.go.kr/1360000/VilageFcstInfoService_2.0/getVilageFcst"
    f"?serviceKey={API_KEY}"
    f"&pageNo=1&numOfRows=1000&dataType=JSON"
    f"&base_date={today}&base_time={base_time}"
    f"&nx={nx}&ny={ny}"
)

# 5. 데이터 요청
response = requests.get(url)
items = response.json().get("response", {}).get("body", {}).get("items", {}).get("item", [])

# 6. 데이터프레임
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

# 8. 컬럼 존재 여부 확인 및 변환
numeric_cols = ['기온(°C)', '습도(%)', '강수확률(%)']
existing_cols = [col for col in numeric_cols if col in df_pivot.columns]
if existing_cols:
    df_pivot[existing_cols] = df_pivot[existing_cols].astype(float)

# 9. 하늘상태 이모지 매핑
sky_map = {
    '1': '☀ 맑음',
    '3': '⛅ 구름많음',
    '4': '☁ 흐림'
}
if '하늘상태' in df_pivot.columns:
    df_pivot['하늘상태'] = df_pivot['하늘상태'].map(sky_map)

# 10. 시간 포맷 보기 좋게
df_pivot.index = df_pivot.index.str.slice(0, 2) + ":" + df_pivot.index.str.slice(2, 4)

# 11. 대시보드 출력
st.title("🌤️ 대전 유성구 전민동 기상청 예보")
st.write(f"📅 예보 기준일: `{today}`, ⏰ 현재 시각: `{current_time}`")

# 12. 표 출력
st.dataframe(df_pivot)

# 13. 차트 출력
if existing_cols:
    st.subheader("📊 예보 차트")
    st.line_chart(df_pivot[existing_cols])
else:
    st.warning("예보 데이터가 아직 제공되지 않았습니다.")