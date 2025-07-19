import streamlit as st
import requests
import pandas as pd
from datetime import datetime, timedelta
import pytz

# 1. API 키 (streamlit secrets.toml에서 불러오기)
API_KEY = st.secrets["weather"]["api_key"]

# 2. 현재 시각 (한국 표준시 기준)
kst = pytz.timezone("Asia/Seoul")
now = datetime.now(kst)
today = now.strftime("%Y%m%d")
current_time = now.strftime("%H:%M")

# 3. 기상청 base_time 계산 (가장 최근 발표된 예보 시각)
def get_latest_base_time(now):
    base_times = ["0200", "0500", "0800", "1100", "1400", "1700", "2000", "2300"]
    hour = now.hour
    for bt in reversed(base_times):
        if hour >= int(bt[:2]):
            return bt
    return "2300"  # 새벽 0~2시 사이엔 전날 23:00 예보 사용

base_time = get_latest_base_time(now)

# 4. 격자 좌표 (대전 유성구 전민동 기준)
nx, ny = 67, 100

# 5. API 요청 URL 구성
url = (
    "http://apis.data.go.kr/1360000/VilageFcstInfoService_2.0/getVilageFcst"
    f"?serviceKey={API_KEY}"
    f"&pageNo=1&numOfRows=1000&dataType=JSON"
    f"&base_date={today}&base_time={base_time}"
    f"&nx={nx}&ny={ny}"
)

# 6. 요청 및 오류 처리
response = requests.get(url)

try:
    items = response.json().get("response", {}).get("body", {}).get("items", {}).get("item", [])
except requests.exceptions.JSONDecodeError:
    st.error("❌ 기상청 응답을 JSON으로 해석할 수 없습니다.")
    st.code(response.text)
    st.stop()

# 7. 데이터프레임 생성 및 필터링
df = pd.DataFrame(items)
df = df[df['category'].isin(['T3H', 'REH', 'SKY', 'POP'])]
df = df[['fcstTime', 'category', 'fcstValue']]

# 8. 피벗 테이블로 변환
df_pivot = df.pivot_table(index='fcstTime', columns='category', values='fcstValue', aggfunc='first')
df_pivot = df_pivot.rename(columns={
    'T3H': '기온(°C)',
    'REH': '습도(%)',
    'POP': '강수확률(%)',
    'SKY': '하늘상태'
})

# 9. 데이터 타입 변환
numeric_cols = ['기온(°C)', '습도(%)', '강수확률(%)']
existing_cols = [col for col in numeric_cols if col in df_pivot.columns]
if existing_cols:
    df_pivot[existing_cols] = df_pivot[existing_cols].apply(pd.to_numeric, errors='coerce')

# 10. 하늘상태 매핑
sky_map = {
    '1': '☀ 맑음',
    '3': '⛅ 구름많음',
    '4': '☁ 흐림'
}
if '하늘상태' in df_pivot.columns:
    df_pivot['하늘상태'] = df_pivot['하늘상태'].map(sky_map)

# 11. 시간 포맷 변경
df_pivot.index.name = '예보시각'
df_pivot.reset_index(inplace=True)
df_pivot['예보시각'] = df_pivot['예보시각'].apply(lambda x: f"{x[:2]}:{x[2:]}")

# 12. 가장 가까운 예보 시각 정보
df_pivot['예보_시'] = df_pivot['예보시각'].str[:2].astype(int)
current_hour = now.hour
df_pivot['시간차'] = abs(df_pivot['예보_시'] - current_hour)
closest_row = df_pivot.loc[df_pivot['시간차'].idxmin()]

# 13. 대시보드 출력
st.title("🌤️ 대전 유성구 전민동 기상청 예보")
st.write(f"📅 예보 기준일: `{today}` | 🕐 현재 시각: `{current_time}`")
st.markdown(f"📌 사용된 예보 기준시간(base_time): `{base_time}`")

# 14. 현재 시각 기준 가장 가까운 예보
st.subheader(f"🔍 현재 시각 기준 가장 가까운 예보: `{closest_row['예보시각']}`")
st.markdown(f"""
- 🌡️ **기온:** `{closest_row.get('기온(°C)', 'N/A')}°C`  
- 💧 **습도:** `{closest_row.get('습도(%)', 'N/A')}%`  
- 🌧️ **강수확률:** `{closest_row.get('강수확률(%)', 'N/A')}%`  
- 🌥️ **하늘상태:** `{closest_row.get('하늘상태', 'N/A')}`
""")

# 15. 전체 예보 표
st.subheader("🗓️ 시간대별 예보 표")
st.dataframe(df_pivot[['예보시각'] + existing_cols + (['하늘상태'] if '하늘상태' in df_pivot.columns else [])])

# 16. 차트
if existing_cols:
    st.subheader("📊 예보 차트 (온도/습도/강수확률)")
    st.line_chart(df_pivot.set_index('예보시각')[existing_cols])
else:
    st.warning("📉 예보 데이터가 아직 제공되지 않았습니다.")