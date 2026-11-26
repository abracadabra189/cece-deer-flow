#!/usr/bin/env node
/**
 * S2 取数包装（真实 HYDC 命令体系）：
 *   1) economicData queryIndustries      产业节点定位（关键词→industryCode）
 *   2) economicData queryIndustryProfile 区域×产业聚合画像（--all true，结构化 groups）
 *   3) economicData queryParkProfile     区域园区
 * 产物落 raw/；归一化由 normalize_data.py 完成。凭据不落地；空结果/报错记 limitation。
 */
import { spawnSync } from "node:child_process";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const HERE = path.dirname(fileURLToPath(import.meta.url));

function arg(name) {
  const i = process.argv.indexOf(name);
  return i >= 0 ? process.argv[i + 1] : null;
}
const specPath = arg("--spec"), outDir = arg("--out");
const fixture = arg("--fixture");

function resolveHydc() {
  const candidates = [
    arg("--hydc"),
    process.env.HYDC_SCRIPT,
    "/mnt/skills/public/cece-hydc-data/scripts/hydc.mjs",
    path.resolve(HERE, "../../cece-hydc-data/scripts/hydc.mjs"),
  ].filter(Boolean);
  for (const c of candidates) if (fs.existsSync(c)) return c;
  return candidates[candidates.length - 1];
}
const hydc = resolveHydc();
if (!specPath || !outDir) {
  console.error("usage: fetch_data.mjs --spec <spec.json> --out <dir> [--fixture <json>] [--hydc <path>]");
  process.exit(2);
}
function envKey() {
  if (String(process.env.HYDC_API_KEY || "").trim()) return process.env.HYDC_API_KEY;
  try { // CLI 回退：与 Gateway 同源读取仓库 .env（gitignored）
    const txt = fs.readFileSync(path.resolve(HERE, "../../../../.env"), "utf8");
    const m = txt.match(/^HYDC_API_KEY=(.*)$/m);
    return m ? m[1].trim() : "";
  } catch {
    return "";
  }
}
if (!fixture && !envKey()) {
  console.error(
    "[industry-insight-report] HYDC_API_KEY 未配置：请在仓库 .env 中填写 HYDC_API_KEY=<token>（或 Bearer <token>）" +
    "并重启 Gateway；容器 sandbox 还需在 config.yaml 的 sandbox.environment 注入 HYDC_API_KEY: $HYDC_API_KEY。" +
    "离线演示请改用 --fixture。");
  process.exit(2);
}
const spec = JSON.parse(fs.readFileSync(specPath, "utf8"));
fs.mkdirSync(path.join(outDir, "data"), { recursive: true });
const now = new Date().toISOString();
const manifest = { as_of: spec.as_of, sources: {}, limitations: [], fetched_at: now };

function writeDataset(name, rows, sourceCmd) {
  const doc = { dataset: name, as_of: spec.as_of, source_cmd: sourceCmd, fetched_at: now, unit: "", rows };
  fs.writeFileSync(path.join(outDir, "data", `${name}.json`), JSON.stringify(doc, null, 2));
  manifest.sources[name] = sourceCmd.startsWith("fixture") ? "行业洞察" : "HYDC:" + sourceCmd.split(" ")[0];
}

if (fixture) {
  const fx = JSON.parse(fs.readFileSync(fixture, "utf8"));
  for (const [name, rows] of Object.entries(fx.datasets)) writeDataset(name, rows, "fixture:" + path.basename(fixture));
  fs.writeFileSync(path.join(outDir, "data", "data_manifest.json"), JSON.stringify(manifest, null, 2));
  console.log(JSON.stringify({ mode: "fixture", datasets: Object.keys(fx.datasets).length }));
  process.exit(0);
}

const rawDir = path.join(outDir, "raw");
fs.mkdirSync(rawDir, { recursive: true });

function call(cmd) {
  const r = spawnSync(process.execPath, [hydc, "query", cmd],
    { encoding: "utf8", timeout: 120000, env: { ...process.env, HYDC_API_KEY: envKey() } });
  if (r.status !== 0 || !r.stdout) {
    manifest.limitations.push({ dataset: cmd.split(" ")[1] || cmd, reason: (r.stderr || "empty").slice(0, 200) });
    return null;
  }
  return r.stdout;
}

// 1) 产业节点定位：industry_code 为中文时按名称解析（优先根节点）
let industryCode = spec.industry_code;
const keyword = spec.industry_name || spec.industry_code;
const indText = call(`economicData queryIndustries --keyword ${keyword} --format json`);
if (indText) {
  fs.writeFileSync(path.join(rawDir, "industries.json"), indText);
  if (/[\u4e00-\u9fa5]/.test(industryCode)) {
    try {
      const items = (JSON.parse(indText).result || JSON.parse(indText)).items || [];
      const exact = items.filter((i) => i.name === keyword || i.rootName === keyword);
      const root = exact.find((i) => i.code === i.rootCode) || exact[0] || items[0];
      if (root) industryCode = root.rootCode && items.some((i) => i.code === i.rootCode && i.rootCode === root.rootCode) ? root.rootCode : root.code;
    } catch { /* 保留原 code */ }
  }
} else {
  manifest.limitations.push({ dataset: "industries", reason: "queryIndustries failed" });
}
fs.writeFileSync(path.join(rawDir, "resolved.json"), JSON.stringify({ industry_code: industryCode, region_code: spec.region_code }, null, 2));

// 2) 区域×产业聚合画像
const profileText = call(`economicData queryIndustryProfile --regionCode ${spec.region_code} --industryCode ${industryCode} --format json --all true`);
if (profileText) fs.writeFileSync(path.join(rawDir, "profile.json"), profileText);
else manifest.limitations.push({ dataset: "profile", reason: "queryIndustryProfile failed" });

// 3) 区域园区
const parksText = call(`economicData queryParkProfile --regionCode ${spec.region_code} --format json`);
if (parksText) fs.writeFileSync(path.join(rawDir, "parks.json"), parksText);
else manifest.limitations.push({ dataset: "parks", reason: "queryParkProfile failed" });

fs.writeFileSync(path.join(outDir, "data", "data_manifest.json"), JSON.stringify(manifest, null, 2));
console.log(JSON.stringify({ mode: "hydc", industry_code: industryCode, limitations: manifest.limitations.length }));
process.exit(profileText ? 0 : 1);
