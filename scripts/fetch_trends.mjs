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

const USER_AGENT =
  "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36";

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
    .replace(/&#x([0-9a-f]+);/gi, (_, hex) => String.fromCodePoint(parseInt(hex, 16)))
    .replace(/&#(\d+);/g, (_, dec) => String.fromCodePoint(parseInt(dec, 10)))
    .replace(/&lt;/g, "<")
    .replace(/&gt;/g, ">")
    .replace(/&quot;/g, '"')
    .replace(/&apos;/g, "'")
    .replace(/&amp;/g, "&");
}

// Looks up the top news headline Daum's own news search returns for a
// keyword, so each trend item can show a concrete "why is this trending"
// reference instead of a bare keyword. Daum's search results are
// server-rendered, so a plain fetch is enough (no browser needed).
async function fetchDaumNewsFor(keyword) {
  try {
    const url = `https://search.daum.net/search?w=news&q=${encodeURIComponent(keyword)}`;
    const res = await fetch(url, { headers: { "User-Agent": USER_AGENT } });
    if (!res.ok) return null;
    const html = await res.text();
    const m = html.match(/<div class="item-title">\s*<strong[^>]*>\s*<a href="([^"]+)"[^>]*>([\s\S]*?)<\/a>/);
    if (!m) return null;
    const title = decodeEntities(m[2].replace(/<[^>]+>/g, "").replace(/\s+/g, " ").trim());
    if (!title) return null;
    return { title, url: m[1] };
  } catch {
    return null;
  }
}

async function attachNews(items, lookup) {
  for (const item of items) {
    item.news = await lookup(item.keyword);
    await new Promise((r) => setTimeout(r, 200));
  }
  return items;
}

async function fetchDaum(browser) {
  const page = await browser.newPage({
    userAgent: USER_AGENT,
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

// Pulls the JSON array that follows `"<key>":` out of a string, matching
// brackets while skipping over string contents.
function extractJsonArray(text, key) {
  const start = text.indexOf(`"${key}":[`);
  if (start === -1) return null;
  const from = start + key.length + 3;
  let depth = 0;
  let inStr = false;
  for (let i = from; i < text.length; i++) {
    const c = text[i];
    if (inStr) {
      if (c === "\\") i++;
      else if (c === '"') inStr = false;
    } else if (c === '"') inStr = true;
    else if (c === "[" || c === "{") depth++;
    else if ((c === "]" || c === "}") && --depth === 0) return JSON.parse(text.slice(from, i + 1));
  }
  return null;
}

// ZUM's issue trend widget is now a one-card-at-a-time carousel, so the DOM
// only ever holds the current card. The full ranking (with related news)
// ships in the Next.js flight payload, which a plain fetch can read.
async function fetchZum() {
  try {
    const res = await fetch("https://www.zum.com/", { headers: { "User-Agent": USER_AGENT } });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const html = await res.text();
    const flight = [...html.matchAll(/self\.__next_f\.push\(\[1,("(?:[^"\\]|\\.)*")\]\)/g)]
      .map((m) => JSON.parse(m[1]))
      .join("");
    const words = extractJsonArray(flight, "issueWords");
    if (!words?.length) throw new Error("issueWords payload not found");
    const items = words
      .slice(0, 10)
      .map((w, i) => {
        const n = w.news?.[0];
        const url = n?.webLink || n?.originalUrl;
        const news = n?.title && url ? { title: n.title.trim(), url, source: new URL(url).hostname.replace(/^www\./, "") } : null;
        return { rank: i + 1, keyword: (w.keyword || "").trim(), news };
      })
      .filter((it) => it.keyword);
    return { items, status: "ok" };
  } catch (err) {
    return { items: [], status: "error", error: err.message };
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
      if (!title) continue;
      // Google Trends bundles the news articles behind each trend; the first
      // one is a ready-made "why is this trending" reference, no extra fetch needed.
      const newsBlock = block.match(/<ht:news_item>([\s\S]*?)<\/ht:news_item>/)?.[1];
      const newsTitle = newsBlock?.match(/<ht:news_item_title>([\s\S]*?)<\/ht:news_item_title>/)?.[1];
      const newsUrl = newsBlock?.match(/<ht:news_item_url>([\s\S]*?)<\/ht:news_item_url>/)?.[1];
      const newsSource = newsBlock?.match(/<ht:news_item_source>([\s\S]*?)<\/ht:news_item_source>/)?.[1];
      const news = newsTitle && newsUrl
        ? { title: decodeEntities(newsTitle.trim()), url: newsUrl.trim(), source: newsSource?.trim() }
        : null;
      items.push({ rank: items.length + 1, keyword: decodeEntities(title.trim()), traffic: traffic?.trim(), news });
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

  const [daum, zum, google] = await Promise.all([fetchDaum(browser), fetchZum(), fetchGoogleTrends()]);

  if (daum.status === "ok") await attachNews(daum.items, fetchDaumNewsFor);

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
      { id: "google", label: "Google Trends", sourceUrl: "https://trends.google.com/trending?geo=KR", ...google },
      { id: "daum", label: "Daum 실시간 트렌드", sourceUrl: "https://www.daum.net/", ...daum },
      { id: "zum", label: "ZUM AI 이슈 트렌드", sourceUrl: "https://www.zum.com/", ...zum },
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
