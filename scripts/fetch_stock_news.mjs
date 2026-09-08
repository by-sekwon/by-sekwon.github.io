// Collects a daily snapshot of Naver Finance's "증권" (stocks) news list.
// Writes to playground/data/stock_news/ (versioned source, a declared Quarto
// resource) and mirrors into docs/playground/data/stock_news/ (published
// copy) so playground/posts/stock_news.qmd picks up new data immediately,
// without waiting on a full `quarto render`.
import { mkdir, readFile, readdir, writeFile, unlink, cp } from "node:fs/promises";
import path from "node:path";

const SRC_DATA_DIR = path.resolve("playground/data/stock_news");
const OUT_DATA_DIR = path.resolve("docs/playground/data/stock_news");
const RETENTION_DAYS = 30;

const SOURCE_URL = "https://finance.naver.com/news/news_list.naver?mode=LSS2D&section_id=101&section_id2=258";
const SOURCE_LABEL = "네이버 증권 · 증권 뉴스";

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

// Naver Finance serves this page as EUC-KR; Node's built-in TextDecoder
// (full-ICU by default) can decode it directly, no extra dependency needed.
async function fetchStockNews() {
  const res = await fetch(SOURCE_URL, { headers: { "User-Agent": USER_AGENT } });
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  const buf = await res.arrayBuffer();
  const html = new TextDecoder("euc-kr").decode(buf);

  // Title comes from the anchor's inner text, not its title="" attribute:
  // Naver's markup leaves literal quote characters unescaped inside title=""
  // for headlines that themselves contain quotes, which truncates a
  // quote-delimited attribute capture. The inner text is properly entity-encoded.
  const itemRe =
    /<d[td] class="articleSubject">\s*<a href="([^"]+)"[^>]*>([\s\S]*?)<\/a>\s*<\/d[td]>\s*<dd class="articleSummary">([\s\S]*?)<span class="press">([^<]*)<\/span>[\s\S]*?<span class="wdate">([^<]*)<\/span>/g;

  const items = [];
  const seen = new Set();
  let m;
  while ((m = itemRe.exec(html)) !== null) {
    const [, href, titleHtml, summaryHtml, press, wdate] = m;
    const url = href.startsWith("http") ? href : `https://finance.naver.com${href}`;
    const cleanTitle = cleanText(titleHtml);
    if (!cleanTitle || seen.has(url)) continue;
    seen.add(url);
    items.push({
      rank: items.length + 1,
      title: cleanTitle,
      url,
      press: cleanText(press),
      time: cleanText(wdate),
      summary: cleanText(summaryHtml),
    });
  }
  return items;
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
  let items = [];
  let status = "ok";
  let error;
  try {
    items = await fetchStockNews();
    if (!items.length) throw new Error("no items parsed");
  } catch (err) {
    status = "error";
    error = err.message;
    console.error(`[stock_news] failed: ${error}`);
  }
  if (status === "ok") console.log(`[stock_news] collected ${items.length} items`);

  const snapshot = {
    date,
    generatedAt: nowKSTIso(),
    sourceLabel: SOURCE_LABEL,
    sourceUrl: SOURCE_URL,
    status,
    ...(error ? { error } : {}),
    items,
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
