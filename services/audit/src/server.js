import express from "express";

const app = express();
app.use(express.json());

app.get("/healthz", (_req, res) => {
  res.json({ ok: true, service: "audit", mode: "stub" });
});

app.post("/run", (req, res) => {
  const { url } = req.body ?? {};
  res.json({
    ok: true,
    url: url ?? null,
    summary: {
      performance_score: null,
      seo_score: null,
      lcp_ms: null,
      cls: null,
      inp_ms: null,
      note: "Lighthouse runner not implemented yet"
    }
  });
});

const port = Number(process.env.PORT ?? 8081);
app.listen(port, () => {
  console.log(`audit stub listening on ${port}`);
});
