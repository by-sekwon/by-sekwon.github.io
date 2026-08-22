// Collects daily search-trend snapshots from Daum, ZUM, and Google Trends.
// Writes to trends/data/ (versioned source, a declared Quarto resource) and
// mirrors into docs/trends/data/ (published copy) so the trends/index.qmd
// page picks up new data immediately, without waiting on a full site render.
import { chromium } from "playwright";
import { mkdir, readFile, readdir, writeFile, unlink, cp } from "node:fs/promises";
import path from "node:path";

// trends/data is the versioned source of truth (declared as a Quarto
// project resource); docs/trends/data is the published mirror that a full
// `quarto render` would otherwise wipe if it only existed under docs/.
const SRC_DATA_DIR = path.resolve("trends/data");
const OUT_DATA_DIR = path.resolve("docs/trends/data");
const RETENTION_DAYS = 30;

function todayKST() {
  const parts = new Intl.DateTimeFormat("en-CA", {
    timeZone: "Asia/Seoul",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).formatToParts(new Date());
  const get = (t) => parts.find((p) => p.type === t).value;
  return `${get("year")}-${get("month")}-${get("day")}`;
}

function nowKSTIso() {
  return new Date().toLocaleString("sv-SE", { timeZone: "Asia/Seoul" }).replace(" ", "T") + "+09:00";
}

function decodeEntities(str) {
  return str
    .replace(/&lt;/g, "<")
    .replace(/&gt;/g, ">")
    .replace(/&quot;/g, '"')
    .replace(/&apos;/g, "'")
    .replace(/&amp;/g, "&");
}

async function fetchDaum(browser) {
  const page = await browser.newPage({
    userAgent:
      "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 " +
      "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
  });
  try {
    await page.goto("https://www.daum.net/", { waitUntil: "domcontentloaded", timeout: 45_000 });
    await page.waitForSelector(".box_trendrank .list_trendrank li", { timeout: 15_000 });
    const items = await page.$$eval(".box_trendrank .list_trendrank li", (lis) =>
      lis.map((li, i) => {
        const a = li.querySelector("a.link_trendrank");
        const keyword =
          a?.getAttribute("data-tiara-copy") || li.querySelector(".tit_item")?.textContent?.trim() || "";
        return { rank: i + 1, keyword: keyword.trim() };
      }).filter((it) => it.keyword)
    );
    return { items, status: "ok" };
  } catch (err) {
    return { items: [], status: "error", error: err.message };
  } finally {
    await page.close().catch(() => {});
  }
}

async function fetchZum(browser) {
  const page = await browser.newPage({
    userAgent:
      "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 " +
      "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
  });
  try {
    await page.goto("https://www.zum.com/", { waitUntil: "domcontentloaded", timeout: 45_000 });
    await page.waitForSelector(".issue-word-list__keyword-item", { timeout: 15_000 });
    const items = await page.$$eval(".issue-word-list__keyword-item", (lis) =>
      lis.map((li, i) => {
        const keyword = li.querySelector(".issue-word-list__keyword")?.textContent?.trim() || "";
        return { rank: i + 1, keyword };
      }).filter((it) => it.keyword)
    );
    return { items, status: "ok" };
  } catch (err) {
    return { items: [], status: "error", error: err.message };
  } finally {
    await page.close().catch(() => {});
  }
}

async function fetchGoogleTrends() {
  try {
    const res = await fetch("https://trends.google.com/trending/rss?geo=KR", {
      headers: { "User-Agent": "Mozilla/5.0" },
    });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const xml = await res.text();
    const items = [];
    const itemBlocks = xml.match(/<item>[\s\S]*?<\/item>/g) || [];
    for (const block of itemBlocks) {
      const title = block.match(/<title>([\s\S]*?)<\/title>/)?.[1];
      const traffic = block.match(/<ht:approx_traffic>([\s\S]*?)<\/ht:approx_traffic>/)?.[1];
      if (title) {
        items.push({ rank: items.length + 1, keyword: decodeEntities(title.trim()), traffic: traffic?.trim() });
      }
    }
    return { items, status: "ok" };
  } catch (err) {
    return { items: [], status: "error", error: err.message };
  }
}

async function pruneOldFiles(dir, keepDates) {
  const keep = new Set(keepDates);
  let existing;
  try {
    existing = await readdir(dir);
  } catch {
    return;
  }
  for (const file of existing) {
    const m = file.match(/^(\d{4}-\d{2}-\d{2})\.json$/);
    if (m && !keep.has(m[1])) {
      await unlink(path.join(dir, file)).catch(() => {});
    }
  }
}

async function main() {
  await mkdir(SRC_DATA_DIR, { recursive: true });

  const date = todayKST();
  const browser = await chromium.launch({ args: ["--no-sandbox", "--disable-setuid-sandbox"] });

  const [daum, zum, google] = await Promise.all([fetchDaum(browser), fetchZum(browser), fetchGoogleTrends()]);
  await browser.close();

  for (const [name, result] of [["daum", daum], ["zum", zum], ["google", google]]) {
    if (result.status === "error") {
      console.error(`[${name}] failed: ${result.error}`);
    } else {
      console.log(`[${name}] collected ${result.items.length} items`);
    }
  }

  const snapshot = {
    date,
    generatedAt: nowKSTIso(),
    sources: [
      { id: "daum", label: "Daum 실시간 트렌드", sourceUrl: "https://www.daum.net/", ...daum },
      { id: "zum", label: "ZUM AI 이슈 트렌드", sourceUrl: "https://www.zum.com/", ...zum },
      { id: "google", label: "Google Trends", sourceUrl: "https://trends.google.com/trending?geo=KR", ...google },
    ],
  };

  await writeFile(path.join(SRC_DATA_DIR, `${date}.json`), JSON.stringify(snapshot, null, 2));

  const manifestPath = path.join(SRC_DATA_DIR, "manifest.json");
  let dates = [];
  try {
    const raw = JSON.parse(await readFile(manifestPath, "utf-8"));
    dates = raw.dates || [];
  } catch {}
  dates = [date, ...dates.filter((d) => d !== date)].sort((a, b) => (a < b ? 1 : -1)).slice(0, RETENTION_DAYS);

  await writeFile(manifestPath, JSON.stringify({ dates }, null, 2));
  await pruneOldFiles(SRC_DATA_DIR, dates);

  // Mirror into docs/ so the published site reflects today's data immediately,
  // without waiting on the next full `quarto render`.
  await mkdir(OUT_DATA_DIR, { recursive: true });
  await cp(SRC_DATA_DIR, OUT_DATA_DIR, { recursive: true });
  await pruneOldFiles(OUT_DATA_DIR, dates);

  console.log(`Saved snapshot for ${date}. Retained dates: ${dates.join(", ")}`);
}

main().catch((err) => {
  console.error(err);
  process.exitCode = 1;
});
