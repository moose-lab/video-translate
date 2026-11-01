import {afterEach, expect, it, vi} from "vitest";
import {api, ApiError} from "./client";
afterEach(() => vi.restoreAllMocks());
it("lets the browser add multipart boundaries while retaining same-origin cookies and CSRF", async () => {
  const fetch = vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response("{}"));
  const form = new FormData(); form.append("file", new File(["video"], "fresh.mp4", {type: "video/mp4"}));
  await api("/projects/p/source", {method: "POST", body: form}, "csrf");
  const init = fetch.mock.calls[0][1]!;
  expect(new Headers(init.headers).has("Content-Type")).toBe(false);
  expect(new Headers(init.headers).get("X-CSRF-Token")).toBe("csrf");
  expect(init.credentials).toBe("same-origin");
  expect(init.body).toBe(form);
});
it("adds JSON content type to JSON string bodies", async () => {
  const fetch = vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response("{}"));
  await api("/projects", {method: "POST", body: JSON.stringify({name: "Film"})}, "csrf");
  expect(new Headers(fetch.mock.calls[0][1]?.headers).get("Content-Type")).toBe("application/json");
});
it("preserves bounded structured error facts without exposing server values or provider payloads", async () => {
  vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response(JSON.stringify({error: {code: "VALIDATION_ERROR", message: "hf_secret provider dump", retryable: true, details: [{field: "body.name", code: "string_too_short", input: "hf_secret"}, {field: "hf_secret/unsafe", code: "bad"}]}}), {status: 422}));
  const error = await api<never>("/projects").catch(e => e as ApiError);
  expect(error).toBeInstanceOf(ApiError);
  expect(error.code).toBe("VALIDATION_ERROR"); expect(error.retryable).toBe(true);
  expect(error.details).toEqual([{field: "body.name", code: "string_too_short"}]);
  expect(error.message).not.toContain("hf_secret"); expect(JSON.stringify(error)).not.toContain("hf_secret");
});
it("dispatches session expiry once for a rejected authenticated request", async () => {
  const expired = vi.fn(); window.addEventListener("session-expired", expired);
  vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response("{}", {status: 401}));
  await expect(api("/projects")).rejects.toMatchObject({status: 401});
  expect(expired).toHaveBeenCalledOnce(); window.removeEventListener("session-expired", expired);
});
