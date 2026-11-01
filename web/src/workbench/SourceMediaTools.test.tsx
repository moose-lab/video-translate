import {afterEach, expect, it, vi} from "vitest";
import {cleanup, fireEvent, render, screen, waitFor} from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import SourcePanel from "./SourcePanel";
import LineAudioPanel from "./LineAudioPanel";
import type {Timeline} from "./types";
import type {AudioLine} from "./audioTypes";
// Only UI contract doubles. All waveform values below are synthetic test measurements.
const project = {id: "p", name: "Film", revision: 7, status: "uploaded", source_language: "en", target_languages: ["zh"], source_asset_id: "asset", source_track_index: 0};
const timeline: Timeline = {editor_fingerprint: "head", project_revision: 7, source: {id: "selection", revision: 2, source_asset_id: "asset", start_ms: 1000, end_ms: 3000, stale: false, track: {audio_ordinal: 0, stream_index: 1, codec: "aac", language: "en", channels: 2, sample_rate: 48000, duration_ms: 10000}}, transcript: {id: "transcript", stale: false, provenance: "test-double"}, segments: [], total: 0, cast: [], cast_total: 0};
const props = {project, timeline, runs: [], csrf: "csrf", refresh: vi.fn(), providers: null, workflow: null, onWorkflow: vi.fn(), refreshVersion: 0};
const ok = (value: unknown, status = 200) => new Response(JSON.stringify(value), {status});
const imported = {id: "import", run_id: "import-run", adapter: "youtube", status: "queued", stale: false, source_asset_id: null, probe_run_id: null, error: null, next_action: null, created_at: "2026-11-01T01:00:00Z"};
const job = {id: "wave", run_id: "wave", status: "succeeded", current: true, kind: "source", output_id: null, artifact: {asset_id: "wave-asset", url: "/api/assets/wave-asset/content"}, waveform: null, error: null};
const envelope = {policy: "pcm-envelope-v1", input_sha256: "a".repeat(64), sample_rate: 8000, channels: 2, sample_count: 16000, duration_ms: 2000, bin_count: 2, bins: [{start_sample: 0, end_sample: 8000, min: -.5, max: .25, rms: .2}, {start_sample: 8000, end_sample: 16000, min: -1, max: .75, rms: .4}], clock: "source_selection_relative", provenance: {source_start_ms: 1000, source_end_ms: 3000, selection_revision: 2, transcript_revision: "transcript"}};
const discovery = {source: {available: true, asset_id: "pcm", preparation_hint: null}, natural_voice: [], items: [job], limit: 100, offset: 0};
afterEach(() => {cleanup(); vi.restoreAllMocks();});
it("discovers durable source imports only after opening, without dispatching downloads", async () => {
  const fetch = vi.spyOn(globalThis, "fetch").mockResolvedValue(ok({items: [{...imported, status: "failed", next_action: "upload_source", error: {code: "SOURCE_IMPORT_UNAVAILABLE", message: "https://secret.invalid/?token=PRIVATE"}}], total: 1}));
  render(<SourcePanel {...props} />);
  expect(fetch).not.toHaveBeenCalled();
  await userEvent.click(screen.getByRole("button", {name: "从公开链接导入"}));
  expect(await screen.findByText(/YouTube · 失败/)).toBeTruthy();
  expect(screen.getByText(/可改用上方文件上传/)).toBeTruthy();
  expect(screen.queryByText(/PRIVATE/)).toBeNull();
  expect(fetch.mock.calls.every(([, init]) => !init?.method)).toBe(true);
});
it("pins URL draft revision, keeps it on conflict, and clears it only after successful admission", async () => {
  const user = userEvent.setup(), writes: unknown[] = []; let fail = true;
  vi.spyOn(globalThis, "fetch").mockImplementation(async (_input, init) => {
    if (init?.method) {writes.push(JSON.parse(String(init.body))); return fail ? ok({error: {code: "REVISION_CONFLICT", message: "token=PRIVATE"}}, 409) : ok(imported, 202);}
    return ok({items: [], total: 0});
  });
  const view = render(<SourcePanel {...props} />);
  await user.click(screen.getByRole("button", {name: "从公开链接导入"}));
  const input = screen.getByLabelText("公开视频 HTTPS 链接");
  await user.type(input, "https://www.youtube.com/watch?v=Example01");
  view.rerender(<SourcePanel {...props} project={{...project, revision: 9}} refreshVersion={1} />);
  await user.click(screen.getByRole("button", {name: "提交链接导入"}));
  await waitFor(() => expect(writes).toEqual([{url: "https://www.youtube.com/watch?v=Example01", revision: 7}]));
  expect(await screen.findByText(/REVISION_CONFLICT/)).toBeTruthy();
  expect((input as HTMLInputElement).value).toContain("Example01");
  expect(screen.queryByText(/PRIVATE/)).toBeNull();
  await user.click(screen.getByRole("button", {name: "放弃链接修改"}));
  await user.type(input, "https://example.org/video.mp4"); fail = false;
  await user.click(screen.getByRole("button", {name: "提交链接导入"}));
  await waitFor(() => expect(writes[1]).toEqual({url: "https://example.org/video.mp4", revision: 9}));
  await waitFor(() => expect((input as HTMLInputElement).value).toBe(""));
});
it("blocks link admission while source range has unsaved changes", async () => {
  vi.spyOn(globalThis, "fetch").mockResolvedValue(ok({items: [], total: 0}));
  render(<SourcePanel {...props} />);
  await userEvent.click(screen.getByRole("button", {name: "从公开链接导入"}));
  await userEvent.type(screen.getByLabelText("公开视频 HTTPS 链接"), "https://example.org/video.mp4");
  fireEvent.change(screen.getByLabelText("开始时间（毫秒）"), {target: {value: "1500"}});
  expect((screen.getByRole("button", {name: "提交链接导入"}) as HTMLButtonElement).disabled).toBe(true);
});
it("renders actual sample-grid min/max/RMS and seeks original video with the selected-window offset", async () => {
  const fetch = vi.spyOn(globalThis, "fetch").mockImplementation(async input => ok(String(input).endsWith("/wave") ? {...job, waveform: envelope} : discovery));
  render(<SourcePanel {...props} />);
  await userEvent.click(screen.getByRole("button", {name: "查看源音频波形"}));
  expect(await screen.findByRole("img", {name: "实测源音频波形"})).toBeTruthy();
  expect(screen.getByText(/8000 Hz · 2 声道 · 16000 采样帧/)).toBeTruthy();
  expect(screen.getByText(/片段内 0 秒对应原片 1.000 秒/)).toBeTruthy();
  const slider = screen.getByRole("slider", {name: "源音频波形播放位置"});
  fireEvent.change(slider, {target: {value: "1000"}});
  expect((screen.getByLabelText("原片播放器") as HTMLVideoElement).currentTime).toBe(2);
  expect(screen.getByRole("img", {name: "实测源音频波形"}).querySelectorAll(".waveform-envelope")).toHaveLength(2);
  expect(screen.getByRole("img", {name: "实测源音频波形"}).querySelectorAll(".waveform-rms")).toHaveLength(2);
  expect(fetch.mock.calls.every(([, init]) => !init?.method)).toBe(true);
});
it("queues CPU waveform only on explicit click with exact current source guard", async () => {
  const writes: {path: string; body: unknown}[] = [];
  vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
    if (init?.method) {writes.push({path: String(input), body: JSON.parse(String(init.body))}); return ok({...job, status: "queued", artifact: null}, 202);}
    return ok({...discovery, items: []});
  });
  render(<SourcePanel {...props} />);
  await userEvent.click(screen.getByRole("button", {name: "查看源音频波形"}));
  await userEvent.click(await screen.findByRole("button", {name: "计算源音频波形"}));
  await waitFor(() => expect(writes).toEqual([{path: "/api/projects/p/waveforms", body: {guard: {selection_revision: 2, transcript_revision: "transcript"}, kind: "source", bins: 600}}]));
  expect(await screen.findByText(/波形：排队中/)).toBeTruthy();
});
it("natural voice waveform uses its own audio zero and does not imply fitted timing or listening acceptance", async () => {
  const voiceJob = {...job, kind: "natural_voice", output_id: "out"}, voiceEnvelope = {...envelope, clock: "natural_audio_relative", provenance: {...envelope.provenance, output_id: "out"}};
  vi.spyOn(globalThis, "fetch").mockImplementation(async input => ok(String(input).endsWith("/wave") ? {...voiceJob, waveform: voiceEnvelope} : {...discovery, items: [voiceJob], natural_voice: [{output_id: "out", asset_id: "audio", segment_id: "row", track_id: "zh"}]}));
  const row = {id: "row", text: "Source", start_ms: 0, end_ms: 1000, absolute_start_ms: 1000, absolute_end_ms: 2000, speaker_id: null, original_speaker_label: null, source_text_fingerprint: "fp", translation: {revision: 1, text: "目标文字", locked: false, approved: true, stale: false, needs_review: false, source_text_fingerprint: "fp"}};
  const line = {segment_id: "row", selection_revision: 1, selected: {id: "out", audio_asset_id: "audio", natural_duration_ms: 2000, slot_duration_ms: 1000, stale: false, evidence_status: "validated", ready: false, acceptance: "not_assessed", review_revision: 0, qc_evidence_fingerprint: "qc", qc: {status: "succeeded", comparison: null, request_id: null}, qc_risks: {}, issues: []}, outstanding: [], reference_review: null, issues: []} as AudioLine;
  render(<LineAudioPanel projectId="p" tag="zh" row={row} index={1} source={{selection_revision: 2, transcript_revision: "transcript"}} line={line} csrf="csrf" refresh={vi.fn()} dirty={false} runs={[]} />);
  await userEvent.click(screen.getByRole("button", {name: /配音与试听 第 1 行/}));
  await userEvent.click(screen.getByRole("button", {name: "查看自然配音波形"}));
  await screen.findByRole("img", {name: "实测自然配音波形"});
  fireEvent.change(screen.getByRole("slider", {name: "自然配音波形播放位置"}), {target: {value: "1000"}});
  expect((screen.getByLabelText("第 1 行自然配音") as HTMLAudioElement).currentTime).toBe(1);
  expect(screen.getByText(/从此行自然音频的 0 秒开始/)).toBeTruthy();
  expect((screen.getByRole("button", {name: "接受第 1 行配音"}) as HTMLButtonElement).disabled).toBe(true);
});
it("rejects inconsistent measured bins before rendering SVG", async () => {
  const invalid = {...envelope, bins: [{...envelope.bins[0], rms: .9}, envelope.bins[1]]};
  vi.spyOn(globalThis, "fetch").mockImplementation(async input => ok(String(input).endsWith("/wave") ? {...job, waveform: invalid} : discovery));
  render(<SourcePanel {...props} />);
  await userEvent.click(screen.getByRole("button", {name: "查看源音频波形"}));
  expect(await screen.findByRole("alert")).toHaveProperty("textContent", expect.stringContaining("波形不可用"));
  expect(screen.queryByRole("img", {name: "实测源音频波形"})).toBeNull();
});
it("retains an unknown URL submission draft and discovers durable records without a second POST", async () => {
  let writes = 0, reads = 0;
  vi.spyOn(globalThis, "fetch").mockImplementation(async (_input, init) => {
    if (init?.method) {writes++; throw new TypeError("https://secret.invalid/?token=PRIVATE");}
    reads++; return ok({items: writes ? [imported] : [], total: writes ? 1 : 0});
  });
  render(<SourcePanel {...props} />);
  await userEvent.click(screen.getByRole("button", {name: "从公开链接导入"}));
  await userEvent.type(screen.getByLabelText("公开视频 HTTPS 链接"), "https://example.org/video.mp4");
  await userEvent.click(screen.getByRole("button", {name: "提交链接导入"}));
  expect(await screen.findByText(/YouTube · 排队中/)).toBeTruthy();
  expect((screen.getByLabelText("公开视频 HTTPS 链接") as HTMLInputElement).value).toBe("https://example.org/video.mp4");
  expect((screen.getByRole("button", {name: "提交链接导入"}) as HTMLButtonElement).disabled).toBe(true);
  expect(writes).toBe(1); expect(reads).toBeGreaterThan(1); expect(screen.queryByText(/PRIVATE/)).toBeNull();
});
it("opens a validated cached waveform returned by calculation admission", async () => {
  vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
    if (init?.method === "POST") return ok(job, 202);
    return ok(String(input).endsWith("/wave") ? {...job, waveform: envelope} : {...discovery, items: []});
  });
  render(<SourcePanel {...props} />);
  await userEvent.click(screen.getByRole("button", {name: "查看源音频波形"}));
  await waitFor(() => expect((screen.getByRole("button", {name: "计算源音频波形"}) as HTMLButtonElement).disabled).toBe(false));
  await userEvent.click(screen.getByRole("button", {name: "计算源音频波形"}));
  expect(await screen.findByRole("img", {name: "实测源音频波形"})).toBeTruthy();
});
