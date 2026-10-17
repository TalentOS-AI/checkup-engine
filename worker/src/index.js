/**
 * Thin Cloudflare Worker for the TalentOS checkup demo (free plan).
 * Duties only: Turnstile, KV rate limits (3/IP/day, 12/day global), auth, proxy/poll.
 * Crawling / LLM live on the Azure VM. Stay well under 10 ms CPU and 50 subrequests.
 */

const ALLOWED_ORIGINS = new Set([
  "https://www.agentbay.asia",
  "https://agentbay.asia",
  "http://localhost:4321",
  "http://127.0.0.1:4321",
]);

const FRIENDLY = {
  blocked: {
    zh: "仅支持公网 http/https 网址，内网与私有地址会被拒绝。",
    en: "Only public http/https URLs are allowed. Private and reserved addresses are rejected.",
  },
  rate_ip: {
    zh: "同一 IP 每天最多 3 次体检，请明天再来。",
    en: "Each IP can run 3 checkups per day. Please come back tomorrow.",
  },
  rate_global: {
    zh: "今日公开 Demo 名额已满（全站 12 次/天），请明天再来。",
    en: "The public Demo is full for today (12 runs site-wide). Please come back tomorrow.",
  },
  turnstile: {
    zh: "人机验证失败，请刷新页面重试。",
    en: "Human verification failed. Please refresh and try again.",
  },
  backend: {
    zh: "后端服务暂不可用，请稍后再试。",
    en: "The backend is temporarily unavailable. Please try again shortly.",
  },
  invalid: {
    zh: "请输入一个有效的公网网址（例如 https://example.com）。",
    en: "Please enter a valid public URL (for example https://example.com).",
  },
  generic: {
    zh: "体检未能完成，请稍后再试。",
    en: "The checkup could not be completed. Please try again later.",
  },
};

function beijingDay(now = Date.now()) {
  // Budget / counters reset at 08:00 Beijing = 00:00 UTC.
  return new Date(now).toISOString().slice(0, 10);
}

function corsHeaders(origin) {
  const o = ALLOWED_ORIGINS.has(origin) ? origin : "https://www.agentbay.asia";
  return {
    "Access-Control-Allow-Origin": o,
    "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type",
    "Access-Control-Max-Age": "86400",
    Vary: "Origin",
  };
}

function json(status, body, origin) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json; charset=utf-8", "Cache-Control": "no-store", ...corsHeaders(origin) },
  });
}

function err(status, code, lang, origin) {
  const f = FRIENDLY[code] || FRIENDLY.generic;
  return json(status, { error: { code, message: f[lang === "en" ? "en" : "zh"], message_zh: f.zh, message_en: f.en } }, origin);
}

/** Cheap URL shape check. Full SSRF is enforced on the VM. */
function cheapValidate(raw) {
  if (typeof raw !== "string" || raw.length < 4 || raw.length > 2048) return null;
  let u;
  try {
    u = new URL(raw.includes("://") ? raw.trim() : `https://${raw.trim()}`);
  } catch {
    return null;
  }
  if (u.protocol !== "http:" && u.protocol !== "https:") return null;
  if (u.username || u.password) return null;
  if (u.port && u.port !== "80" && u.port !== "443") return null;
  const host = u.hostname.toLowerCase();
  if (!host.includes(".") || host.endsWith(".local") || host.endsWith(".internal") || host === "localhost") return null;
  if (/^(10\.|127\.|0\.|169\.254\.|192\.168\.|172\.(1[6-9]|2\d|3[01])\.)/.test(host)) return null;
  if (host.includes(":")) return null; // reject literal IPv6 in the Worker; VM does the real check
  return u.toString();
}

async function verifyTurnstile(token, ip, env) {
  const secret = env.TURNSTILE_SECRET;
  if (!secret) return false;
  const body = new URLSearchParams({ secret, response: token || "", remoteip: ip || "" });
  const r = await fetch("https://challenges.cloudflare.com/turnstile/v0/siteverify", { method: "POST", body });
  if (!r.ok) return false;
  const data = await r.json();
  return !!data.success;
}

async function rateLimit(env, ip, { dryRun } = { dryRun: false }) {
  const day = beijingDay();
  const ipKey = `ip:${day}:${ip || "unknown"}`;
  const gKey = `g:${day}`;
  const ipLimit = Number(env.DAILY_IP_LIMIT || 3);
  const gLimit = Number(env.DAILY_GLOBAL_LIMIT || 12);
  const ipCount = Number((await env.CHECKUP_KV.get(ipKey)) || 0);
  if (ipCount >= ipLimit) return "rate_ip";
  const gCount = Number((await env.CHECKUP_KV.get(gKey)) || 0);
  if (gCount >= gLimit) return "rate_global";
  if (dryRun) return null;
  const ttl = 60 * 60 * 36;
  await env.CHECKUP_KV.put(ipKey, String(ipCount + 1), { expirationTtl: ttl });
  await env.CHECKUP_KV.put(gKey, String(gCount + 1), { expirationTtl: ttl });
  return null;
}

