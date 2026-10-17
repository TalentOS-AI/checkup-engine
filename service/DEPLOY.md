# Deploy checkup-engine on the Azure gateway VM

**Coordinate with Reed / Relay before touching the VM.** This document is the
install checklist. The service listens on `127.0.0.1:8790` only. DNS is not
changed. The Cloudflare Worker stays on the free plan and only proxies.

## What already exists on the VM

- Ubuntu 24.04, Python 3 (stdlib only — **nothing to `pip install`**)
- Caddy terminating TLS for `llm.agentbay.asia`
- LiteLLM / imagegen already bound to localhost

## Install (additive)

```bash
# 1. user + dirs
sudo useradd --system --home /var/lib/checkup-engine --shell /usr/sbin/nologin checkup || true
sudo mkdir -p /opt/checkup-engine /var/lib/checkup-engine /etc/checkup-engine
sudo rsync -a --delete ./ /opt/checkup-engine/   # from a release tarball / git clone
sudo chown -R checkup:checkup /var/lib/checkup-engine
sudo chown -R root:checkup /opt/checkup-engine
sudo chmod -R a+rX /opt/checkup-engine

# 2. secrets (chmod 600, never in git)
sudo install -m 600 /dev/null /etc/checkup-engine/env
sudo nano /etc/checkup-engine/env   # fill from service/env.example
# GATEWAY_CHECKUP_* must match the checkup-demo key; CHECKUP_SERVICE_TOKEN is
# a new shared secret also set as a Cloudflare Worker secret.

# 3. systemd
sudo cp /opt/checkup-engine/service/checkup-engine.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now checkup-engine
curl -s http://127.0.0.1:8790/health

# 4. Caddy — ADDITIVE route only (see Caddyfile.snippet). Example:
#    handle_path /checkup/* { reverse_proxy 127.0.0.1:8790 }
# Ask Reed/Relay to paste the snippet into the existing site block and reload
# Caddy. Do not rewrite other handlers. Do not touch DNS.
sudo caddy validate --config /etc/caddy/Caddyfile
sudo systemctl reload caddy
curl -s https://llm.agentbay.asia/checkup/health
```

## Worker wiring

Set Worker secrets (wrangler):

- `CHECKUP_SERVICE_TOKEN` — same value as on the VM
- `TURNSTILE_SECRET` — real secret later; test key for preview
- `CHECKUP_BACKEND` — `https://llm.agentbay.asia/checkup`

Vars (plain): `TURNSTILE_SITEKEY`, `DAILY_GLOBAL_LIMIT=12`, `DAILY_IP_LIMIT=3`.

## Port conflict check

Before enabling, ask Relay: is `8790` free? (On some sandboxes 8790 is reserved by an egress tunnel — pick another localhost port there.) If not, pick another localhost port
and update both the unit and the Caddy snippet.

## Rollback

```bash
sudo systemctl disable --now checkup-engine
# remove the handle_path /checkup/* block from Caddy and reload
```
