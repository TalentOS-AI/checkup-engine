# checkup-engine

Open-source **AI-readiness checkup** for small-business websites.

> Early stage (v0.1). The rubric and collectors are usable today; the hosted Demo is a thin Cloudflare Worker plus a small Python service on our gateway VM. Expect rough edges.

## What it does

1. Fetches a public website (home + a few key pages), respecting `robots.txt`.
2. Scores it against a public, reproducible [5-dimension rubric](docs/rubric.md).
3. Optionally asks an LLM to write **up to 3 recommendations**, each citing an evidence URL from the pages it actually read. A QA step drops unsupported claims.
4. Renders a bilingual HTML report.

**SSRF defence** is first-class: only `http`/`https` on ports 80/443, no credentials, DNS resolution must be fully public, and the TCP connection is pinned to the vetted IP (blocks DNS rebinding). See `checkup_engine/ssrf.py`.

## Quick start (CLI)

```bash
python3 -m checkup_engine https://example.com --lang en --offline --out report.html
# With a LiteLLM / OpenAI-compatible gateway:
#   export GATEWAY_CHECKUP_KEY=...
#   export GATEWAY_CHECKUP_BASE_URL=https://llm.agentbay.asia/v1
#   export GATEWAY_CHECKUP_MODEL=deepseek-v4
python3 -m checkup_engine https://example.com --lang zh --out report.html --json report.json
```

Python 3.10+, **stdlib only** — nothing to `pip install` to run the engine or the VM service.


## Live Demo status (early stage)

| Piece | URL / note |
|---|---|
| Engine health | https://llm.agentbay.asia/checkup/health |
| Worker API (preview) | https://talentos-checkup-demo.jimmywangjimmy.workers.dev |
| Site Demo pages | `/demo/` and `/en/demo/` on www.agentbay.asia — **not published to gh-pages until Reed confirms** |
| Turnstile | Preview still uses Cloudflare **test keys** (always pass). Real site+secret keys: wait for `/workspace/secrets/turnstile-checkup.env` from Relay, then wire Site Key into the Astro demo pages and Secret into the Worker. |

Honest limits: site-wide **12 runs/day**, **3 per IP/day**, gateway budget **$1/day** (resets 08:00 Beijing). Expect rough edges; scores are reproducible, recommendations are estimates.

## Architecture (Demo)

```
Browser (/demo/)  →  Cloudflare Worker (Turnstile + KV rate limit + proxy)
                  →  Azure VM service (localhost:8790, behind Caddy /checkup/*)
                  →  LiteLLM gateway (deepseek-v4)
```

- Worker stays on the **Cloudflare free plan** (CPU ≪ 10 ms, ≤ a few subrequests).
- Site-wide Demo cap: **12 runs/day**; per-IP: **3/day**. Budget resets 08:00 Beijing time.
- Visitor-facing errors are bilingual and never include raw gateway text.

VM install steps: [`service/DEPLOY.md`](service/DEPLOY.md).

## Monitoring daily report

```bash
python3 scripts/daily_sample.py --site https://www.agentbay.asia/
# writes samples/YYYY-MM-DD/{snapshot.json,daily.md,daily.html}
```

Suggested cron (Beijing time, off-peak for the model):

```cron
# 07:30 Asia/Shanghai — tell Reed; do not create the routine yourself
30 7 * * * cd /opt/checkup-engine && set -a && . /etc/checkup-engine/env && set +a && python3 scripts/daily_sample.py
```

## Tests

```bash
python3 -m unittest discover -s tests -v
node --test worker/test/*.test.mjs
```

## License

MIT © 2026 TalentOS

---

Maintained by [TalentOS](https://www.agentbay.asia) · 需要定制 Agent / 技能开发？[找我们定制 / Work with us](https://www.agentbay.asia/contact) · talentos@agentbay.asia
