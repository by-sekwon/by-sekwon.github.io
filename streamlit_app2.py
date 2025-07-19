import streamlit as st
import requests
import pandas as pd
from datetime import datetime

# 1. API 키
API_KEY = "ruuUkmag89d29McI%2BctxcVAsnsv%2BfAPzunUfmNjVf5R9StYJJes8edUq1wRm48DMu0rBodNw9Mit0EEX01p6EA%3D%3D"

# 2. 날짜/시간
today = datetime.today().strftime("%Y%m%d")
base_time = "0500"

# 3. 서울 종로구 기준 격자좌표
nx, ny = 60, 127

# 4. 요청 URL
url = (
    "http://apis.data.go.kr/1360000/VilageFcstInfoService_2.0/getVilageFcst"
    f"?serviceKey={API_KEY}"
    f"&pageNo=1&numOfRows=1000&dataType=JSON"
    f"&base_date={today}&base_time={base_time}"
    f"&nx={nx}&ny={ny}"
)

# 5. API 호출
response = requests.get(url)
items = response.json().get("response", {}).get("body", {}).get("items", {}).get("item", [])

# 6. 데이터 정리
df = pd.DataFrame(items)
df = df[df['category'].isin(['T3H', 'REH', 'SKY', 'POP'])]  # 🔹강수확률 추가
df = df[['fcstTime', 'category', 'fcstValue']]

# 7. 피벗
df_pivot = df.pivot_table(index='fcstTime', columns='category', values='fcstValue', aggfunc='first')
df_pivot = df_pivot.rename(columns={
    'T3H': '기온(°C)',
    'REH': '습도(%)',
    'POP': '강수확률(%)',
    'SKY': '하늘상태'
})

# 8. 하늘상태 해석
sky_map = {
    '1': '맑음',
    '3': '구름많음',
    '4': '흐림'
}
df_pivot['하늘상태'] = df_pivot['하늘상태'].map(sky_map)

# 9. 시각화
st.title("🌤️ 실시간 기상청 단기예보")
st.dataframe(df_pivot)