import streamlit as st
import requests
from datetime import datetime, timedelta

# 1. API 키
API_KEY = st.secrets["weather"]["api_key"]

# 2. 현재 시간 (KST 기준)
now = datetime.utcnow() + timedelta(hours=9)
today = now.strftime("%Y%m%d")
base_time = (now - timedelta(minutes=40)).strftime("%H%M")

# 3. 격자 좌표 (대전 유성구 전민동)
nx, ny = 67, 100

# 4. 초단기예보 요청 URL
url = (
    "http://apis.data.go.kr/1360000/VilageFcstInfoService_2.0/getUltraSrtFcst"
    f"?serviceKey={API_KEY}&pageNo=1&numOfRows=1000&dataType=JSON"
    f"&base_date={today}&base_time={base_time}&nx={nx}&ny={ny}"
)

# 5. 요청 및 파싱
response = requests.get(url, timeout=5)
items = response.json().get("response", {}).get("body", {}).get("items", {}).get("item", [])

# 6. 기온 추출 (T1H: 현재 기온)
temperature = None
for item in items:
    if item["category"] == "T1H":
        temperature = item["obsrValue"]
        break

# 7. 출력
st.title("🌡️ 현재 기온 (대전 유성구 전민동)")
st.write(f"⏰ 기준 시각: `{now.strftime('%Y-%m-%d %H:%M')}`")
if temperature:
    st.success(f"현재 기온은 **{temperature}°C** 입니다.")
else:
    st.error("⚠️ 현재 기온 정보를 불러올 수 없습니다.")