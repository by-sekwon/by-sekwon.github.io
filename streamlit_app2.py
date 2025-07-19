import streamlit as st
import requests
import pandas as pd
from datetime import datetime, timedelta

# 1. API 키 불러오기
API_KEY = st.secrets["weather"]["api_key"]

# 2. 현재 날짜/시각 정보
now = datetime.now()
today = now.strftime("%Y%m%d")
current_time = now.strftime("%H:%M")

# 3. 대전 유성구 전민동 격자 좌표
nx, ny = 67, 100

# 4. 사용 가능한 기준 시각 리스트 (3시간 간격)
base_times = ["0200", "0500", "0800", "1100", "1400", "1700", "2000", "2300"]

# 5. 예보 데이터를 담을 리스트
all_items = []

for base_time in base_times:
    try:
        url = (
            "http://apis.data.go.kr/1360000/VilageFcstInfoService_2.0/getVilageFcst"
            f"?serviceKey={API_KEY}"
            f"&pageNo=1&numOfRows=1000&dataType=JSON"
            f"&base_date={today}&base_time={base_time}"
            f"&nx={nx}&ny={ny}"
        )
        response = requests.get(url, timeout=5)
        data = response.json()
        items = data.get("response", {}).get("body", {}).get("items", {}).get("item", [])
        all_items.extend(items)
    except Exception as e:
        st.warning(f"🚨 {base_time} 시 요청 실패: {e}")

# 6. 데이터 없을 경우 중단
if not all_items:
    st.error("❌ 예보 데이터를 불러올 수 없습니다. API 요청에 실패했을 수 있습니다.")
    st.stop()

# 7. 데이터프레임 생성 및 필터
df = pd.DataFrame(all_items)
df = df[df['category'].isin(['T3H', 'REH', 'SKY', 'POP'])]
df = df[['fcstTime', 'category', 'fcstValue']]

# 8. 피벗 및 컬럼명 변경
df_pivot = df.pivot_table(index='fcstTime', columns='category', values='fcstValue', aggfunc='first')
df_pivot = df_pivot.rename(columns={
    'T3H': '기온(°C)',
    'REH': '습도(%)',
    'POP': '강수확률(%)',
    'SKY': '하늘상태'
})

# 9. 수치형 컬럼 처리 (존재하는 것만)
numeric_cols_all = ['기온(°C)', '습도(%)', '강수확률(%)']
existing_numeric_cols = [col for col in numeric_cols_all if col in df_pivot.columns]

if existing_numeric_cols:
    df_pivot[existing_numeric_cols] = df_pivot[existing_numeric_cols].apply(pd.to_numeric, errors='coerce')

# 10. 하늘상태 이모지 처리
sky_map = {
    '1': '☀ 맑음',
    '3': '⛅ 구름많음',
    '4': '☁ 흐림'
}
if '하늘상태' in df_pivot.columns:
    df_pivot['하늘상태'] = df_pivot['하늘상태'].map(sky_map)

# 11. 시각 포맷
df_pivot.index.name = '예보시각'
df_pivot.reset_index(inplace=True)
df_pivot['예보시각'] = df_pivot['예보시각'].apply(lambda x: f"{x[:2]}:{x[2:]}")

# 12. 현재 시각 기준 가장 가까운 예보
current_hour = int(now.strftime("%H"))
df_pivot['예보_시'] = df_pivot['예보시각'].str[:2].astype(int)
df_pivot['시간차'] = abs(df_pivot['예보_시'] - current_hour)
closest_row = df_pivot.loc[df_pivot['시간차'].idxmin()]

# 13. 대시보드 출력
st.title("🌤️ 대전 유성구 전민동 기상청 예보")
st.write(f"📅 예보 기준일: `{today}`, ⏰ 현재 시각: `{current_time}`")

st.subheader(f"🔎 현재 시각 기준 가장 가까운 예보: `{closest_row['예보시각']}`")
st.markdown(f"""
- 🌡️ **기온:** `{closest_row.get('기온(°C)', 'N/A')}°C`  
- 💧 **습도:** `{closest_row.get('습도(%)', 'N/A')}%`  
- 🌧️ **강수확률:** `{closest_row.get('강수확률(%)', 'N/A')}%`  
- 🌥️ **하늘상태:** `{closest_row.get('하늘상태', 'N/A')}`
""")

# 14. 예보 테이블
st.subheader("🗓️ 시간대별 예보 표")
columns_to_display = ['예보시각'] + existing_numeric_cols + (['하늘상태'] if '하늘상태' in df_pivot.columns else [])
st.dataframe(df_pivot[columns_to_display])

# 15. 차트 시각화
if existing_numeric_cols:
    st.subheader("📊 예보 차트 (온도/습도/강수확률)")
    st.line_chart(df_pivot.set_index('예보시각')[existing_numeric_cols])
else:
    st.warning("📉 예보 데이터가 부족하여 차트를 그릴 수 없습니다.")