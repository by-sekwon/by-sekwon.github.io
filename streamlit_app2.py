import streamlit as st
import requests
import pandas as pd
from datetime import datetime

# 1. API 키 보안처리 (.streamlit/secrets.toml → [weather] api_key = "...")
API_KEY = st.secrets["weather"]["api_key"]

# 2. 현재 날짜/시간
now = datetime.now()
today = now.strftime("%Y%m%d")
current_time = now.strftime("%H:%M")
base_time = "0500"  # 안정적으로 예보 잘 나오는 시간

# 3. 대전 유성구 전민동 격자좌표
nx, ny = 67, 100

# 4. API 요청 URL
url = (
    "http://apis.data.go.kr/1360000/VilageFcstInfoService_2.0/getVilageFcst"
    f"?serviceKey={API_KEY}"
    f"&pageNo=1&numOfRows=1000&dataType=JSON"
    f"&base_date={today}&base_time={base_time}"
    f"&nx={nx}&ny={ny}"
)

# 5. API 요청
try:
    response = requests.get(url, timeout=5)
    response.raise_for_status()
    items = response.json().get("response", {}).get("body", {}).get("items", {}).get("item", [])
except Exception as e:
    st.error(f"⛔ API 요청 실패: {e}")
    st.stop()

# 6. 데이터프레임 구성
df = pd.DataFrame(items)
df = df[df['fcstDate'] == today]  # 🔸오늘 날짜만
df = df[df['category'].isin(['T3H', 'REH', 'SKY', 'POP'])]  # 필요한 항목만
df = df[['fcstTime', 'category', 'fcstValue']]

# 7. 피벗 → 시간별 보기
df_pivot = df.pivot_table(index='fcstTime', columns='category', values='fcstValue', aggfunc='first')
df_pivot = df_pivot.rename(columns={
    'T3H': '기온(°C)',
    'REH': '습도(%)',
    'POP': '강수확률(%)',
    'SKY': '하늘상태'
})

# 8. 숫자형 변환
numeric_cols = ['기온(°C)', '습도(%)', '강수확률(%)']
existing_numeric_cols = [col for col in numeric_cols if col in df_pivot.columns]
df_pivot[existing_numeric_cols] = df_pivot[existing_numeric_cols].apply(pd.to_numeric, errors='coerce')

# 9. 하늘상태 코드 → 이모지
sky_map = {'1': '☀ 맑음', '3': '⛅ 구름많음', '4': '☁ 흐림'}
if '하늘상태' in df_pivot.columns:
    df_pivot['하늘상태'] = df_pivot['하늘상태'].map(sky_map)

# 10. 시간 가독성 개선
df_pivot.index.name = '예보시각'
df_pivot.reset_index(inplace=True)
df_pivot['예보시각'] = df_pivot['예보시각'].apply(lambda x: f"{x[:2]}:{x[2:]}")

# 11. 현재 시각 기준 가장 가까운 예보 선택
current_hour = int(now.strftime("%H"))
df_pivot['예보_시'] = df_pivot['예보시각'].str[:2].astype(int)
df_pivot['시간차'] = abs(df_pivot['예보_시'] - current_hour)
closest_row = df_pivot.loc[df_pivot['시간차'].idxmin()]

# 12. 대시보드 출력
st.title("🌤️ 대전 유성구 전민동 기상청 예보")
st.write(f"📅 **예보 기준일**: `{today}`  |  ⏰ **현재 시각**: `{current_time}`")

# 13. 현재 예보 강조 출력
st.subheader(f"🔍 현재 시각 기준 가장 가까운 예보: `{closest_row['예보시각']}`")
st.markdown(f"""
- 🌡️ **기온:** `{closest_row.get('기온(°C)', 'N/A')}°C`  
- 💧 **습도:** `{closest_row.get('습도(%)', 'N/A')}%`  
- 🌧️ **강수확률:** `{closest_row.get('강수확률(%)', 'N/A')}%`  
- 🌥️ **하늘상태:** `{closest_row.get('하늘상태', 'N/A')}`
""")

# 14. 예보 표 출력
st.subheader("🗓️ 시간대별 예보 표")
표컬럼 = ['예보시각'] + existing_numeric_cols + (['하늘상태'] if '하늘상태' in df_pivot.columns else [])
st.dataframe(df_pivot[표컬럼], use_container_width=True)

# 15. 차트
if existing_numeric_cols:
    st.subheader("📊 예보 차트 (온도/습도/강수확률)")
    st.line_chart(df_pivot.set_index('예보시각')[existing_numeric_cols])
else:
    st.warning("📉 수치형 예보 데이터가 부족해 차트를 출력할 수 없습니다.")