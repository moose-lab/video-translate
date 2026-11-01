import { afterEach, expect, it, vi } from "vitest";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import App from "../App";
const identity = {csrf_token: "csrf", user: {name: "Editor"}, workspace: {name: "Studio"}};
const ok = (data: unknown, status = 200) => new Response(JSON.stringify(data), {status});
afterEach(() => {cleanup(); vi.restoreAllMocks(); window.history.replaceState(null, "", "/");});
it("opens Projects after login and keeps Services and logout reachable", async () => {
  vi.spyOn(globalThis, "fetch").mockImplementation(async input => String(input).endsWith("/auth/me") ? ok(identity) : String(input).includes("/projects?") ? ok({items: [], total: 0}) : ok({credentials: {huggingface: {configured: false, revision: 0}, translation: {configured: false, revision: 0}}, providers: {}}));
  render(<App />);
  expect(await screen.findByRole("heading", {name: "项目"})).toBeTruthy();
  await userEvent.click(screen.getByRole("link", {name: "服务配置"}));
  expect(await screen.findByRole("heading", {name: "配置云端服务"})).toBeTruthy();
  await userEvent.click(screen.getByRole("link", {name: "项目"}));
  expect(await screen.findByRole("heading", {name: "项目"})).toBeTruthy();
  await userEvent.click(screen.getByRole("button", {name: "退出登录"}));
  expect(await screen.findByRole("button", {name: "登录"})).toBeTruthy();
  expect(window.location.hash).toBe("#/projects");
});
it("does not let a late initial identity response restore an expired session", async () => {
  let resolve!: (value: Response) => void;
  vi.spyOn(globalThis, "fetch").mockImplementation(() => new Promise<Response>(done => {resolve = done;}));
  render(<App />);
  window.dispatchEvent(new Event("session-expired"));
  resolve(ok(identity));
  await waitFor(() => expect(screen.queryByRole("heading", {name: "项目"})).toBeNull());
  expect(await screen.findByRole("button", {name: "登录"})).toBeTruthy();
});
