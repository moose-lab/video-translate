import {afterEach, expect, it, vi} from "vitest";
import {cleanup, render, screen, waitFor} from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import FitWorkspace from "./FitWorkspace";
import FitSettingsForm from "./FitSettingsForm";
import DeliveryForm from "./DeliveryForm";
import type {Timeline} from "./types";
import type {FitDetail, SettingsResponse} from "./finishingTypes";
// Contract doubles only; no rendering, inference, or media approval is performed here.
const settings: SettingsResponse = {revision: 4, settings: {mode: "smart", max_audio_speed: {numerator: 6, denominator: 5}, max_picture_factor: {numerator: 2, denominator: 1}, max_borrow_ms: 0, max_output_duration_ms: 57600000}};
const timeline = {source: {revision: 2, stale: false}, transcript: {id: "transcript", stale: false}, total: 1, segments: [{id: "s", revision_id: "source-revision", source_text_fingerprint: "fp", translation: {revision: 3}}]} as Timeline;
const audio = {items: [{segment_id: "s", selection_revision: 5, selected: {id: "output", review_revision: 7, qc_evidence_fingerprint: "qc", ready: false}}], total: 1};
const fit = {id: "fit", run_id: "fit-run", purpose: "incomplete_preview", status: "succeeded", current: true, stale: false, audio_eligible: false, dub_ready: false, render_eligible: false, timeline_feasible: true, planned_output_duration_ms: {numerator: 76780, denominator: 1}, tracks: [{id: "track", tag: "zh"}], issues: ["LISTENING_NOT_ASSESSED"], lines: [], total: 1, plan: {source_duration_ms: 59510, output_duration_ms: {numerator: 76780, denominator: 1}, pieces: [], issues: []}} as FitDetail;
const ok = (value: unknown, status = 200) => new Response(JSON.stringify(value), {status});
afterEach(() => {cleanup(); vi.restoreAllMocks(); window.history.replaceState(null, "", "/");});
it("pins fitting-settings edits to the loaded base revision across live refresh", async () => {
  const user = userEvent.setup(); let saved: unknown;
  vi.spyOn(globalThis, "fetch").mockImplementation(async (_input, init) => {saved = JSON.parse(String(init?.body)); return ok({error: {code: "REVISION_CONFLICT"}}, 409);});
  const view = render(<FitSettingsForm projectId="p" csrf="csrf" data={settings} onSaved={vi.fn()} />);
  await user.selectOptions(screen.getByLabelText("拟合方式"), "fixed");
  view.rerender(<FitSettingsForm projectId="p" csrf="csrf" data={{...settings, revision: 8}} onSaved={vi.fn()} />);
  await user.click(screen.getByRole("button", {name: "保存拟合设置"}));
  await waitFor(() => expect(saved).toEqual({revision: 4, settings: {...settings.settings, mode: "fixed"}}));
  expect(await screen.findByText(/REVISION_CONFLICT/)).toBeTruthy();
});
it("captures exact source/translation/audio/QC heads and retains them across live changes until explicit reload", async () => {
  const user = userEvent.setup(); let saved: unknown;
  vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
    const path = String(input);
    if (init?.method) {saved = JSON.parse(String(init.body)); return ok({error: {code: "REVISION_CONFLICT"}}, 409);}
    if (path.includes("/fit-settings")) return ok(settings);
    if (path.includes("/fit-plans?")) return ok({items: [], total: 0});
    if (path.includes("/timeline?")) return ok(timeline);
    if (path.includes("/synthesis?")) return ok(audio);
    throw new Error(path);
  });
  const props = {projectId: "p", csrf: "csrf", refreshVersion: 0, targetLanguages: ["zh"], sourceTimeline: timeline, onDelivery: vi.fn()};
  const view = render(<FitWorkspace {...props} />);
  await user.click(await screen.findByRole("button", {name: "读取拟合输入"}));
  await screen.findByText(/已读取 1 行/);
  view.rerender(<FitWorkspace {...props} refreshVersion={1} sourceTimeline={{...timeline, source: {...timeline.source!, revision: 9}}} />);
  await user.click(screen.getByRole("button", {name: "生成拟合方案"}));
  await waitFor(() => expect(saved).toEqual({selection_revision: 2, transcript_revision: "transcript", settings_revision: 4, purpose: "incomplete_preview", tracks: [{tag: "zh", segments: [{id: "s", expected_source_revision_id: "source-revision", expected_source_text_fingerprint: "fp", translation_revision: 3, selection_revision: 5, output_id: "output", review_revision: 7, qc_evidence_fingerprint: "qc"}]}]}));
  expect(await screen.findByText(/REVISION_CONFLICT/)).toBeTruthy();
  expect(screen.getByText(/已读取 1 行/)).toBeTruthy();
});
it("allows an explicit incomplete preview despite ordinary dub eligibility flags, with exact export choices", async () => {
  const user = userEvent.setup(); let saved: unknown;
  const fetch = vi.spyOn(globalThis, "fetch").mockImplementation(async (_input, init) => {saved = JSON.parse(String(init?.body)); return ok({id: "delivery"}, 202);});
  render(<DeliveryForm projectId="p" csrf="csrf" plan={fit} onCreated={vi.fn()} />);
  expect(fetch).not.toHaveBeenCalled();
  expect((screen.getByRole("button", {name: "创建导出"}) as HTMLButtonElement).disabled).toBe(true);
  await user.click(screen.getByLabelText(/我了解这是未完成试听预览/));
  await user.selectOptions(screen.getByLabelText("输出帧率"), "30000/1001");
  await user.selectOptions(screen.getByLabelText("字幕输出"), "none");
  await user.click(screen.getByRole("button", {name: "创建导出"}));
  await waitFor(() => expect(saved).toEqual({fit_plan_id: "fit", expected_fit_run_id: "fit-run", purpose: "incomplete_preview", frame_rate: {numerator: 30000, denominator: 1001}, background_gain: 1, voice_gain: 1, include_original_comparison: true, default_audio_track: "zh", captions: "none"}));
});
