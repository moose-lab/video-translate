import {afterEach, expect, it, vi} from "vitest";
import {cleanup, fireEvent, render, screen, waitFor} from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import LineAudioPanel from "./LineAudioPanel";
import type {AudioLine, NaturalOutput} from "./audioTypes";
// Contract doubles: fabricated audio/QC facts test UI guards; no inference or listening claim is made.
const output = {id: "out", audio_asset_id: "audio", natural_duration_ms: 1850, slot_duration_ms: 1000, stale: false, evidence_status: "validated", ready: false, acceptance: "not_assessed", review_revision: 0, qc_evidence_fingerprint: "qc-a", qc: {status: "failed", comparison: null, request_id: null}, qc_risks: {gap: "failed"}, issues: ["QC_FAILED"], qc_override: false} as NaturalOutput;
const line: AudioLine = {segment_id: "s1", selection_revision: 3, selected: output, outstanding: [], reference_review: {version_id: "ref", duration_ms: 5000, warnings: [], acknowledgement_required: false}, issues: []};
const row = {id: "s1", text: "Source", start_ms: 0, end_ms: 1000, absolute_start_ms: 0, absolute_end_ms: 1000, speaker_id: null, original_speaker_label: null, source_text_fingerprint: "source-fp", translation: {revision: 4, text: "目标文字", locked: false, approved: true, stale: false, needs_review: false, source_text_fingerprint: "source-fp"}};
const props = {projectId: "p", tag: "zh", row, index: 1, source: {selection_revision: 2, transcript_revision: "transcript"}, line, csrf: "csrf", refresh: vi.fn(), dirty: false, runs: []};
const ok = (value: unknown, status = 200) => new Response(JSON.stringify(value), {status});
afterEach(() => {cleanup(); vi.restoreAllMocks();});
it("shows actual natural duration and private audio without starting generation or QC", async () => {
  const user = userEvent.setup(), fetch = vi.spyOn(globalThis, "fetch").mockResolvedValue(ok({}));
  render(<LineAudioPanel {...props} />);
  await user.click(screen.getByRole("button", {name: /配音与试听 第 1 行/}));
  expect(screen.getByText(/实测自然时长 1.850 秒/)).toBeTruthy();
  expect(screen.getByLabelText("第 1 行自然配音").getAttribute("src")).toBe("/api/assets/audio/content");
  expect(screen.getByText(/质检失败/)).toBeTruthy();
  expect(fetch).not.toHaveBeenCalled();
  expect((screen.getByRole("button", {name: "接受第 1 行配音"}) as HTMLButtonElement).disabled).toBe(true);
});
it("requires exact translation/reference acknowledgement before explicit generation and resets it when those versions change", async () => {
  const user = userEvent.setup(); let sent: unknown;
  vi.spyOn(globalThis, "fetch").mockImplementation(async (_input, init) => {sent = JSON.parse(String(init?.body)); return ok({id: "generation", status: "running", lines: []}, 202);});
  const unapproved = {...row, translation: {...row.translation, approved: false}};
  const warned = {...line, selected: null, selection_revision: 0, reference_review: {...line.reference_review!, warnings: ["short"], acknowledgement_required: true}};
  const view = render(<LineAudioPanel {...props} row={unapproved} line={warned} />);
  await user.click(screen.getByRole("button", {name: /配音与试听 第 1 行/}));
  const generate = screen.getByRole("button", {name: "生成第 1 行配音"}) as HTMLButtonElement;
  expect(generate.disabled).toBe(true);
  await user.click(screen.getByLabelText(/我已核对当前第 1 行译文/));
  await user.click(screen.getByLabelText(/我已检查当前参考音及其风险/));
  await user.click(generate);
  await waitFor(() => expect(sent).toEqual({selection_revision: 2, transcript_revision: "transcript", segments: [{id: "s1", translation_revision: 4, expected_source_text_fingerprint: "source-fp", selection_revision: 0, review_translation_revision: 4, review_reference_version_id: "ref"}], replace_selected: false, regenerate: false}));
  view.rerender(<LineAudioPanel {...props} row={{...unapproved, translation: {...unapproved.translation, revision: 5}}} line={warned} />);
  expect((screen.getByLabelText(/我已核对当前第 1 行译文/) as HTMLInputElement).checked).toBe(false);
  expect(generate.disabled).toBe(true);
});
it("requires listening and explicit QC-risk acknowledgement, then submits exact evidence-bound human review", async () => {
  const user = userEvent.setup(); const writes: {path: string; body: unknown}[] = [];
  vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {writes.push({path: String(input), body: JSON.parse(String(init?.body))}); return ok({});});
  const view = render(<LineAudioPanel {...props} />);
  await user.click(screen.getByRole("button", {name: /配音与试听 第 1 行/}));
  fireEvent.ended(screen.getByLabelText("第 1 行自然配音"));
  await user.click(screen.getByLabelText(/我已试听此音频并核对质检风险/));
  view.rerender(<LineAudioPanel {...props} line={{...line, selected: {...output, qc_evidence_fingerprint: "qc-b"}}} />);
  expect((screen.getByRole("button", {name: "接受第 1 行配音"}) as HTMLButtonElement).disabled).toBe(true);
  fireEvent.ended(screen.getByLabelText("第 1 行自然配音"));
  await user.click(screen.getByLabelText(/我已试听此音频并核对质检风险/));
  await user.click(screen.getByRole("button", {name: "接受第 1 行配音"}));
  await waitFor(() => expect(writes).toEqual([{path: "/api/projects/p/language-tracks/zh/segments/s1/audio-review", body: {selection_revision: 2, transcript_revision: "transcript", revision: 0, translation_revision: 4, expected_source_text_fingerprint: "source-fp", output_id: "out", audio_selection_revision: 3, qc_evidence_fingerprint: "qc-b", decision: "accepted", note: ""}}]));
});
it("requests independent QC explicitly against the actual selected output", async () => {
  const user = userEvent.setup(); let sent: unknown;
  const fetch = vi.spyOn(globalThis, "fetch").mockImplementation(async (_input, init) => {sent = JSON.parse(String(init?.body)); return ok({id: "qc", lines: []}, 202);});
  render(<LineAudioPanel {...props} />);
  await user.click(screen.getByRole("button", {name: /配音与试听 第 1 行/}));
  await user.click(screen.getByRole("button", {name: "检查第 1 行语音"}));
  await waitFor(() => expect(sent).toEqual({selection_revision: 2, transcript_revision: "transcript", segments: [{id: "s1", translation_revision: 4, expected_source_text_fingerprint: "source-fp", selection_revision: 3, output_id: "out"}]}));
  expect(String(fetch.mock.calls[0][0])).toBe("/api/projects/p/language-tracks/zh/voice-qc");
});
it("keeps audio-history selection guards bound to the loaded history snapshot", async () => {
  const user = userEvent.setup(); let sent: unknown;
  vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
    if (init?.method) {sent = JSON.parse(String(init.body)); return ok({error: {code: "REVISION_CONFLICT"}}, 409);}
    return ok({selection_revision: 3, selected_output_id: "out", total: 1, outputs: [{...output, id: "history-output", audio_asset_id: "history-audio"}]});
  });
  const view = render(<LineAudioPanel {...props} />);
  await user.click(screen.getByRole("button", {name: /配音与试听 第 1 行/}));
  await user.click(screen.getByRole("button", {name: "查看第 1 行音频历史"}));
  await screen.findByRole("button", {name: "选用历史音频 1"});
  view.rerender(<LineAudioPanel {...props} source={{selection_revision: 5, transcript_revision: "new-transcript"}} row={{...row, translation: {...row.translation, revision: 6}}} line={{...line, selection_revision: 7}} />);
  await user.click(screen.getByRole("button", {name: "选用历史音频 1"}));
  await waitFor(() => expect(sent).toEqual({selection_revision: 2, transcript_revision: "transcript", revision: 3, output_id: "history-output", translation_revision: 4, expected_source_text_fingerprint: "source-fp"}));
  expect(await screen.findByText(/REVISION_CONFLICT/)).toBeTruthy();
});
it("does not generate a replacement to evade a line's unknown submission", async () => {
  const user = userEvent.setup(), fetch = vi.spyOn(globalThis, "fetch").mockResolvedValue(ok({}));
  render(<LineAudioPanel {...props} line={{...line, selected: null, selection_revision: 0}} runs={[{id: "unknown", stage: "synthesize", segment_id: "s1", target_language: "zh", status: "needs_review", attempt_count: 1, is_stale: false, remote_state: "submitting", remote_id: null, safe_error: {code: "SUBMISSION_UNCERTAIN"}}]} />);
  await user.click(screen.getByRole("button", {name: /配音与试听 第 1 行/}));
  expect((screen.getByRole("button", {name: "生成第 1 行配音"}) as HTMLButtonElement).disabled).toBe(true);
  expect(fetch).not.toHaveBeenCalled();
});
it("shows a bounded empty QC detail result instead of an endless loading state", async () => {
  const user = userEvent.setup();
  vi.spyOn(globalThis, "fetch").mockResolvedValue(ok({id: "qc", total: 0, lines: []}));
  render(<LineAudioPanel {...props} line={{...line, selected: {...output, qc: {...output.qc, request_id: "qc"}}}} />);
  await user.click(screen.getByRole("button", {name: /配音与试听 第 1 行/}));
  await user.click(screen.getByRole("button", {name: "查看识别对照"}));
  expect(await screen.findByText(/当前任务未找到此行识别结果/)).toBeTruthy();
});
it("adopts its own successful history selection response before the next selection", async () => {
  const user = userEvent.setup(); const revisions: number[] = [];
  const outputs = [{...output, id: "b"}, {...output, id: "c"}];
  vi.spyOn(globalThis, "fetch").mockImplementation(async (_input, init) => {
    if (init?.method) {
      const body = JSON.parse(String(init.body)); revisions.push(body.revision);
      return ok({selection_revision: revisions.length + 3, selected_output_id: body.output_id, total: 2, outputs});
    }
    return ok({selection_revision: 3, selected_output_id: "out", total: 2, outputs});
  });
  render(<LineAudioPanel {...props} />);
  await user.click(screen.getByRole("button", {name: /配音与试听 第 1 行/}));
  await user.click(screen.getByRole("button", {name: "查看第 1 行音频历史"}));
  await user.click(await screen.findByRole("button", {name: "选用历史音频 1"}));
  await waitFor(() => expect((screen.getByRole("button", {name: "选用历史音频 1"}) as HTMLButtonElement).disabled).toBe(true));
  await user.click(screen.getByRole("button", {name: "选用历史音频 2"}));
  await waitFor(() => expect(revisions).toEqual([3, 4]));
});
it("refreshes an open recognition detail when the same QC request completes", async () => {
  const user = userEvent.setup(); let complete = false;
  const fetch = vi.spyOn(globalThis, "fetch").mockImplementation(async () => ok({id: "qc", total: 1, lines: [{id: "qc-line", segment_id: "s1", status: complete ? "succeeded" : "running", current: true, next_action: "listen_and_review", recognition: complete ? {segments: [{text: "识别完成的文字"}]} : null}]}));
  const view = render(<LineAudioPanel {...props} line={{...line, selected: {...output, qc: {...output.qc, status: "running", request_id: "qc"}}}} />);
  await user.click(screen.getByRole("button", {name: /配音与试听 第 1 行/}));
  await user.click(screen.getByRole("button", {name: "查看识别对照"}));
  await screen.findByText("尚无识别文字。");
  complete = true;
  view.rerender(<LineAudioPanel {...props} line={{...line, selected: {...output, qc_evidence_fingerprint: "new-qc", qc: {...output.qc, status: "succeeded", request_id: "qc"}}}} />);
  expect(await screen.findByText("识别完成的文字")).toBeTruthy();
  expect(fetch).toHaveBeenCalledTimes(2);
});
