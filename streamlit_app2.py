import streamlit as st
import requests
import pandas as pd
from datetime import datetime

# 1. API 키
API_KEY = "ruuUkmag89d29McI%2BctxcVAsnsv%2BfAPzunUfmNjVf5R9StYJJes8edUq1wRm48DMu0rBodNw9Mit0EEX01p6EA%3D%3D"

# 2. 현재 날짜와 시각
now = datetime.now()
today = now.strftime("%Y%m%d")
current_time = now.strftime("%H:%M")

# 3. 기준 시간 (기상청은 0200, 0500, 0800, ... 단위만 제공)
base_time = "0500"

# 4. 서울 종로구 격자 좌표
nx, ny = 60, 127

# 5. API URL
url = (
    "http://apis.data.go.kr/1360000/VilageFcstInfoService_2.0/getVilageFcst"
    f"?serviceKey={API_KEY}"
    f"&pageNo=1&numOfRows=1000&dataType=JSON"
    f"&base_date={today}&base_time={base_time}"
    f"&nx={nx}&ny={ny}"
)

# 6. 데이터 요청
response = requests.get(url)
items = response.json().get("response", {}).get("body", {}).get("items", {}).get("item", [])

# 7. 데이터프레임 정리
df = pd.DataFrame(items)
df = df[df['category'].isin(['T3H', 'REH', 'SKY', 'POP'])]
df = df[['fcstTime', 'category', 'fcstValue']]

# 8. 피벗 테이블
df_pivot = df.pivot_table(index='fcstTime', columns='category', values='fcstValue', aggfunc='first')
df_pivot = df_pivot.rename(columns={
    'T3H': '기온(°C)',
    'REH': '습도(%)',
    'POP': '강수확률(%)',
    'SKY': '하늘상태'
})

# 9. 숫자형 변환
df_pivot[['기온(°C)', '습도(%)', '강수확률(%)']] = df_pivot[['기온(°C)', '습도(%)', '강수확률(%)']].astype(float)

# 10. 하늘상태 해석
sky_map = {
    '1': '맑음',
    '3': '구름많음',
    '4': '흐림'
}
df_pivot['하늘상태'] = df_pivot['하늘상태'].map(sky_map)

# 11. 시간 포맷 변경 (예: "0600" → "06:00")
df_pivot.index = df_pivot.index.str.slice(0, 2) + ":" + df_pivot.index.str.slice(2, 4)

# 12. 대시보드 출력
st.title("🌤️ 실시간 기상청 단기예보")
st.write(f"현재 시각 기준: **{current_time}**")

st.dataframe(df_pivot)

# 13. 그래프 시각화
st.line_chart(df_pivot[['기온(°C)', '습도(%)', '강수확률(%)']])