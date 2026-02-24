import fs from "node:fs";
import express from "express";

const app = express();
app.use(express.json({ limit: "1mb" }));

const STUB_MODE = process.env.LIGHTHOUSE_STUB === "1";

const scoreTo100 = (value) => {
  if (typeof value !== "number") return null;
  const n = value <= 1 ? value * 100 : value;
  return Math.round(n);
};

const numericValue = (audits, id) => {
  const node = audits?.[id];
  return typeof node?.numericValue === "number" ? node.numericValue : null;
};

const summarizeLhr = (lhr) => {
  const categories = lhr?.categories ?? {};
  const audits = lhr?.audits ?? {};
  return {
    performance_score: scoreTo100(categories.performance?.score ?? null),
    seo_score: scoreTo100(categories.seo?.score ?? null),
    lcp_ms: numericValue(audits, "largest-contentful-paint"),
    cls: numericValue(audits, "cumulative-layout-shift"),
    inp_ms: numericValue(audits, "interaction-to-next-paint"),
    tbt_ms: numericValue(audits, "total-blocking-time"),
  };
};

const detectChromePath = () => {
  const candidates = [
    process.env.CHROME_PATH,
    "/usr/bin/chromium",
    "/usr/bin/chromium-browser",
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
  ].filter(Boolean);
  for (const candidate of candidates) {
    if (fs.existsSync(candidate)) return candidate;
  }
  return undefined;
};

let lighthouseCache = null;
let chromeLauncherCache = null;
let dependencyLoadError = null;

async function loadLighthouseDeps() {
  if (lighthouseCache && chromeLauncherCache) {
    return { lighthouse: lighthouseCache, chromeLauncher: chromeLauncherCache };
  }
  if (dependencyLoadError) throw dependencyLoadError;
  try {
    const [lhMod, clMod] = await Promise.all([
      import("lighthouse"),
      import("chrome-launcher"),
    ]);
    lighthouseCache = lhMod.default ?? lhMod;
    chromeLauncherCache = clMod.default ?? clMod;
    return { lighthouse: lighthouseCache, chromeLauncher: chromeLauncherCache };
  } catch (err) {
    dependencyLoadError = err;
    throw err;
  }
}

const stubRun = (url, reason = "stub mode") => ({
  ok: true,
  mode: "stub",
  url: url ?? null,
  summary: {
    performance_score: null,
    seo_score: null,
    lcp_ms: null,
    cls: null,
    inp_ms: null,
    tbt_ms: null,
    note: `Lighthouse stub response (${reason})`,
  },
});

app.get("/healthz", async (_req, res) => {
  if (STUB_MODE) {
    return res.json({ ok: true, service: "audit", mode: "stub", lighthouse_ready: false });
  }
  try {
    await loadLighthouseDeps();
    return res.json({
      ok: true,
      service: "audit",
      mode: "lighthouse",
      lighthouse_ready: true,
      chrome_path: detectChromePath() ?? null,
    });
  } catch (err) {
    return res.json({
      ok: true,
      service: "audit",
      mode: "stub-fallback",
      lighthouse_ready: false,
      error: String(err),
    });
  }
});

app.post("/run", async (req, res) => {
  const { url } = req.body ?? {};
  if (!url || typeof url !== "string") {
    return res.status(400).json({ ok: false, error: "missing url" });
  }
  if (STUB_MODE) {
    return res.json(stubRun(url, "LIGHTHOUSE_STUB=1"));
  }

  let deps;
  try {
    deps = await loadLighthouseDeps();
  } catch (err) {
    return res.json(stubRun(url, `deps unavailable: ${String(err)}`));
  }

  const chromePath = detectChromePath();
  if (!chromePath) {
    return res.json(stubRun(url, "chrome binary not found"));
  }

  let chrome;
  try {
    chrome = await deps.chromeLauncher.launch({
      chromePath,
      chromeFlags: ["--headless=new", "--no-sandbox", "--disable-gpu", "--disable-dev-shm-usage"],
    });

    const runnerResult = await deps.lighthouse(url, {
      port: chrome.port,
      output: "json",
      logLevel: "error",
      onlyCategories: ["performance", "seo"],
      formFactor: "mobile",
      screenEmulation: { mobile: true, width: 390, height: 844, deviceScaleFactor: 2, disabled: false },
    });

    const lhr = runnerResult?.lhr ?? null;
    const summary = summarizeLhr(lhr);
    const includeLhr = process.env.LIGHTHOUSE_INCLUDE_LHR === "1";
    return res.json({
      ok: true,
      mode: "lighthouse",
      url,
      summary,
      ...(includeLhr ? { lhr } : {}),
    });
  } catch (err) {
    return res.status(502).json({
      ok: false,
      mode: "lighthouse",
      url,
      error: String(err),
    });
  } finally {
    try {
      if (chrome) await chrome.kill();
    } catch {
      // best-effort cleanup
    }
  }
});

const port = Number(process.env.PORT ?? 8081);
app.listen(port, () => {
  console.log(`audit service listening on ${port}`);
});

