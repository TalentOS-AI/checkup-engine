# Turnstile wiring (TODO until Relay delivers keys)

Expected file on the box (chmod 600, never commit):

```
/workspace/secrets/turnstile-checkup.env
TURNSTILE_SITEKEY=...
TURNSTILE_SECRET=...
```

Then:

1. `wrangler secret put TURNSTILE_SECRET` on `talentos-checkup-demo` (value from that file).
2. Set `PUBLIC_TURNSTILE_SITEKEY` (or edit `src/config/demo.js`) and rebuild `talentos-site`.
3. Redeploy Worker; remove the “using Turnstile test keys” banner (`USING_TURNSTILE_TEST_KEYS`).
4. Retest `/demo/` once with a real browser challenge.

Preview today uses sitekey `1x00000000000000000000AA` / secret `1x0000000000000000000000000000000AA` (always pass).
