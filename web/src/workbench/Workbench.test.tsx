import { afterEach, expect, it, vi } from "vitest";
import { cleanup, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import Workbench from "./Workbench";

// Contract doubles only: no provider or inference is exercised by these fixtures.
const project = { id: "project-one", name: "Interview", revision: 3, status: "created", source_language: "en", target_languages: ["zh"], source_asset_id: null, source_track_index: 0 };
const ok = (value: unknown, status = 200) => new Response(JSON.stringify(value), {status, headers: {"Content-Type": "application/json"}});
afterEach(() => { cleanup(); vi.restoreAllMocks(); window.history.replaceState(null, "", "/"); });
it("lists real project responses and opens a reloadable project link", async () => {
  const user = userEvent.setup();
  vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
    const path = String(input);
    if (path === "/api/projects?limit=50&offset=0") return ok({items: [project], total: 1});
    if (path === "/api/projects/project-one") return ok(project);
    if (path.includes("/timeline")) return ok({segments: [], total: 0, cast: [], source: null, transcript: null, editor_fingerprint: "head"});
    if (path.includes("/runs")) return ok({items: [], total: 0});
    if (path.includes("/events")) return ok({items: [], total: 0, next_cursor: 0});
    throw new Error(path);
  });
  render(<Workbench csrf="csrf" />);
  await user.click(await screen.findByRole("link", {name: "Interview"}));
  await waitFor(() => expect(window.location.hash).toBe("#/projects/project-one"));
  expect(await screen.findByRole("heading", {name: "Interview"})).toBeTruthy();
});
it("creates with source and target language choices, then opens the returned project", async () => {
  const user = userEvent.setup();
  const writes: unknown[] = [];
  vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
    const path = String(input);
    if (path.startsWith("/api/languages")) return ok({items: [{code: "auto", name: "自动检测", variants: []}, {code: "en", name: "English", variants: []}, {code: "zh", name: "中文", variants: ["zh-Hans"]}]});
    if (path === "/api/projects" && init?.method === "POST") { writes.push(JSON.parse(String(init.body))); return ok({...project, name: "New film"}, 201); }
    if (path.startsWith("/api/projects?")) return ok({items: [], total: 0});
    if (path === "/api/projects/project-one") return ok({...project, name: "New film"});
    if (path.includes("/timeline")) return ok({segments: [], total: 0, cast: [], source: null, transcript: null, editor_fingerprint: "head"});
    return ok({items: [], total: 0, next_cursor: 0});
  });
  render(<Workbench csrf="csrf" />);
  await user.click(await screen.findByRole("button", {name: "新建项目"}));
  await user.type(screen.getByLabelText("项目名称"), "New film");
  await user.click(screen.getByText("选择源语言"));
  await user.click(await within(screen.getByText("选择源语言").parentElement!).findByRole("button", {name: "English · en"}));
  await user.click(screen.getByText("添加目标语言"));
  await user.click(await within(screen.getByText("添加目标语言").parentElement!).findByRole("button", {name: "中文 · zh-Hans"}));
  await user.click(screen.getByRole("button", {name: "创建项目"}));
  await waitFor(() => expect(writes).toEqual([{name: "New film", source_language: "en", target_languages: ["zh-Hans"]}]));
  expect(await screen.findByRole("heading", {name: "New film"})).toBeTruthy();
});
