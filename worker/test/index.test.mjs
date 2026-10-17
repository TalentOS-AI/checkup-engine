import { describe, it } from "node:test";
import assert from "node:assert/strict";
import worker from "../src/index.js";

function fakeKv() {
  const store = new Map();
  return {
    async get(k) { return store.has(k) ? store.get(k) : null; },
    async put(k, v) { store.set(k, v); },
  };
}

function env(overrides = {}) {
  return {
    CHECKUP_KV: fakeKv(),
    TURNSTILE_SECRET: "1x0000000000000000000000000000000AA",
    DAILY_IP_LIMIT: "3",
    DAILY_GLOBAL_LIMIT: "12",
    CHECKUP_SERVICE_TOKEN: "test-token",
    CHECKUP_BACKEND: "",
    ...overrides,
  };
}

function post(url, ip = "1.2.3.4") {
  return new Request("https://x/api/checkup", {
    method: "POST",
    headers: { "Content-Type": "application/json", "CF-Connecting-IP": ip, Origin: "https://www.agentbay.asia" },
    body: JSON.stringify({ url, turnstileToken: "x", lang: "zh" }),
  });
}

describe("checkup worker", () => {
  it("health", async () => {
    assert.equal((await worker.fetch(new Request("https://x/health"), env())).status, 200);
  });

  it("rejects loopback without backend call", async () => {
    const r = await worker.fetch(post("http://127.0.0.1/"), env());
    assert.equal(r.status, 400);
    assert.equal((await r.json()).error.code, "invalid");
  });

  it("503 when backend unset; does not burn quota", async () => {
    const original = globalThis.fetch;
    globalThis.fetch = async (url) => {
      if (String(url).includes("siteverify")) return new Response(JSON.stringify({ success: true }));
      throw new Error("no backend");
    };
    const e = env();
    try {
      for (let i = 0; i < 5; i++) {
        const r = await worker.fetch(post("https://example.com"), e);
        assert.equal(r.status, 503);
      }
    } finally { globalThis.fetch = original; }
  });

  it("enforces per-IP limit of 3 after accepted jobs", async () => {
    const original = globalThis.fetch;
    let n = 0;
    globalThis.fetch = async (url) => {
      if (String(url).includes("siteverify")) return new Response(JSON.stringify({ success: true }));
      n += 1;
      return new Response(JSON.stringify({ jobId: "abc" + n, token: "t", exp: 9e12 }), { status: 202 });
    };
    const e = env({ CHECKUP_BACKEND: "https://backend.example/checkup" });
    try {
      for (let i = 0; i < 3; i++) {
        assert.equal((await worker.fetch(post("https://example.com"), e)).status, 202);
      }
      const r = await worker.fetch(post("https://example.com"), e);
      assert.equal(r.status, 429);
      assert.equal((await r.json()).error.code, "rate_ip");
    } finally { globalThis.fetch = original; }
  });

  it("enforces global limit of 12", async () => {
    const original = globalThis.fetch;
    globalThis.fetch = async (url) => {
      if (String(url).includes("siteverify")) return new Response(JSON.stringify({ success: true }));
      return new Response(JSON.stringify({ jobId: "x", token: "t", exp: 9e12 }), { status: 202 });
    };
    const e = env({ CHECKUP_BACKEND: "https://backend.example/checkup", DAILY_GLOBAL_LIMIT: "2", DAILY_IP_LIMIT: "99" });
    try {
      assert.equal((await worker.fetch(post("https://example.com", "1.1.1.1"), e)).status, 202);
      assert.equal((await worker.fetch(post("https://example.com", "1.1.1.2"), e)).status, 202);
      const r = await worker.fetch(post("https://example.com", "1.1.1.3"), e);
      assert.equal(r.status, 429);
      assert.equal((await r.json()).error.code, "rate_global");
    } finally { globalThis.fetch = original; }
  });
});
