// Visits each Streamlit Community Cloud app with a real headless browser
// so the websocket connection registers as activity, and auto-clicks the
// "wake up" button if the app has gone to sleep from inactivity.
import { chromium } from "playwright";

const APPS = [
  { name: "로또 번호 생성기", url: "https://by-sekwonappio-8l9qy39rtnnumlftcp5vev.streamlit.app/" },
  { name: "매수적절성 분석기", url: "https://by-sekwonappio-brhv7z6elu8dakgf7ed6ie.streamlit.app/" },
  { name: "KRX 매수 추천 스캐너", url: "https://by-sekwonappio-74lvd7sgtztzyfhztkce9p.streamlit.app/" },
];

const WAKE_BUTTON_PATTERN = /get this app back up|wake.?up|yes,\s*get/i;

async function wakeApp(browser, { name, url }) {
  const page = await browser.newPage();
  try {
    await page.goto(url, { waitUntil: "networkidle", timeout: 60_000 });

    const wakeButton = page.getByRole("button", { name: WAKE_BUTTON_PATTERN });
    if (await wakeButton.isVisible({ timeout: 8_000 }).catch(() => false)) {
      console.log(`[${name}] asleep — clicking wake button`);
      await wakeButton.click();
      // Streamlit spins the container back up; give it time to boot.
      await page.waitForTimeout(45_000);
    } else {
      console.log(`[${name}] already awake — visit registered`);
    }
  } catch (err) {
    console.error(`[${name}] failed: ${err.message}`);
  } finally {
    await page.close();
  }
}

const browser = await chromium.launch();
for (const app of APPS) {
  await wakeApp(browser, app);
}
await browser.close();
