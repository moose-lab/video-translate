import {afterEach, expect, it, vi} from "vitest";
import {cleanup, fireEvent, render, screen, waitFor, within} from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import Workbench from "./Workbench";
// Contract doubles: source facts and transcript are fabricated for UI verification, never inference evidence.
const project = {id: "p", name: "Source film", revision: 7, status: "uploaded", source_language: "en", target_languages: ["zh", "ja"], source_asset_id: "asset", source_track_index: 0};
const probe = {id: "probe", stage: "probe", status: "succeeded", is_stale: false, attempt_count: 1, result: {duration_ms: 59510, video: {codec: "h264", width: 1920, height: 1080}, audio: [{audio_ordinal: 0, stream_index: 1, codec: "aac", language: "eng", channels: 2, sample_rate: 48000}]}};
const selection = {id: "selection", revision: 2, start_ms: 1000, end_ms: 20000, source_asset_id: "asset", stale: false, track: {...probe.result.audio[0], duration_ms: 59510, probe_run_id: "probe"}};
const timeline = {editor_fingerprint: "server-head", project_revision: 7, source: selection, transcript: {id: "transcript-head", stale: false, provenance: "provider"}, segments: Array.from({length: 8}, (_, i) => ({id: `s${i}`, revision: 1, start_ms: i * 1000, end_ms: (i + 1) * 1000, absolute_start_ms: 1000 + i * 1000, absolute_end_ms: 2000 + i * 1000, text: `Source line ${i + 1}`, speaker_id: "speaker", original_speaker_label: "SPEAKER_00"})), total: 8, cast: [{id: "speaker", name: "Role A", archived: false}], cast_total: 1};
const ok = (value: unknown, status = 200) => new Response(JSON.stringify(value), {status});
const settings = {credentials: {huggingface: {configured: true}}, providers: {separation: {adapter: "demucs_multistem"}, transcription: {adapter: "hf_asr"}}};
afterEach(() => {cleanup(); vi.restoreAllMocks(); window.history.replaceState(null, "", "/");});
function fixture(extra?: (path: string, init?: RequestInit) => Response | Promise<Response> | undefined) {
  return vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
    const path = String(input); const override = extra?.(path, init); if (override) return override;
    if (path === "/api/projects/p") return ok(project);
    if (path.includes("/timeline")) return ok(timeline);
    if (path.includes("/runs?")) return ok({items: [probe], total: 1});
    if (path.includes("/events?")) return ok({items: [], total: 0, next_cursor: 0});
    if (path === "/api/provider-settings") return ok(settings);
    throw new Error(path);
  });
}
function open() {window.history.replaceState(null, "", "/#/projects/p"); return render(<Workbench csrf="csrf" />);}
it("rehydrates selected source, actual eight source rows, cast and probe facts without starting inference", async () => {
  const fetch = fixture(); open();
  expect(await screen.findByText("Source line 8")).toBeTruthy();
  expect(screen.getAllByText("Role A").length).toBeGreaterThan(0);
  expect((screen.getByLabelText("开始时间（毫秒）") as HTMLInputElement).value).toBe("1000");
  expect((screen.getByLabelText("结束时间（毫秒）") as HTMLInputElement).value).toBe("20000");
  expect(screen.getByText(/59.510/)).toBeTruthy();
  expect(screen.getByLabelText("原片播放器").getAttribute("src")).toBe("/api/assets/asset/content");
  expect(fetch.mock.calls.filter(([, init]) => init?.method && init.method !== "GET")).toHaveLength(0);
  fireEvent.error(screen.getByLabelText("原片播放器"));
  expect(screen.getByText(/浏览器无法播放/)).toBeTruthy();
});
it("uploads exactly file, probes explicitly, validates selection with project revision, and analyses only on click", async () => {
  const user = userEvent.setup(); let uploaded = false, probed = false, selected = false;
  const writes: {path: string; init: RequestInit}[] = [];
  fixture((path, init) => {
    if (init?.method) writes.push({path, init});
    if (path === "/api/projects/p/source") {uploaded = true; return ok({project: {...project, revision: 8}, asset: {id: "asset"}}, 201);}
    if (path === "/api/projects/p/runs" && init?.method === "POST") {probed = true; return ok(probe, 201);}
    if (path === "/api/projects/p/source-selection") {selected = true; return ok(selection);}
    if (path === "/api/projects/p/workflow") return ok({id: "workflow", action: "analyse", status: "running", stage: "extract", next_action: null, run_ids: ["extract"], auto_advance: false}, 202);
    if (path === "/api/projects/p") return ok({...project, source_asset_id: uploaded ? "asset" : null, revision: uploaded ? 8 : 7});
    if (path.includes("/timeline")) return ok({...timeline, source: selected ? selection : null, transcript: null, segments: [], total: 0});
    if (path.includes("/runs?")) return ok({items: probed ? [probe] : [], total: probed ? 1 : 0});
  });
  open(); await screen.findByRole("heading", {name: "Source film"});
  const file = new File(["fresh"], "fresh.mp4", {type: "video/mp4"});
  await user.upload(screen.getByLabelText("选择原片文件"), file);
  await user.click(screen.getByRole("button", {name: "上传原片"}));
  await waitFor(() => expect(uploaded).toBe(true));
  const form = writes.find(write => write.path.endsWith("/source"))!.init.body as FormData;
  expect([...form.keys()]).toEqual(["file"]); expect(form.get("file")).toBe(file);
  await user.click(await screen.findByRole("button", {name: "读取媒体信息"}));
  await waitFor(() => expect(probed).toBe(true));
  const start = await screen.findByLabelText("开始时间（毫秒）"), end = screen.getByLabelText("结束时间（毫秒）");
  await user.clear(end); await user.type(end, "60000");
  expect((screen.getByRole("button", {name: "保存源片段"}) as HTMLButtonElement).disabled).toBe(true);
  await user.clear(start); await user.type(start, "0"); await user.clear(end); await user.type(end, "59510");
  await user.click(screen.getByRole("button", {name: "保存源片段"}));
  await waitFor(() => expect(selected).toBe(true));
  expect(JSON.parse(String(writes.find(write => write.path.endsWith("/source-selection"))!.init.body))).toEqual({revision: 8, source_asset_id: "asset", audio_ordinal: 0, start_ms: 0, end_ms: 59510});
  expect(writes.some(write => write.path.endsWith("/workflow"))).toBe(false);
  await user.click(await screen.findByRole("button", {name: "分析所选源片段"}));
  await waitFor(() => expect(writes.some(write => write.path.endsWith("/workflow"))).toBe(true));
  expect(JSON.parse(String(writes.find(write => write.path.endsWith("/workflow"))!.init.body))).toEqual({action: "analyse", expected_editor_fingerprint: "server-head", auto_advance: false});
  expect(await screen.findByText(/^源分析：/)).toBeTruthy();
});
it("requires an explicit uncertainty choice before resubmission and leaves cancellation truthful", async () => {
  const user = userEvent.setup(); const writes: {path: string; body: unknown}[] = [];
  fixture((path, init) => {
    if (path.includes("/runs?")) return ok({items: [{...probe, id: "uncertain", stage: "transcribe", status: "needs_review", remote_state: "submitting", remote_id: null, safe_error: {code: "SUBMISSION_UNCERTAIN", retryable: false}}, {...probe, id: "active", stage: "extract", status: "running"}], total: 2});
    if (path.endsWith("/retry") || path.endsWith("/cancel")) {writes.push({path, body: init?.body ? JSON.parse(String(init.body)) : null}); return ok({...probe, status: "cancelling"});}
  });
  open(); const jobs = await screen.findByRole("region", {name: "任务"});
  expect(writes).toEqual([]);
  await user.click(within(jobs).getByRole("button", {name: "重试"}));
  expect(writes).toEqual([]);
  expect((screen.getByRole("button", {name: "确认重试此任务"}) as HTMLButtonElement).disabled).toBe(true);
  await user.click(screen.getByLabelText(/我已核查远程任务/));
  await user.click(screen.getByRole("button", {name: "确认重试此任务"}));
  await waitFor(() => expect(writes[0]).toEqual({path: "/api/runs/uncertain/retry", body: {acknowledge_uncertain_submission: true}}));
  await user.click(within(jobs).getByRole("button", {name: "取消任务"}));
  await waitFor(() => expect(writes.some(write => write.path.endsWith("/cancel"))).toBe(true));
  expect(screen.getByText(/取消请求已提交/)).toBeTruthy();
});
it("ignores project requests that finish after navigation", async () => {
  let finish!: (value: Response) => void;
  fixture(path => path === "/api/projects/p" ? new Promise<Response>(resolve => {finish = resolve;}) : path === "/api/projects/other" ? ok({...project, id: "other", name: "Other project"}) : undefined);
  open();
  window.location.hash = "/projects/other";
  expect(await screen.findByRole("heading", {name: "Other project"})).toBeTruthy();
  finish(ok(project));
  await waitFor(() => expect(screen.queryByRole("heading", {name: "Source film"})).toBeNull());
});
it("keeps unsaved source bounds across live refresh and offers a way to discard the draft", async () => {
  const user = userEvent.setup(); fixture(); open();
  await screen.findByText("Source line 8");
  const start = screen.getByLabelText("开始时间（毫秒）") as HTMLInputElement;
  await user.clear(start); await user.type(start, "2500");
  await user.click(screen.getByRole("button", {name: "刷新状态"}));
  await waitFor(() => expect(start.value).toBe("2500"));
  await user.click(screen.getByRole("button", {name: "放弃范围修改"}));
  await waitFor(() => expect(start.value).toBe("1000"));
});
it("does not reuse the previous asset selection as fresh-file probe facts", async () => {
  fixture(path => path === "/api/projects/p" ? ok({...project, source_asset_id: "new-asset"}) : path.includes("/timeline") ? ok({...timeline, source: {...selection, stale: true}}) : path.includes("/runs?") ? ok({items: [{...probe, is_stale: true}], total: 1}) : undefined);
  open(); await screen.findByRole("heading", {name: "Source film"});
  expect(screen.getByLabelText("原片播放器").getAttribute("src")).toBe("/api/assets/new-asset/content");
  expect(screen.queryByLabelText("开始时间（毫秒）")).toBeNull();
  expect(screen.queryByRole("button", {name: "分析所选源片段"})).toBeNull();
});
it("pins a dirty source draft to its original project revision until explicitly discarded", async () => {
  const user = userEvent.setup(); let changed = false;
  const writes: Record<string, unknown>[] = [];
  const replacement = {...selection, id: "selection-b", revision: 3, start_ms: 6000, end_ms: 30000};
  fixture((path, init) => {
    if (path === "/api/projects/p") return ok({...project, revision: changed ? 8 : 7});
    if (path.includes("/timeline")) return ok({...timeline, project_revision: changed ? 8 : 7, source: changed ? replacement : selection});
    if (path === "/api/projects/p/source-selection") {
      const body = JSON.parse(String(init?.body)); writes.push(body);
      return body.revision === 7 ? ok({error: {code: "REVISION_CONFLICT", message: "Resource changed; reload and try again", retryable: true}}, 409) : ok(replacement);
    }
  });
  open(); await screen.findByText("Source line 8");
  const start = screen.getByLabelText("开始时间（毫秒）") as HTMLInputElement;
  await user.clear(start); await user.type(start, "2500");
  changed = true;
  await user.click(screen.getByRole("button", {name: "刷新状态"}));
  await screen.findByText(/服务器已选：6.000–30.000/);
  expect(start.value).toBe("2500");
  await user.click(screen.getByRole("button", {name: "保存源片段"}));
  await waitFor(() => expect(writes).toHaveLength(1));
  expect(writes[0]).toMatchObject({revision: 7, source_asset_id: "asset", start_ms: 2500, end_ms: 20000});
  expect(await screen.findByText(/REVISION_CONFLICT/)).toBeTruthy();
  expect(start.value).toBe("2500");
  await user.click(screen.getByRole("button", {name: "放弃范围修改"}));
  await waitFor(() => expect(start.value).toBe("6000"));
  await user.click(screen.getByRole("button", {name: "保存源片段"}));
  await waitFor(() => expect(writes).toHaveLength(2));
  expect(writes[1]).toMatchObject({revision: 8, source_asset_id: "asset", start_ms: 6000, end_ms: 30000});
});
it("opens manual role/reference editing explicitly without submitting media or provider work", async () => {
  const user = userEvent.setup();
  const fetch = fixture(path => path.includes("/speakers?") ? ok({items: [{id: "speaker", selection_id: "selection", name: "Role A", description: "", revision: 1, archived: false}], total: 1}) : path.includes("/references?") ? ok({items: [], total: 0}) : undefined);
  open(); await screen.findByRole("heading", {name: "Source film"});
  expect(fetch.mock.calls.some(([path]) => String(path).includes("/speakers?"))).toBe(false);
  await user.click(screen.getByRole("button", {name: "编辑角色与参考音"}));
  expect(await screen.findByLabelText("新角色名称")).toBeTruthy();
  expect(fetch.mock.calls.filter(([, init]) => init?.method && init.method !== "GET")).toHaveLength(0);
});
