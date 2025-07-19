import streamlit as st
import requests
import pandas as pd
from datetime import datetime

# 1. API 키
API_KEY = "ruuUkmag89d29McI%2BctxcVAsnsv%2BfAPzunUfmNjVf5R9StYJJes8edUq1wRm48DMu0rBodNw9Mit0EEX01p6EA%3D%3D"

# 2. 기준 날짜와 시간 설정
today = datetime.today().strftime("%Y%m%d")
base_time = "0500"  # 새벽 예보 기준

# 3. 격자 좌표 설정 (서울 종로구 예시)
nx = 60
ny = 127

# 4. API URL 구성
url = (
    "http://apis.data.go.kr/1360000/VilageFcstInfoService_2.0/getVilageFcst"
    f"?serviceKey={API_KEY}"
    f"&pageNo=1&numOfRows=1000&dataType=JSON"
    f"&base_date={today}&base_time={base_time}"
    f"&nx={nx}&ny={ny}"
)

# 5. 요청 및 데이터 처리
response = requests.get(url)
items = response.json().get("response", {}).get("body", {}).get("items", {}).get("item", [])

# 6. 데이터프레임 변환
df = pd.DataFrame(items)
df = df[df['category'].isin(['T3H', 'REH', 'SKY'])]  # 3시간 기온, 습도, 하늘상태
df = df[['fcstTime', 'category', 'fcstValue']]

# 7. 피벗: 시간별 항목 보기 좋게
df_pivot = df.pivot(index='fcstTime', columns='category', values='fcstValue').reset_index()

# 8. Streamlit 대시보드
st.title("🌤️ 실시간 기상청 단기예보")
st.dataframe(df_pivot)