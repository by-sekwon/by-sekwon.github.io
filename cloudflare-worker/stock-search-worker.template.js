// Cloudflare Worker: live search + per-stock news proxy for
// playground/posts/watchlist_news.qmd on by-sekwon.github.io.
//
// A static GitHub Pages site can't let a visitor's browser fetch
// finance.naver.com directly (no CORS headers there), so this small
// server-side proxy does the fetch instead and returns CORS-enabled JSON.
//
// Endpoints:
//   GET /search?q=<종목명 또는 코드>  -> {query, results: [{code, name, market}]}
//   GET /news?code=<6자리 코드>       -> {code, name, sourceUrl, items: [...]}
//
// Deploy: paste this whole file into a new Cloudflare Worker (dashboard
// Quick Edit) and click Deploy, or `wrangler deploy` with this as main.
// Regenerate by editing stock-search-worker.template.js and re-running
// `node scripts/build_search_worker.mjs` from the repo root (only needed
// if the KRX ticker list changes — rare).

const TICKERS = __TICKERS__; // [[code, name, market], ...]

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

function corsHeaders() {
  return {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Methods": "GET, OPTIONS",
    "Access-Control-Max-Age": "86400",
  };
}

function json(data, status = 200) {
  return new Response(JSON.stringify(data), {
    status,
    headers: { "Content-Type": "application/json; charset=utf-8", ...corsHeaders() },
  });
}

function searchTickers(q) {
  const query = q.trim().toLowerCase();
  if (!query) return [];
  const matches = [];
  for (const [code, name, market] of TICKERS) {
    if (code.includes(query) || name.toLowerCase().includes(query)) {
      matches.push({ code, name, market });
      if (matches.length >= 15) break;
    }
  }
  return matches;
}

const USER_AGENT =
  "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36";

async function fetchStockNews(code) {
  const known = TICKERS.find((t) => t[0] === code);
  const name = known ? known[1] : code;
  const sourceUrl = `https://finance.naver.com/item/main.naver?code=${code}`;
  const res = await fetch(sourceUrl, { headers: { "User-Agent": USER_AGENT } });
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  const html = await res.text();

  const sectionMatch = html.match(/<span>뉴스공시<\/span><\/h4>([\s\S]*?)<hr>/);
  if (!sectionMatch) throw new Error("news section not found");
  const sectionHtml = sectionMatch[1];

  const itemRe =
    /<a href="(\/item\/news_read\.naver\?[^"]+)"[^>]*>([\s\S]*?)<\/a>\s*(?:<a[^>]*class="link_relation"[^>]*>[\s\S]*?<\/a>\s*)?<\/span>\s*<em>\s*([\d/]+)\s*<\/em>/g;

  const year = new Date().getUTCFullYear();
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
    if (items.length >= 20) break;
  }
  return { code, name, sourceUrl, items: items.map((it, i) => ({ rank: i + 1, ...it })) };
}

export default {
  async fetch(request, env, ctx) {
    const url = new URL(request.url);

    if (request.method === "OPTIONS") {
      return new Response(null, { status: 204, headers: corsHeaders() });
    }

    if (url.pathname === "/search") {
      const q = url.searchParams.get("q") || "";
      return json({ query: q, results: searchTickers(q) });
    }

    if (url.pathname === "/news") {
      const code = url.searchParams.get("code") || "";
      if (!/^\d{6}$/.test(code)) return json({ error: "invalid code" }, 400);

      // Cache each stock's news for 10 minutes so repeat visitors are fast
      // and Naver doesn't see a fresh request per pageview.
      const cache = caches.default;
      const cacheKey = new Request(url.toString(), { method: "GET" });
      const cached = await cache.match(cacheKey);
      if (cached) return cached;

      try {
        const stock = await fetchStockNews(code);
        const resp = json(stock);
        resp.headers.set("Cache-Control", "public, max-age=600");
        ctx.waitUntil(cache.put(cacheKey, resp.clone()));
        return resp;
      } catch (err) {
        return json({ error: err.message }, 502);
      }
    }

    return json({ error: "not found" }, 404);
  },
};
