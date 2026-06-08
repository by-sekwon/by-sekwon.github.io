"""
동행복권 당첨번호 수집 스크립트
- Playwright로 JS를 렌더링해 XHR 응답을 가로채 JSON 데이터 추출
- JSON이 없으면 렌더된 HTML에서 번호 파싱
- lotto_cache.json 에 누적 저장 (기존 데이터 재사용, 빈 회차만 보충)
"""
import json, re, os
from datetime import date
from playwright.sync_api import sync_playwright

CACHE_FILE = "lotto_cache.json"

# 파일이 없으면 빈 파일 먼저 생성 (git add 실패 방지)
if not os.path.exists(CACHE_FILE):
    with open(CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump([], f)

# ── 기존 캐시 로드 ──────────────────────────────
with open(CACHE_FILE, encoding="utf-8") as f:
    existing = {r["round"]: r for r in json.load(f)}

# ── 최신 회차 추정 ──────────────────────────────
days = (date.today() - date(2002, 12, 7)).days
estimated = max(1, days // 7 + 1)

# ── 수집할 회차 결정 ────────────────────────────
# 이미 있는 회차는 스킵, 추정 최신 +5까지 시도
all_rounds = list(range(1, estimated + 6))
missing    = [r for r in all_rounds if r not in existing]
print(f"추정 최신 회차: {estimated}, 수집 대상: {len(missing)}회")

if not missing:
    print("수집할 회차 없음 → 기존 캐시 유지")
    exit(0)

records = dict(existing)

# ── Playwright로 수집 ───────────────────────────
def parse_round(page, rnd):
    """한 회차 페이지에서 당첨번호 추출. 성공 시 dict 반환, 실패 시 None."""
    found = {}

    def on_response(resp):
        try:
            ct = resp.headers.get("content-type", "")
            if "json" in ct:
                data = resp.json()
                if isinstance(data, dict) and data.get("returnValue") == "success":
                    found.update(data)
        except Exception:
            pass

    page.on("response", on_response)
    try:
        page.goto(
            f"https://www.dhlottery.co.kr/gameResult.do?method=byWin&drwNo={rnd}",
            wait_until="networkidle",
            timeout=20_000,
        )
    except Exception:
        return None
    finally:
        page.remove_listener("response", on_response)

    # ① XHR JSON으로 얻은 경우
    if found.get("returnValue") == "success":
        return {
            "round":   found["drwNo"],
            "date":    found["drwNoDate"],
            "numbers": [found[f"drwtNo{i}"] for i in range(1, 7)],
            "bonus":   found["bnusNo"],
        }

    # ② 렌더된 HTML 파싱 (fallback)
    html = page.content()
    nums = [int(t) for t in re.findall(r"class=\"[^\"]*ball[^\"]*\"[^>]*>\s*(\d{1,2})\s*<", html)
            if 1 <= int(t) <= 45]
    if len(nums) >= 7:
        d_match = re.search(r"\d{4}[-./]\d{1,2}[-./]\d{1,2}", html)
        return {
            "round":   rnd,
            "date":    d_match.group().replace("/", "-").replace(".", "-") if d_match else "",
            "numbers": nums[:6],
            "bonus":   nums[6],
        }

    return None

BATCH = 200  # 한 번에 처리할 최대 회차 수 (GitHub Actions 시간 제한 방어)

with sync_playwright() as pw:
    browser = pw.chromium.launch(headless=True)
    context = browser.new_context(
        user_agent=(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
        )
    )
    # 메인 페이지 로드 → 세션 쿠키 확보
    page = context.new_page()
    page.goto("https://www.dhlottery.co.kr/", wait_until="networkidle", timeout=15_000)

    success = fail = 0
    for rnd in missing[:BATCH]:
        result = parse_round(page, rnd)
        if result:
            records[rnd] = result
            success += 1
            if success % 50 == 0:
                print(f"  {success}회차 수집 완료 (마지막: {rnd}회)")
        else:
            fail += 1

    browser.close()

print(f"완료 — 성공: {success}, 실패/없음: {fail}")

# ── 저장 ────────────────────────────────────────
sorted_records = sorted(records.values(), key=lambda x: x["round"])
with open(CACHE_FILE, "w", encoding="utf-8") as f:
    json.dump(sorted_records, f, ensure_ascii=False)

if sorted_records:
    print(f"저장 완료: {sorted_records[0]['round']}~{sorted_records[-1]['round']}회, 총 {len(sorted_records)}건")
