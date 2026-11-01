import {afterEach, expect, it, vi} from "vitest";
import {cleanup, render, screen, waitFor} from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import TargetPanel from "./TargetPanel";
import type {Timeline} from "./types";
// Contract doubles only. Translation strings and phases below are UI fixtures, not inference results.
const project = {id: "p", name: "Film", revision: 7, status: "uploaded", source_language: "en", target_languages: ["zh", "ja"], source_asset_id: "asset", source_track_index: 0};
const data = {editor_fingerprint: "head", project_revision: 7, source: {id: "source-a", revision: 2, source_asset_id: "asset", start_ms: 0, end_ms: 10000, stale: false, track: {audio_ordinal: 0, stream_index: 1, codec: "aac", language: "en", channels: 2, sample_rate: 48000}}, transcript: {id: "transcript-a", stale: false, provenance: "contract-double"}, segments: [{id: "s1", text: "Source dialogue", start_ms: 0, end_ms: 1000, absolute_start_ms: 0, absolute_end_ms: 1000, speaker_id: null, original_speaker_label: null, source_text_fingerprint: "source-fp-a", translation: {revision: 3, revision_id: "translation-a", text: "目标文字", locked: false, approved: false, stale: false, needs_review: true, source_text_fingerprint: "source-fp-a"}}], total: 1, cast: [], cast_total: 0, language_tracks: [{id: "track", tag: "zh", revision: 4, mode: "Fast", archived: false, materialized: true}]} as Timeline;
const emptyAudio = {items: [], total: 0, ready: false, readiness: {ready_rows: 0, total: 0}};
const ok = (value: unknown, status = 200) => new Response(JSON.stringify(value), {status});
afterEach(() => {cleanup(); vi.restoreAllMocks(); window.history.replaceState(null, "", "/");});
const props = {project, sourceTimeline: data, csrf: "csrf", refreshVersion: 0, runs: [], refresh: vi.fn()};
it("reads actual target rows and changes language without submitting cloud commands", async () => {
  const user = userEvent.setup();
  const fetch = vi.spyOn(globalThis, "fetch").mockImplementation(async input => ok(String(input).includes("/synthesis?") ? emptyAudio : String(input).includes("target_language=ja") ? {...data, segments: [{...data.segments[0], translation: null}]} : data));
  render(<TargetPanel {...props} />);
  expect(await screen.findByDisplayValue("目标文字")).toBeTruthy();
  expect(screen.getByText("Source dialogue")).toBeTruthy();
  await user.click(screen.getByRole("tab", {name: /日语/}));
  await waitFor(() => expect(fetch.mock.calls.some(([path]) => String(path).includes("target_language=ja"))).toBe(true));
  expect(fetch.mock.calls.every(([, init]) => !init?.method)).toBe(true);
});
it("preserves edited text and original source/row guards after live changes, then approves only a saved row", async () => {
  const user = userEvent.setup(); let current = data;
  const writes: {path: string; body: Record<string, unknown>}[] = [];
  vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
    if (String(input).includes("/synthesis?")) return ok(emptyAudio);
    if (init?.method) {writes.push({path: String(input), body: JSON.parse(String(init.body))}); return writes.length === 1 ? ok({error: {code: "REVISION_CONFLICT", retryable: true}}, 409) : ok({});}
    return ok(current);
  });
  const view = render(<TargetPanel {...props} />);
  const text = await screen.findByLabelText("目标文字 第 1 行");
  await user.clear(text); await user.type(text, "手动修改");
  await user.click(screen.getByLabelText("锁定第 1 行"));
  current = {...data, source: {...data.source!, revision: 5}, transcript: {...data.transcript!, id: "transcript-b"}, segments: [{...data.segments[0], source_text_fingerprint: "source-fp-b", translation: {...data.segments[0].translation!, revision: 6, text: "服务器新文字"}}]};
  view.rerender(<TargetPanel {...props} refreshVersion={1} />);
  await waitFor(() => expect(screen.getByText(/源版本已变化/)).toBeTruthy());
  await user.click(screen.getByRole("button", {name: "保存第 1 行"}));
  await waitFor(() => expect(writes).toHaveLength(1));
  expect(writes[0].body).toEqual({selection_revision: 2, transcript_revision: "transcript-a", revision: 3, expected_source_text_fingerprint: "source-fp-a", text: "手动修改", locked: true, approved: false});
  expect(await screen.findByText(/REVISION_CONFLICT/)).toBeTruthy();
  expect((text as HTMLTextAreaElement).value).toBe("手动修改");
  await user.click(screen.getByRole("button", {name: "放弃第 1 行修改"}));
  expect((screen.getByLabelText("目标文字 第 1 行") as HTMLTextAreaElement).value).toBe("服务器新文字");
  await user.click(screen.getByRole("button", {name: "确认第 1 行译文"}));
  await waitFor(() => expect(writes).toHaveLength(2));
  expect(writes[1]).toEqual({path: "/api/projects/p/language-tracks/zh/approve", body: {selection_revision: 5, transcript_revision: "transcript-b", segments: [{id: "s1", revision: 6, expected_source_text_fingerprint: "source-fp-b"}]}});
});
it("submits translation only after click with exact guards and never applies shorten suggestions automatically", async () => {
  const user = userEvent.setup(); const writes: {path: string; body: unknown}[] = [];
  const command = {id: "command", target_language: "zh", mode: "Autofit", status: "review", next_action: "translation_review", phases: [{id: "phase", phase: "shorten", status: "succeeded", run_id: "run"}], suggestions: [{phase_id: "phase", segment_id: "s1", text: "更短建议", estimated: true, stale: false, applied: false}], skipped_ids: []};
  vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
    if (String(input).includes("/synthesis?")) return ok(emptyAudio);
    if (init?.method) {writes.push({path: String(input), body: JSON.parse(String(init.body))}); return ok(command, 202);}
    return String(input).includes("/translate/") ? ok(command) : ok({...data, language_tracks: [{...data.language_tracks![0], mode: "Autofit"}]});
  });
  render(<TargetPanel {...props} />); await screen.findByDisplayValue("目标文字");
  expect(writes).toHaveLength(0);
  await user.click(screen.getByRole("button", {name: "翻译本页未保护行"}));
  await waitFor(() => expect(writes).toHaveLength(1));
  expect(writes[0]).toEqual({path: "/api/projects/p/language-tracks/zh/translate", body: {selection_revision: 2, transcript_revision: "transcript-a", track_revision: 4, force_replace: false, segments: [{id: "s1", revision: 3, expected_source_text_fingerprint: "source-fp-a", locked: false, approved: false}]}});
  expect(await screen.findByText("更短建议")).toBeTruthy();
  expect(writes).toHaveLength(1); expect(window.location.hash).toContain("command=command");
});
it("blocks a new cloud command while the target has an unresolved submission", async () => {
  vi.spyOn(globalThis, "fetch").mockImplementation(async input => ok(String(input).includes("/synthesis?") ? emptyAudio : data));
  render(<TargetPanel {...props} runs={[{id: "old", stage: "translation_context", status: "needs_review", target_language: "zh", is_stale: false, attempt_count: 1, remote_state: "submitting", remote_id: null, safe_error: {code: "SUBMISSION_UNCERTAIN"}}]} />);
  await screen.findByDisplayValue("目标文字");
  expect((screen.getByRole("button", {name: "翻译本页未保护行"}) as HTMLButtonElement).disabled).toBe(true);
  expect(screen.getByText(/先在任务区核查/)).toBeTruthy();
});
it("keeps the original track revision while a mode change is unsaved", async () => {
  const user = userEvent.setup(); let current = data; let saved: unknown;
  vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
    if (String(input).includes("/synthesis?")) return ok(emptyAudio);
    if (init?.method) {saved = JSON.parse(String(init.body)); return ok({error: {code: "REVISION_CONFLICT"}}, 409);}
    return ok(current);
  });
  const view = render(<TargetPanel {...props} />); await screen.findByDisplayValue("目标文字");
  await user.selectOptions(screen.getByLabelText("翻译模式"), "Cinematic");
  current = {...data, language_tracks: [{...data.language_tracks![0], revision: 5, mode: "Autofit"}]};
  view.rerender(<TargetPanel {...props} refreshVersion={1} />);
  await waitFor(() => expect((screen.getByLabelText("翻译模式") as HTMLSelectElement).value).toBe("Cinematic"));
  await user.click(screen.getByRole("button", {name: "保存翻译模式"}));
  await waitFor(() => expect(saved).toEqual({revision: 4, mode: "Cinematic"}));
  expect(await screen.findByText(/REVISION_CONFLICT/)).toBeTruthy();
});
