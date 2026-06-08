"""
동행복권 당첨번호 수집 스크립트
- Playwright + 봇 감지 회피 설정
- XHR JSON 가로채기 → HTML 파싱 이중 시도
- 상세 로그 출력으로 실패 원인 파악 가능
"""
import json, re, os, sys
from datetime import date
from playwright.sync_api import sync_playwright

CACHE_FILE = "lotto_cache.json"
BATCH      = 200   # 1회 실행당 최대 수집 회차

# ── 기존 캐시 로드 ──────────────────────────────
if not os.path.exists(CACHE_FILE):
    with open(CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump([], f)

with open(CACHE_FILE, encoding="utf-8") as f:
    existing = {r["round"]: r for r in json.load(f)}

print(f"기존 캐시: {len(existing)}회차")

# ── 최신 회차 추정 ──────────────────────────────
days      = (date.today() - date(2002, 12, 7)).days
estimated = max(1, days // 7 + 1)
all_rounds = list(range(1, estimated + 6))
missing    = [r for r in all_rounds if r not in existing]
print(f"추정 최신 회차: {estimated} | 수집 대상: {len(missing)}회 | 이번 배치: {min(len(missing), BATCH)}회")

if not missing:
    print("수집할 회차 없음 → 종료")
    sys.exit(0)

records = dict(existing)

# ── Playwright 수집 ─────────────────────────────
def parse_round(page, rnd):
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
        resp = page.goto(
            f"https://www.dhlottery.co.kr/gameResult.do?method=byWin&drwNo={rnd}",
            wait_until="networkidle",
            timeout=20_000,
        )
        status = resp.status if resp else "N/A"
    except Exception as e:
        print(f"  [{rnd}회] 페이지 로드 실패: {e}")
        page.remove_listener("response", on_response)
        return None
    finally:
        page.remove_listener("response", on_response)

    # ① XHR JSON
    if found.get("returnValue") == "success":
        return {
            "round":   found["drwNo"],
            "date":    found["drwNoDate"],
            "numbers": [found[f"drwtNo{i}"] for i in range(1, 7)],
            "bonus":   found["bnusNo"],
        }

    # ② 렌더된 HTML 파싱
    html  = page.content()
    title = re.search(r"<title>(.*?)</title>", html)
    nums  = [int(t) for t in re.findall(r'class="[^"]*ball[^"]*"[^>]*>\s*(\d{1,2})\s*<', html)
             if 1 <= int(t) <= 45]

    if rnd <= 3:  # 첫 3회차는 상세 로그
        print(f"  [{rnd}회] HTTP={status} | title={title.group(1)[:40] if title else 'N/A'}"
              f" | ball nums found={nums[:10]}")

    if len(nums) >= 7:
        d_match = re.search(r"\d{4}[-./]\d{1,2}[-./]\d{1,2}", html)
        return {
            "round":   rnd,
            "date":    d_match.group().replace("/", "-").replace(".", "-") if d_match else "",
            "numbers": nums[:6],
            "bonus":   nums[6],
        }

    return None


with sync_playwright() as pw:
    browser = pw.chromium.launch(
        headless=True,
        args=[
            "--no-sandbox",
            "--disable-blink-features=AutomationControlled",
            "--disable-dev-shm-usage",
        ],
    )
    context = browser.new_context(
        user_agent=(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
        ),
        viewport={"width": 1920, "height": 1080},
        locale="ko-KR",
        timezone_id="Asia/Seoul",
    )
    # 봇 감지 회피: navigator.webdriver 제거
    context.add_init_script(
        "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
    )

    page = context.new_page()
    print("메인 페이지 접속 중...")
    try:
        r = page.goto("https://www.dhlottery.co.kr/", wait_until="networkidle", timeout=15_000)
        print(f"메인 페이지 HTTP={r.status if r else 'N/A'} | title={page.title()[:50]}")
    except Exception as e:
        print(f"메인 페이지 접속 실패: {e}")

    success = fail = 0
    for rnd in missing[:BATCH]:
        result = parse_round(page, rnd)
        if result:
            records[rnd] = result
            success += 1
            if success % 50 == 0:
                print(f"  누적 성공: {success}회 (최근: {rnd}회)")
        else:
            fail += 1
            if fail <= 5:  # 첫 5개 실패만 로그
                print(f"  [{rnd}회] 데이터 없음")

    browser.close()

print(f"\n완료 — 성공: {success} | 실패/없음: {fail}")

# ── 저장 ────────────────────────────────────────
sorted_records = sorted(records.values(), key=lambda x: x["round"])
with open(CACHE_FILE, "w", encoding="utf-8") as f:
    json.dump(sorted_records, f, ensure_ascii=False)

print(f"저장: {len(sorted_records)}건 → {CACHE_FILE}")
