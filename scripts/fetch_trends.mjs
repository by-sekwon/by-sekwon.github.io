// Collects daily search-trend snapshots from Daum, ZUM, and Google Trends.
// Writes to trends/data/ (versioned source, a declared Quarto resource) and
// mirrors into docs/trends/data/ (published copy) so the trends/index.qmd
// page picks up new data immediately, without waiting on a full site render.
import { chromium } from "playwright";
import Anthropic from "@anthropic-ai/sdk";
import { zodOutputFormat } from "@anthropic-ai/sdk/helpers/zod";
import { z } from "zod";
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

// ZUM's search results are rendered client-side, so this needs a real page.
async function fetchZumNewsFor(browser, keyword) {
  const page = await browser.newPage({ userAgent: USER_AGENT });
  try {
    const url = `https://search.zum.com/search.zum?method=uni&option=accu&query=${encodeURIComponent(keyword)}`;
    await page.goto(url, { waitUntil: "domcontentloaded", timeout: 20_000 });
    const link = await page.waitForSelector('li[class*="NewsList-module"][class*="list_item"] a[href]', {
      timeout: 10_000,
    }).catch(() => null);
    if (!link) return null;
    const href = await link.getAttribute("href");
    const titleEl = await link.$('[class*="item_title"]');
    const siteEl = await link.$('[class*="item_site"]');
    const title = (await titleEl?.textContent())?.trim();
    const source = (await siteEl?.textContent())?.trim();
    if (!title || !href) return null;
    return { title, url: href, source };
  } catch {
    return null;
  } finally {
    await page.close().catch(() => {});
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

async function fetchZum(browser) {
  const page = await browser.newPage({
    userAgent: USER_AGENT,
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

const CurationSchema = z.object({
  items: z
    .array(
      z.object({
        keyword: z.string().describe("짧은 이슈 이름 (한국어, 5~15자 내외)"),
        reason: z
          .string()
          .describe("이 이슈가 왜 상위권인지 한 문장으로. 반드시 제공된 뉴스 제목/검색어에 있는 사실만 사용."),
        sources: z
          .array(z.enum(["daum", "zum", "google"]))
          .describe("이 이슈를 언급한 출처 (여러 소스에 동시에 뜬 경우 전부 포함)"),
      }),
    )
    .max(10)
    .describe("교차 소스 중요도 순으로 정렬된 상위 이슈 목록 (최대 10개, 입력 이슈 수가 적으면 그보다 적어도 됨)"),
});

// Asks Claude to synthesize a single "top 10" list across the three raw
// sources: merge the same real-world story when it appears under different
// keywords on different portals, and rank by how many sources carry it.
// Grounded strictly in the keywords/headlines already scraped above — Claude
// is explicitly told not to use outside knowledge, since it has no way to
// verify today's actual news and must not guess at fast-moving real events.
async function curateWithClaude(daum, zum, google) {
  if (!process.env.ANTHROPIC_API_KEY) {
    return { items: [], status: "error", error: "ANTHROPIC_API_KEY not set" };
  }

  const digest = [
    { source: "daum", ok: daum.status === "ok", items: daum.items },
    { source: "zum", ok: zum.status === "ok", items: zum.items },
    { source: "google", ok: google.status === "ok", items: google.items },
  ]
    .filter((s) => s.ok && s.items.length)
    .map((s) => ({
      source: s.source,
      items: s.items.map((it) => ({
        keyword: it.keyword,
        news_title: it.news?.title || null,
      })),
    }));

  if (!digest.length) {
    return { items: [], status: "error", error: "no source data available to curate" };
  }

  try {
    const client = new Anthropic();
    const response = await client.messages.parse({
      model: "claude-opus-5",
      max_tokens: 4096,
      output_config: {
        effort: "medium",
        format: zodOutputFormat(CurationSchema),
      },
      system:
        "너는 한국 포털 실시간 검색어 데이터를 종합하는 편집자다. 아래 JSON은 Daum·ZUM·Google Trends에서 " +
        "오늘 실제로 수집된 검색어와 관련 뉴스 제목이다. 이 데이터에 없는 사실을 절대 추가하거나 추측하지 마라 " +
        "(너는 실시간 정보를 모른다). 같은 실제 사건을 가리키는 서로 다른 키워드는 하나의 이슈로 합치고, " +
        "여러 소스에 동시에 뜬 이슈를 우선순위로 두어 상위 10개 이내로 정리하라.",
      messages: [{ role: "user", content: JSON.stringify(digest) }],
    });

    if (!response.parsed_output) {
      return { items: [], status: "error", error: "failed to parse structured output" };
    }

    const items = response.parsed_output.items.map((it, i) => ({
      rank: i + 1,
      keyword: it.keyword,
      news: { title: it.reason, source: it.sources.join(", ") },
    }));
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

  if (daum.status === "ok") await attachNews(daum.items, fetchDaumNewsFor);
  if (zum.status === "ok") await attachNews(zum.items, (keyword) => fetchZumNewsFor(browser, keyword));

  await browser.close();

  const claude = await curateWithClaude(daum, zum, google);

  for (const [name, result] of [["daum", daum], ["zum", zum], ["google", google], ["claude", claude]]) {
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
      { id: "claude", label: "Claude 종합 Top 10", sourceUrl: null, ...claude },
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
