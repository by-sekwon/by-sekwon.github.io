// Collects a daily snapshot of per-stock news ("뉴스공시") for the current
// KOSPI top-200 + KOSDAQ top-100 companies by market cap (~300 total),
// re-derived fresh every run from Naver's market-cap ranking pages so the
// universe stays current as rankings shift — no hardcoded stock list to
// maintain. This is a registered-watchlist search, not a live
// arbitrary-keyword search: a static site has no backend to proxy a
// browser's cross-origin search request, so per-stock news is pre-fetched
// here (server-side, no CORS issue) once a day and the frontend just
// searches within this pre-fetched list.
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
const MAX_ITEMS_PER_STOCK = 15;
const KOSPI_TARGET = 200;
const KOSDAQ_TARGET = 100;
const REQUEST_DELAY_MS = 120;
const MAX_RANKING_PAGES = 12; // safety cap: 12 * 50 = 600 raw rows per market

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

// KRX convention: a common-stock code ends in "0"; preferred-share classes
// of the same issuer end in "5", "6", "7"... — skip those, since they'd
// mostly duplicate the common stock's own news under a name nobody searches.
function isCommonStock(code) {
  return /0$/.test(code);
}

async function fetchMarketCapPage(sosok, page) {
  const url = `https://finance.naver.com/sise/sise_market_sum.naver?sosok=${sosok}&page=${page}`;
  const res = await fetch(url, { headers: { "User-Agent": USER_AGENT } });
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  const buf = await res.arrayBuffer();
  const html = new TextDecoder("euc-kr").decode(buf);
  const rowRe = /<a href="\/item\/main\.naver\?code=(\d{6})" class="tltle">([^<]*)<\/a>/g;
  const rows = [];
  let m;
  while ((m = rowRe.exec(html)) !== null) {
    rows.push({ code: m[1], name: cleanText(m[2]) });
  }
  return rows;
}

async function fetchTopByMarketCap(sosok, market, target) {
  const collected = [];
  const seen = new Set();
  for (let page = 1; page <= MAX_RANKING_PAGES && collected.length < target; page++) {
    const rows = await fetchMarketCapPage(sosok, page);
    if (!rows.length) break; // ran past the last page
    for (const row of rows) {
      if (!isCommonStock(row.code) || seen.has(row.code)) continue;
      seen.add(row.code);
      collected.push({ code: row.code, name: row.name, market });
      if (collected.length >= target) break;
    }
    await sleep(REQUEST_DELAY_MS);
  }
  return collected;
}

// Naver Finance's per-stock page (item/main.naver) is UTF-8, unlike the
// EUC-KR sise_market_sum.naver ranking pages above.
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
  return { items: items.slice(0, MAX_ITEMS_PER_STOCK).map((it, i) => ({ rank: i + 1, ...it })) };
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

  console.log("Ranking KOSPI/KOSDAQ by market cap…");
  const [kospi, kosdaq] = await Promise.all([
    fetchTopByMarketCap(0, "KOSPI", KOSPI_TARGET),
    fetchTopByMarketCap(1, "KOSDAQ", KOSDAQ_TARGET),
  ]);
  const universe = [...kospi, ...kosdaq];
  console.log(`Universe: ${kospi.length} KOSPI + ${kosdaq.length} KOSDAQ = ${universe.length} stocks`);

  const stocks = [];
  let okCount = 0;
  for (const { code, name, market } of universe) {
    try {
      const { items } = await fetchStockNews(code, name, year);
      stocks.push({ code, name, market, status: "ok", items });
      okCount++;
    } catch (err) {
      stocks.push({ code, name, market, status: "error", error: err.message, items: [] });
    }
    await sleep(REQUEST_DELAY_MS);
  }
  console.log(`Collected news for ${okCount}/${universe.length} stocks`);

  const snapshot = { date, generatedAt: nowKSTIso(), stocks };

  await writeFile(path.join(SRC_DATA_DIR, `${date}.json`), JSON.stringify(snapshot));

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
