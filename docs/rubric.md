# Checkup rubric (v0.1)

Five dimensions, each scored 0–100 as a weighted pass rate of its checks. The overall score is the mean of the five. Scores are **deterministic** — the same collected pages always produce the same numbers. The LLM only writes recommendations and may be skipped (`--offline`).

| Dimension | What it measures |
|---|---|
| Discoverability | Title, meta description, H1, lang, canonical, sitemap, robots, Open Graph, viewport, HTTPS |
| Freshness | Copyright year, dated content ≤ 90 days, sitemap lastmod, blog/news |
| Touchpoints | Contact page, email, phone, form, chat, booking, ≥2 social, analytics |
| AI readiness | JSON-LD, Organization schema, llms.txt, AI crawler policy, alt text ≥80%, server-rendered text, FAQ |
| Automation | Pricing, products/services, case studies, form capture, multilingual |

Every failed check carries bilingual fix text. Recommendations must cite an evidence URL that was actually collected; a QA step drops inventions.
