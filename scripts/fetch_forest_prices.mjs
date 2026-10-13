// Collects daily wholesale auction (경락) prices for a fixed list of forest
// products from 농넷(nongnet.or.kr) "전국도매시장 경락정보". 농넷 serves that
// dashboard from a Qlik Sense app that allows anonymous sessions, so this
// talks to the same Qlik Engine JSON-RPC websocket the dashboard itself uses
// (there is no official REST API for it). If 농넷 changes the app id or field
// names, this is the place to fix.
//
// Every run re-downloads the whole window (START_YEAR-01-01 ~ today) as one
// item x variety x date table, since past days can still be revised, and
// overwrites a single prices.json.
//
// Writes to playground/data/forest_prices/ (versioned source, a declared
// Quarto resource) and mirrors into docs/playground/data/forest_prices/
// (published copy) so playground/posts/forest_prices.qmd picks up new data
// immediately, without waiting on a full `quarto render`.
//
// Needs Node 22+ (global WebSocket).
import { mkdir, writeFile, cp } from "node:fs/promises";
import path from "node:path";

const SRC_DATA_DIR = path.resolve("playground/data/forest_prices");
const OUT_DATA_DIR = path.resolve("docs/playground/data/forest_prices");

const APP_ID = "551d7860-2a5d-49e5-915e-56517f3da2a3";
const WS_URL = `wss://www.nongnet.or.kr/qlik/sso/app/${APP_ID}`;
const START_YEAR = 2026;
// label = 사이트에 보여줄 임업 품목명, field = 농넷 `품목명_선택` 값
const ITEMS = [
  { label: "밤", field: "밤" },
  { label: "대추", field: "대추" },
  { label: "호두", field: "호두" },
  { label: "떫은감", field: "떫은감" },
  { label: "표고버섯", field: "표고버섯" },
  { label: "고사리", field: "고사리" },
  { label: "복분자딸기", field: "복분자" },
];
const PAGE_ROWS = 2000; // Qlik caps one fetch at 10,000 cells (5 columns here)
const RPC_TIMEOUT_MS = 60_000;

function nowKSTIso() {
  return new Date().toLocaleString("sv-SE", { timeZone: "Asia/Seoul" }).replace(" ", "T") + "+09:00";
}

function connect() {
  return new Promise((resolve, reject) => {
    const ws = new WebSocket(WS_URL);
    const pending = new Map();
    let nextId = 0;

    const call = (handle, method, params = []) =>
      new Promise((res, rej) => {
        const id = ++nextId;
        const timer = setTimeout(() => {
          pending.delete(id);
          rej(new Error(`${method} timed out`));
        }, RPC_TIMEOUT_MS);
        pending.set(id, { res, rej, timer });
        ws.send(JSON.stringify({ jsonrpc: "2.0", id, handle, method, params }));
      });

    ws.onmessage = (e) => {
      const msg = JSON.parse(e.data);
      const p = msg.id && pending.get(msg.id);
      if (!p) return;
      pending.delete(msg.id);
      clearTimeout(p.timer);
      if (msg.error) p.rej(new Error(`${msg.error.message} (${msg.error.code})`));
      else p.res(msg.result);
    };
    ws.onerror = (e) => reject(new Error(`websocket error: ${e.message || "connection failed"}`));
    ws.onopen = () => resolve({ call, close: () => ws.close() });
  });
}

