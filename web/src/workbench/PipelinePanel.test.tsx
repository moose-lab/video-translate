import {afterEach, expect, it, vi} from "vitest";
import {cleanup, render, screen, waitFor} from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import PipelinePanel from "./PipelinePanel";
import type {Timeline} from "./types";
// Contract doubles only: these states are synthetic controller projections, never provider evidence.
const timeline = {editor_fingerprint: "editor-a", source: {id: "selection", stale: false}, transcript: {id: "transcript", stale: false, provenance: "import"}} as Timeline;
const tracks = [{id: "track-zh", tag: "zh", archived: false}, {id: "track-ja", tag: "ja", archived: false}];
const flow = {id: "flow-a", revision: 3, generation: 1, policy_revision: 1, scope_revision: 1, status: "review", stage: "targets", next_action: "review_targets", source_mode: "use_current", source_guard: "source-a", auto_advance: false, purpose: "dub", target_track_ids: ["track-zh"], delivery_track_ids: ["track-zh"], delivery_options: {}, dirty: false, stop_requested: false, event_cursor: 8, targets: [{track_id: "track-zh", tag: "zh", guard: "target-a", status: "review", next_action: "translation_review"}], finish: {}, unresolved_remote: [], commands_total: 0, commands: [], checkpoints: [{id: "check", scope: "source", guard: "source-a", provenance: "automatic_policy", policy_revision: 1}]};
const props = {projectId: "p", csrf: "csrf", timeline, refreshVersion: 0};
const ok = (value: unknown, status = 200) => new Response(JSON.stringify(value), {status});
afterEach(() => {cleanup(); vi.restoreAllMocks(); window.history.replaceState(null, "", "/");});
it("cold loads the saved workflow deep link and exposes actual checkpoints without dispatch", async () => {
  window.history.replaceState(null, "", "/#/projects/p?pipeline=flow-a");
  const fetch = vi.spyOn(globalThis, "fetch").mockImplementation(async input => ok(String(input).includes("language-tracks?") ? {items: tracks, total: 2} : String(input).includes("offset=") ? {items: [flow], total: 1} : flow));
  render(<PipelinePanel {...props} />);
  expect(await screen.findByText(/流程代次 1/)).toBeTruthy();
  expect(screen.getByText(/策略自动放行/)).toBeTruthy();
  expect(screen.getByRole("button", {name: /核对中文译文并继续/})).toBeTruthy();
  expect(fetch.mock.calls.every(([, init]) => !init?.method)).toBe(true);
});
it("pins explicit continuation to returned revision, opaque guard and track despite live refresh", async () => {
  const user = userEvent.setup(); let current = flow; const writes: unknown[] = [];
  vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
    if (init?.method) {writes.push(JSON.parse(String(init.body))); return ok({error: {code: "REVISION_CONFLICT"}}, 409);}
    return ok(String(input).includes("language-tracks?") ? {items: tracks, total: 2} : String(input).includes("offset=") ? {items: [flow], total: 1} : current);
  });
  const view = render(<PipelinePanel {...props} />);
  await user.click(await screen.findByRole("button", {name: /核对中文译文并继续/}));
  expect(writes).toHaveLength(0);
  current = {...flow, revision: 9, targets: [{...flow.targets[0], guard: "target-b"}]};
  view.rerender(<PipelinePanel {...props} refreshVersion={1} />);
  await user.click(screen.getByRole("button", {name: "确认此次流程操作"}));
  await waitFor(() => expect(writes[0]).toEqual({revision: 3, kind: "translation", guard: "target-a", track_id: "track-zh"}));
  expect(await screen.findByText(/REVISION_CONFLICT/)).toBeTruthy();
  expect(screen.getByRole("button", {name: "放弃此次操作"})).toBeTruthy();
});
it("starts only after explicit selection with pinned editor and no default automatic acceptance", async () => {
  const user = userEvent.setup(); const writes: unknown[] = [];
  vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
    if (init?.method) {writes.push(JSON.parse(String(init.body))); return ok(flow, 202);}
    return ok(String(input).includes("language-tracks?") ? {items: tracks, total: 2} : String(input).endsWith("/current") ? null : String(input).includes("offset=") ? {items: [], total: 0} : flow);
  });
  const view = render(<PipelinePanel {...props} />);
  await user.click(screen.getByRole("button", {name: "设置新流程"}));
  await user.click(await screen.findByLabelText("流程包含中文")); await user.click(screen.getByLabelText("共同导出包含中文"));
  view.rerender(<PipelinePanel {...props} timeline={{...timeline, editor_fingerprint: "editor-b"}} refreshVersion={1} />);
  expect(writes).toHaveLength(0);
  await user.click(screen.getByRole("button", {name: "启动所选流程"}));
  await waitFor(() => expect(writes[0]).toMatchObject({expected_editor_fingerprint: "editor-a", source_mode: "use_current", target_track_ids: ["track-zh"], delivery_track_ids: ["track-zh"], auto_advance: false}));
  expect(window.location.hash).toContain("pipeline=flow-a");
});
it("reads every bounded track page before allowing scope, and makes unknown remote work explicit", async () => {
  const user = userEvent.setup();
  const fetch = vi.spyOn(globalThis, "fetch").mockImplementation(async input => {
    const path = String(input);
    if (path.includes("language-tracks?")) return ok(path.includes("offset=100") ? {items: [tracks[1]], total: 101} : {items: [tracks[0]], total: 101});
    return ok(path.includes("offset=") ? {items: [flow], total: 1} : {...flow, unresolved_remote: [{run_id: "run-a", status: "needs_review", submission_uncertain: true, exclusively_owned: false}]});
  });
  render(<PipelinePanel {...props} />);
  expect(await screen.findByText(/远程提交结果未知/)).toBeTruthy();
  await user.click(screen.getByRole("button", {name: "调整流程语言范围"}));
  expect(await screen.findByLabelText("流程包含日语")).toBeTruthy();
  expect(fetch.mock.calls.some(([path]) => String(path).includes("language-tracks?limit=100&offset=100"))).toBe(true);
  expect(fetch.mock.calls.every(([, init]) => !init?.method)).toBe(true);
});
it("sends policy, scope, stop and resume only as explicitly confirmed versioned commands", async () => {
  const user = userEvent.setup(); let current = flow; const writes: {path: string; body: unknown}[] = [];
  vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
    const path = String(input);
    if (init?.method) {const body = JSON.parse(String(init.body)); writes.push({path, body}); current = {...current, revision: current.revision + 1, auto_advance: path.endsWith("/policy") ? body.auto_advance : current.auto_advance, stop_requested: path.endsWith("/cancel") ? true : path.endsWith("/resume") ? false : current.stop_requested}; return ok(current, 202);}
    return ok(path.includes("language-tracks?") ? {items: tracks, total: 2} : path.includes("offset=") ? {items: [flow], total: 1} : current);
  });
  render(<PipelinePanel {...props} />);
  await user.click(await screen.findByRole("button", {name: "设置自动推进"})); expect(writes).toHaveLength(0);
  await user.click(screen.getByRole("button", {name: "确认此次流程操作"}));
  await screen.findByRole("button", {name: "关闭自动推进"});
  await user.click(screen.getByRole("button", {name: "调整流程语言范围"})); await user.click(screen.getByLabelText("流程包含日语"));
  await user.click(screen.getByRole("button", {name: "核对语言范围变更"})); await user.click(screen.getByRole("button", {name: "确认此次流程操作"}));
  await waitFor(() => expect(writes).toHaveLength(2));
  await user.click(screen.getByRole("button", {name: "停止流程"})); await user.click(screen.getByRole("button", {name: "确认此次流程操作"}));
  await user.click(await screen.findByRole("button", {name: "恢复流程"})); await user.click(screen.getByRole("button", {name: "确认此次流程操作"}));
  await waitFor(() => expect(writes).toHaveLength(4));
  expect(writes.map(write => write.body)).toEqual([{revision: 3, auto_advance: true}, {revision: 4, target_track_ids: ["track-zh", "track-ja"], delivery_track_ids: ["track-zh"]}, {revision: 5}, {revision: 6}]);
  expect(writes.map(write => write.path.split("/").at(-1))).toEqual(["policy", "scope", "cancel", "resume"]);
});
it("ignores and aborts old detail reads when the selected workflow changes", async () => {
  const {fireEvent} = await import("@testing-library/react");
  let finish!: (value: Response) => void; let oldSignal: AbortSignal | undefined;
  vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
    const path = String(input);
    if (path.endsWith("/current")) {oldSignal = init?.signal as AbortSignal; return new Promise<Response>(resolve => {finish = resolve;});}
    return ok(path.includes("language-tracks?") ? {items: tracks, total: 2} : path.includes("offset=") ? {items: [flow], total: 1} : {...flow, generation: 4});
  });
  render(<PipelinePanel {...props} />);
  await waitFor(() => expect(finish).toBeTruthy());
  window.history.replaceState(null, "", "/#/projects/p?pipeline=flow-a"); fireEvent(window, new HashChangeEvent("hashchange"));
  expect(await screen.findByText(/流程代次 4/)).toBeTruthy(); expect(oldSignal?.aborted).toBe(true);
  finish(ok({...flow, generation: 1}));
  await waitFor(() => expect(screen.queryByText(/流程代次 1/)).toBeNull());
});
