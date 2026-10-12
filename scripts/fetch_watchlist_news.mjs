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
const MAX_RANKING_PAGES = 6; // safety cap: 6 * 100 = 600 raw rows per market

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

// finance.naver.com/sise/* and /item/* now 302-redirect to stock.naver.com,
// a client-rendered app with no data in its HTML, so both the ranking and the
// per-stock news are read from the JSON API behind it instead.
const NAVER_API = "https://m.stock.naver.com/api";
const RANKING_PAGE_SIZE = 100;

async function fetchJson(url) {
  const res = await fetch(url, { headers: { "User-Agent": USER_AGENT, Referer: "https://stock.naver.com/" } });
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.json();
}

async function fetchMarketCapPage(market, page) {
  const json = await fetchJson(`${NAVER_API}/stocks/marketValue/${market}?page=${page}&pageSize=${RANKING_PAGE_SIZE}`);
  return (json.stocks || [])
    .filter((d) => d.stockEndType === "stock")
    .map((d) => ({ code: d.itemCode, name: cleanText(d.stockName || "") }));
}

async function fetchTopByMarketCap(market, target) {
  const collected = [];
  const seen = new Set();
  for (let page = 1; page <= MAX_RANKING_PAGES && collected.length < target; page++) {
    const rows = await fetchMarketCapPage(market, page);
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

// The news API groups related articles into clusters; the first item of each
// cluster is the lead article, which is what the old "뉴스공시" list showed.
async function fetchStockNews(code) {
  const clusters = await fetchJson(`${NAVER_API}/news/stock/${code}?pageSize=${MAX_ITEMS_PER_STOCK}&page=1`);
  if (!Array.isArray(clusters)) throw new Error("unexpected response");

  const items = [];
  const seen = new Set();
  for (const cluster of clusters) {
    const d = cluster.items?.[0];
    if (!d) continue;
    const url = d.mobileNewsUrl || `https://n.news.naver.com/mnews/article/${d.officeId}/${d.articleId}`;
    const title = cleanText(d.titleFull || d.title || "");
    if (!title || seen.has(url)) continue;
    seen.add(url);
    const time = (d.datetime || "").replace(/^(\d{4})(\d{2})(\d{2}).*$/, "$1-$2-$3");
    items.push({ title, url, press: cleanText(d.officeName || ""), time });
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

  console.log("Ranking KOSPI/KOSDAQ by market cap…");
  const [kospi, kosdaq] = await Promise.all([
    fetchTopByMarketCap("KOSPI", KOSPI_TARGET),
    fetchTopByMarketCap("KOSDAQ", KOSDAQ_TARGET),
  ]);
  const universe = [...kospi, ...kosdaq];
  // An empty universe means the ranking source broke; fail the run loudly
  // rather than publishing an empty snapshot over yesterday's data.
  if (!universe.length) throw new Error("market-cap ranking returned no stocks");
  console.log(`Universe: ${kospi.length} KOSPI + ${kosdaq.length} KOSDAQ = ${universe.length} stocks`);

  const stocks = [];
  let okCount = 0;
  for (const { code, name, market } of universe) {
    try {
      const { items } = await fetchStockNews(code);
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
