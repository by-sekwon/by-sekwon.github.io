import streamlit as st
import requests
import pandas as pd
from datetime import datetime, timedelta
import pytz

# 1. API 키
API_KEY = st.secrets["weather"]["api_key"]

# ✅ 한국 시간 설정
kst = pytz.timezone("Asia/Seoul")
now = datetime.now(kst)
today = now.strftime("%Y%m%d")
current_time = now.strftime("%H%M")

# ✅ 격자 좌표 (대전 유성구 전민동 기준)
nx, ny = 67, 100  # ✅ <== 순서를 URL 생성 전에 위치시켜야 함


# ✅ 초단기실황 API
url = (
    "http://apis.data.go.kr/1360000/VilageFcstInfoService_2.0/getUltraSrtNcst"
    f"?serviceKey={API_KEY}"
    f"&pageNo=1&numOfRows=100&dataType=JSON"
    f"&base_date={today}&base_time={current_time}"
    f"&nx={nx}&ny={ny}"
)

response = requests.get(url)
try:
    items = response.json().get("response", {}).get("body", {}).get("items", {}).get("item", [])
except Exception:
    st.error("❌ 기상청 데이터 불러오기 실패")
    st.stop()

# ✅ 코드 설명 매핑
code_map = {
    "T1H": "🌡️ 기온(°C)",
    "REH": "💧 습도(%)",
    "RN1": "🌧️ 1시간 강수량(mm)",
    "PTY": "🌥️ 강수형태"
}

# ✅ PTY 이모지 매핑
pty_map = {
    "0": "☀️ 없음",
    "1": "🌧️ 비",
    "2": "🌨️ 비/눈",
    "3": "❄️ 눈",
    "4": "🌦️ 소나기"
}

# ✅ 데이터 정리
data = {}
for item in items:
    category = item["category"]
    if category in code_map:
        value = item["obsrValue"]
        if category == "PTY":
            data[code_map[category]] = pty_map.get(str(value), "❓ 미상")
        else:
            data[code_map[category]] = f"{value}"

# ✅ Streamlit 출력
st.title("🌤️ 대전 유성구 실시간 날씨")
st.write(f"📅 기준시각: `{today} {current_time[:2]}:{current_time[2:]}`")
st.markdown("---")

for k, v in data.items():
    st.write(f"**{k}**: `{v}`")

st.markdown("---")

# ✅ 기온 시각화 (옵션)
if "🌡️ 기온(°C)" in data:
    temp = float(data["🌡️ 기온(°C)"])
    temp_df = pd.DataFrame({"기온(°C)": [temp]}, index=[now.strftime("%H:%M")])
    st.line_chart(temp_df)