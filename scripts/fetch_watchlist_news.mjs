// Collects a daily snapshot of per-stock news ("뉴스공시") for a fixed
// watchlist of large-cap KOSPI stocks, from Naver Finance's per-stock page.
// This is a registered-watchlist search, not a live arbitrary-keyword
// search: a static site has no backend to proxy a browser's cross-origin
// search request, so per-stock news is pre-fetched here (server-side, no
// CORS issue) once a day and the frontend just picks from this fixed list.
//
// Writes to playground/data/watchlist_news/ (versioned source, a declared
// Quarto resource) and mirrors into docs/playground/data/watchlist_news/
// (published copy) so playground/posts/watchlist_news.qmd picks up new
// data immediately, without waiting on a full `quarto render`.
import { mkdir, readFile, readdir, writeFile, unlink, cp } from "node:fs/promises";
import path from "node:path";

const SRC_DATA_DIR = path.resolve("playground/data/watchlist_news");
const OUT_DATA_DIR = path.resolve("docs/playground/data/watchlist_news");
const RETENTION_DAYS = 14;
const MAX_ITEMS_PER_STOCK = 20;

const USER_AGENT =
  "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36";

// Starting watchlist: KOSPI top-10 by market cap. Add/remove entries here
// to change what's searchable on the page — no other code changes needed.
const WATCHLIST = [
  { code: "005930", name: "삼성전자" },
  { code: "000660", name: "SK하이닉스" },
  { code: "373220", name: "LG에너지솔루션" },
  { code: "207940", name: "삼성바이오로직스" },
  { code: "005380", name: "현대차" },
  { code: "000270", name: "기아" },
  { code: "068270", name: "셀트리온" },
  { code: "035420", name: "NAVER" },
  { code: "035720", name: "카카오" },
  { code: "005490", name: "POSCO홀딩스" },
];

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

const NAMED_ENTITIES = {
  hellip: "…", ldquo: "“", rdquo: "”", lsquo: "‘", rsquo: "’",
  middot: "·", uarr: "↑", darr: "↓", nbsp: " ",
  lt: "<", gt: ">", quot: '"', apos: "'",
};

function decodeEntities(str) {
  return str
    .replace(/&#x([0-9a-f]+);/gi, (_, hex) => String.fromCodePoint(parseInt(hex, 16)))
    .replace(/&#(\d+);/g, (_, dec) => String.fromCodePoint(parseInt(dec, 10)))
    .replace(/&([a-z]+);/gi, (m, name) => NAMED_ENTITIES[name.toLowerCase()] ?? m)
    .replace(/&amp;/g, "&");
}

function cleanText(str) {
  return decodeEntities(str.replace(/<[^>]+>/g, " ").replace(/\s+/g, " ").trim());
}

function sleep(ms) {
  return new Promise((r) => setTimeout(r, ms));
}

// Naver Finance's per-stock page (item/main.naver) is UTF-8, unlike the
// news_list.naver pages used for the general 증권 news feed.
async function fetchStockNews(code, name, year) {
  const sourceUrl = `https://finance.naver.com/item/main.naver?code=${code}`;
  const res = await fetch(sourceUrl, { headers: { "User-Agent": USER_AGENT } });
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  const html = await res.text();

  const sectionMatch = html.match(/<span>뉴스공시<\/span><\/h4>([\s\S]*?)<hr>/);
  if (!sectionMatch) throw new Error("news section not found");
  const sectionHtml = sectionMatch[1];

  const itemRe =
    /<a href="(\/item\/news_read\.naver\?[^"]+)"[^>]*>([\s\S]*?)<\/a>\s*(?:<a[^>]*class="link_relation"[^>]*>[\s\S]*?<\/a>\s*)?<\/span>\s*<em>\s*([\d/]+)\s*<\/em>/g;

  const items = [];
  const seen = new Set();
  let m;
  while ((m = itemRe.exec(sectionHtml)) !== null) {
    const [, href, titleHtml, mmdd] = m;
    const url = `https://finance.naver.com${href}`;
    const title = cleanText(titleHtml);
    if (!title || seen.has(url)) continue;
    seen.add(url);
    items.push({ title, url, time: `${year}-${mmdd.replace("/", "-")}` });
  }
  return {
    code,
    name,
    sourceUrl,
    status: "ok",
    items: items.slice(0, MAX_ITEMS_PER_STOCK).map((it, i) => ({ rank: i + 1, ...it })),
  };
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
  const year = date.slice(0, 4);

  const stocks = [];
  for (const { code, name } of WATCHLIST) {
    try {
      const stock = await fetchStockNews(code, name, year);
      console.log(`[watchlist_news:${code}] ${name}: collected ${stock.items.length} items`);
      stocks.push(stock);
    } catch (err) {
      console.error(`[watchlist_news:${code}] ${name} failed: ${err.message}`);
      stocks.push({ code, name, sourceUrl: `https://finance.naver.com/item/main.naver?code=${code}`, status: "error", error: err.message, items: [] });
    }
    await sleep(150);
  }

  const snapshot = { date, generatedAt: nowKSTIso(), stocks };

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

  console.log(`Saved watchlist snapshot for ${date}. Retained dates: ${dates.join(", ")}`);
}

main().catch((err) => {
  console.error(err);
  process.exitCode = 1;
});
