// Generates cloudflare-worker/stock-search-worker.js by embedding the KRX
// ticker list (stock_kr_tickers.csv) into a worker template. Run this again
// only if the ticker list needs refreshing — the worker itself is a
// standalone deployable file (paste into the Cloudflare dashboard, or
// `wrangler deploy`), not part of the Quarto site build.
import { readFile, writeFile } from "node:fs/promises";

const csv = await readFile("stock_kr_tickers.csv", "utf-8");
const lines = csv.replace(/^﻿/, "").trim().split("\n");
lines.shift(); // header row
const tickers = lines.map((line) => {
  const [code, name, market] = line.split(",");
  return [code, name, market];
});

const template = await readFile("cloudflare-worker/stock-search-worker.template.js", "utf-8");
const output = template.replace("__TICKERS__", JSON.stringify(tickers));

await writeFile("cloudflare-worker/stock-search-worker.js", output);
console.log(`Embedded ${tickers.length} tickers into cloudflare-worker/stock-search-worker.js`);