async function createJob(env, url, lang) {
  const backend = (env.CHECKUP_BACKEND || "").replace(/\/$/, "");
  if (!backend || !env.CHECKUP_SERVICE_TOKEN) {
    return { status: 503, body: null };
  }
  const r = await fetch(`${backend}/jobs`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${env.CHECKUP_SERVICE_TOKEN}`,
    },
    body: JSON.stringify({ url, lang }),
  });
  const text = await r.text();
  let data;
  try {
    data = JSON.parse(text);
  } catch {
    data = null;
  }
  return { status: r.status, body: data };
}

async function proxyGet(env, pathWithQuery) {
  const backend = (env.CHECKUP_BACKEND || "").replace(/\/$/, "");
  if (!backend || !env.CHECKUP_SERVICE_TOKEN) return null;
  return fetch(`${backend}${pathWithQuery}`, {
    headers: { Authorization: `Bearer ${env.CHECKUP_SERVICE_TOKEN}` },
  });
}

export default {
  async fetch(request, env) {
    const origin = request.headers.get("Origin") || "";
    if (request.method === "OPTIONS") {
      return new Response(null, { status: 204, headers: corsHeaders(origin) });
    }
    const u = new URL(request.url);

    if (u.pathname === "/health") {
      return json(200, { ok: true, service: "talentos-checkup-demo" }, origin);
    }

    if (request.method === "POST" && u.pathname === "/api/checkup") {
      let body;
      try {
        body = await request.json();
      } catch {
        return err(400, "invalid", "zh", origin);
      }
      const lang = body.lang === "en" ? "en" : "zh";
      const url = cheapValidate(body.url);
      if (!url) return err(400, "invalid", lang, origin);
      // Turnstile (1 subrequest)
      const okTs = await verifyTurnstile(body.turnstileToken, request.headers.get("CF-Connecting-IP"), env);
      if (!okTs) return err(403, "turnstile", lang, origin);
      // Soft check first (no write). Only consume quota after the VM accepts the job,
      // so SSRF rejects and backend errors do not burn the visitor's daily slots.
      const limited = await rateLimit(env, request.headers.get("CF-Connecting-IP"), { dryRun: true });
      if (limited) return err(429, limited, lang, origin);
      const res = await createJob(env, url, lang);
      if (res.status === 503 || !res.body) return err(503, "backend", lang, origin);
      if (res.status >= 400) {
        if (res.body && res.body.error && res.body.error.message) {
          return json(res.status, { error: res.body.error }, origin);
        }
        return err(res.status === 400 ? 400 : 502, res.status === 400 ? "blocked" : "backend", lang, origin);
      }
      await rateLimit(env, request.headers.get("CF-Connecting-IP"), { dryRun: false });
      return json(202, {
        jobId: res.body.jobId,
        token: res.body.token,
        exp: res.body.exp,
        pollUrl: `/api/checkup/${res.body.jobId}?t=${encodeURIComponent(res.body.token)}&exp=${res.body.exp}`,
      }, origin);
    }

    const m = u.pathname.match(/^\/api\/checkup\/([a-f0-9]+)\/?$/);
    if (request.method === "GET" && m) {
      const jobId = m[1];
      const t = u.searchParams.get("t") || "";
      const exp = u.searchParams.get("exp") || "";
      const upstream = await proxyGet(env, `/jobs/${jobId}?t=${encodeURIComponent(t)}&exp=${encodeURIComponent(exp)}`);
      if (!upstream) return err(503, "backend", "zh", origin);
      const text = await upstream.text();
      return new Response(text, {
        status: upstream.status,
        headers: { "Content-Type": "application/json; charset=utf-8", "Cache-Control": "no-store", ...corsHeaders(origin) },
      });
    }

    const r = u.pathname.match(/^\/api\/report\/([a-f0-9]+)\/?$/);
    if (request.method === "GET" && r) {
      const jobId = r[1];
      const t = u.searchParams.get("t") || "";
      const exp = u.searchParams.get("exp") || "";
      const upstream = await proxyGet(env, `/report/${jobId}?t=${encodeURIComponent(t)}&exp=${encodeURIComponent(exp)}`);
      if (!upstream) return err(503, "backend", "zh", origin);
      return new Response(upstream.body, {
        status: upstream.status,
        headers: {
          "Content-Type": upstream.headers.get("Content-Type") || "text/html; charset=utf-8",
          "Cache-Control": "no-store",
          ...corsHeaders(origin),
        },
      });
    }

    return err(404, "generic", "zh", origin);
  },
};