async function fetchRows(call) {
  const doc = await call(-1, "OpenDoc", [APP_ID]);
  const docHandle = doc.qReturn.qHandle;

  const itemSet = ITEMS.map((it) => `'${it.field}'`).join(",");
  const set = `{<품목명_선택={${itemSet}},경락년도={">=${START_YEAR}"},단위명={'kg'}>}`;
  const cube = await call(docHandle, "CreateSessionObject", [{
    qInfo: { qType: "forest-prices" },
    qHyperCubeDef: {
      qDimensions: [
        { qDef: { qFieldDefs: ["품목명_선택"] } },
        { qDef: { qFieldDefs: ["품종명"] } },
        { qDef: { qFieldDefs: ["경락일자_Date"] } },
      ],
      qMeasures: [
        { qDef: { qDef: `Sum(${set} 총금액)` } },
        { qDef: { qDef: `Sum(${set} 총물량)` } },
      ],
      qSuppressZero: true,
      qSuppressMissing: true,
    },
  }]);
  const cubeHandle = cube.qReturn.qHandle;

  const layout = await call(cubeHandle, "GetLayout");
  const total = layout.qLayout.qHyperCube.qSize.qcy;
  const rows = [];
  for (let top = 0; top < total; top += PAGE_ROWS) {
    const page = await call(cubeHandle, "GetHyperCubeData", [
      "/qHyperCubeDef",
      [{ qTop: top, qLeft: 0, qWidth: 5, qHeight: PAGE_ROWS }],
    ]);
    rows.push(...page.qDataPages[0].qMatrix);
  }
  if (rows.length !== total) throw new Error(`expected ${total} rows, got ${rows.length}`);
  return rows;
}

function buildItems(rows) {
  const byItem = new Map(ITEMS.map((it) => [it.field, new Map()]));
  for (const [item, variety, date, amount, volume] of rows) {
    const varieties = byItem.get(item.qText);
    if (!varieties) continue;
    if (!/^\d{4}-\d{2}-\d{2}$/.test(date.qText)) continue;
    if (!(amount.qNum > 0) || !(volume.qNum > 0)) continue;
    const name = variety.qText && variety.qText !== "-" ? variety.qText : "미분류";
    if (!varieties.has(name)) varieties.set(name, []);
    // [경락일, 총금액(원), 총물량(kg)]
    varieties.get(name).push([date.qText, Math.round(amount.qNum), Math.round(volume.qNum * 10) / 10]);
  }

  return ITEMS.map((it) => {
    const varieties = [...byItem.get(it.field)].map(([name, rows]) => {
      rows.sort((a, b) => (a[0] < b[0] ? -1 : 1));
      return { name, volume: rows.reduce((s, r) => s + r[2], 0), rows };
    });
    // 거래 물량이 많은 품종부터
    varieties.sort((a, b) => b.volume - a.volume);
    return {
      name: it.label,
      sourceName: it.field,
      varieties: varieties.map(({ name, rows }) => ({ name, rows })),
    };
  });
}

async function main() {
  const { call, close } = await connect();
  let rows;
  try {
    rows = await fetchRows(call);
  } finally {
    close();
  }

  const items = buildItems(rows);
  const empty = items.filter((it) => !it.varieties.length).map((it) => it.name);
  // 한 품목이라도 통째로 비면 농넷 쪽 품목명이 바뀐 것 — 기존 파일을 덮어쓰지 않고 실패시킨다.
  if (empty.length) throw new Error(`no data for: ${empty.join(", ")}`);

  const dates = items.flatMap((it) => it.varieties.flatMap((v) => v.rows.map((r) => r[0]))).sort();
  const snapshot = {
    generatedAt: nowKSTIso(),
    source: "농넷 전국도매시장 경락정보 (nongnet.or.kr)",
    from: dates[0],
    to: dates[dates.length - 1],
    columns: ["date", "amountWon", "volumeKg"],
    items,
  };

  await mkdir(SRC_DATA_DIR, { recursive: true });
  await writeFile(path.join(SRC_DATA_DIR, "prices.json"), JSON.stringify(snapshot));

  // Mirror into docs/ so the published site reflects today's data immediately,
  // without waiting on the next full `quarto render`.
  await mkdir(OUT_DATA_DIR, { recursive: true });
  await cp(SRC_DATA_DIR, OUT_DATA_DIR, { recursive: true });

  const counts = items.map((it) => `${it.name} ${it.varieties.reduce((s, v) => s + v.rows.length, 0)}`).join(", ");
  console.log(`Saved forest prices ${snapshot.from} ~ ${snapshot.to} (${rows.length} rows: ${counts})`);
}

main().catch((err) => {
  console.error(err);
  process.exitCode = 1;
});
