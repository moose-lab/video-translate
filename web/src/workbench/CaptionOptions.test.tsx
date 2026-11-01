import {afterEach, expect, it, vi} from "vitest";
import {cleanup, fireEvent, render, screen, waitFor} from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import DeliveryForm from "./DeliveryForm";
import PipelineStartForm from "./PipelineStartForm";
import DeliveryResult from "./DeliveryResult";
import type {FitDetail, Delivery} from "./finishingTypes";
import type {Timeline} from "./types";
// Contract doubles only: captions, fonts, proofs and media metadata below are synthetic UI fixtures.
const plan = {id: "fit", run_id: "fit-run", purpose: "dub", status: "succeeded", current: true, timeline_feasible: true, dub_ready: true, plan: {}, tracks: [{id: "zh-track", tag: "zh"}]} as FitDetail;
const timeline = {editor_fingerprint: "editor-a", source: {stale: false}, transcript: {stale: false, provenance: "import"}} as Timeline;
const tracks = [{id: "zh-track", tag: "zh", archived: false, materialized: true, mode: "Fast" as const, revision: 1}];
const ok = (value: unknown, status = 200) => new Response(JSON.stringify(value), {status});
afterEach(() => {cleanup(); vi.restoreAllMocks();});
it("keeps legacy delivery requests free of optional caption fields until enabled", async () => {
  let body: Record<string, unknown> | undefined; const user = userEvent.setup();
  vi.spyOn(globalThis, "fetch").mockImplementation(async (_input, init) => {body = JSON.parse(String(init?.body)); return ok({id: "delivery"});});
  render(<DeliveryForm projectId="p" csrf="csrf" plan={plan} onCreated={vi.fn()} />);
  await user.click(screen.getByRole("button", {name: "创建导出"}));
  await waitFor(() => expect(body).toBeTruthy()); expect(body).not.toHaveProperty("caption_options");
});
it("submits selected sidecar formats and bilingual burn-in with only actual parent targets", async () => {
  let body: Record<string, unknown> | undefined; const user = userEvent.setup();
  vi.spyOn(globalThis, "fetch").mockImplementation(async (_input, init) => {body = JSON.parse(String(init?.body)); return ok({id: "delivery"});});
  render(<DeliveryForm projectId="p" csrf="csrf" plan={plan} onCreated={vi.fn()} />);
  await user.click(screen.getByLabelText("启用高级字幕选项"));
  await user.click(screen.getByLabelText("字幕文件 ASS")); await user.click(screen.getByLabelText("将字幕烧录到画面"));
  await user.selectOptions(screen.getByLabelText("烧录字幕内容"), "bilingual"); await user.selectOptions(screen.getByLabelText("字幕目标语言"), "zh");
  expect(screen.queryByRole("option", {name: /日语/})).toBeNull();
  await user.selectOptions(screen.getByLabelText("字幕字体类别"), "cjk"); fireEvent.change(screen.getByLabelText("字幕基准字号"), {target: {value: "48"}});
  await user.click(screen.getByRole("button", {name: "创建导出"}));
  await waitFor(() => expect(body?.caption_options).toEqual({formats: ["srt", "vtt", "ass"], burn_in: true, track: "bilingual", target_track: "zh", font_profile: "cjk", font_size: 48, style: "outlined"}));
});
it("validates empty formats and bounded font size, and omits the object again when disabled", async () => {
  const user = userEvent.setup();
  render(<DeliveryForm projectId="p" csrf="csrf" plan={plan} onCreated={vi.fn()} />);
  await user.click(screen.getByLabelText("启用高级字幕选项")); await user.click(screen.getByLabelText("字幕文件 SRT")); await user.click(screen.getByLabelText("字幕文件 VTT"));
  expect((screen.getByRole("button", {name: "创建导出"}) as HTMLButtonElement).disabled).toBe(true);
  await user.click(screen.getByLabelText("将字幕烧录到画面"));
  fireEvent.change(screen.getByLabelText("字幕基准字号"), {target: {value: "97"}});
  expect((screen.getByRole("button", {name: "创建导出"}) as HTMLButtonElement).disabled).toBe(true);
  fireEvent.change(screen.getByLabelText("字幕基准字号"), {target: {value: "42"}});
  expect((screen.getByRole("button", {name: "创建导出"}) as HTMLButtonElement).disabled).toBe(false);
  await user.click(screen.getByLabelText("启用高级字幕选项"));
  expect(screen.queryByLabelText("字幕文件 ASS")).toBeNull();
});
it("includes explicit caption options under pipeline delivery options with selected finish targets", async () => {
  const user = userEvent.setup(); let body: {delivery_options: {caption_options?: unknown}} | undefined;
  vi.spyOn(globalThis, "fetch").mockImplementation(async (_input, init) => {body = JSON.parse(String(init?.body)); return ok({id: "flow"});});
  render(<PipelineStartForm projectId="p" csrf="csrf" timeline={timeline} tracks={tracks} onCreated={vi.fn()} onClose={vi.fn()} />);
  await user.click(screen.getByLabelText("流程包含中文")); await user.click(screen.getByLabelText("共同导出包含中文"));
  await user.click(screen.getByLabelText("启用高级字幕选项")); await user.click(screen.getByLabelText("将字幕烧录到画面"));
  await user.selectOptions(screen.getByLabelText("烧录字幕内容"), "target"); await user.selectOptions(screen.getByLabelText("字幕目标语言"), "zh");
  await user.click(screen.getByRole("button", {name: "启动所选流程"}));
  await waitFor(() => expect(body?.delivery_options.caption_options).toMatchObject({burn_in: true, track: "target", target_track: "zh"}));
});
it("renders only returned ASS, owned VTT tracks, actual burn metadata and bounded font failures", () => {
  const delivery = {id: "d", status: "succeeded", purpose: "dub", current: true, phase: "export", manifest_valid: true, source_window: {start_ms: 0, end_ms: 1000}, choices: {captions: "sidecar", default_audio_track: "zh"}, artifacts: [{format: "mp4", asset_id: "video", metadata: {duration_ms: 1200, captions: {mode: "burn_in", track: "bilingual", target_track: "zh", font_size: 48, style: "outlined"}}, byte_size: 100, track: "all"}, {format: "ass", asset_id: "ass", byte_size: 10, track: "zh", metadata: {}}, {format: "vtt", content_type: "text/vtt", asset_id: "vtt", byte_size: 10, track: "zh", metadata: {}}], caption_status: {glyph_count: 4, fonts: [{family: "Measured font", glyph_count: 4}]}, error: {code: "CONFIGURATION", issue: "FONT_GLYPHS_MISSING", missing: ["U+4E2D", "/private/path/font.ttf"]}} as Delivery;
  render(<DeliveryResult delivery={delivery} />);
  expect(screen.getByText(/画面已烧录.*双语/)).toBeTruthy(); expect(screen.getByText(/Measured font/)).toBeTruthy();
  expect(screen.getByRole("link", {name: /下载.*ASS/}).getAttribute("href")).toBe("/api/assets/ass/content");
  const track = screen.getByLabelText("导出视频预览").querySelector("track"); expect(track?.getAttribute("src")).toBe("/api/assets/vtt/content"); expect(track?.hasAttribute("default")).toBe(false);
  expect(screen.getByText(/U\+4E2D/)).toBeTruthy(); expect(screen.queryByText(/private\/path/)).toBeNull();
});
it("keeps a removed pipeline finish target invalid instead of silently choosing another caption language", async () => {
  const user = userEvent.setup();
  render(<PipelineStartForm projectId="p" csrf="csrf" timeline={timeline} tracks={[...tracks, {...tracks[0], id: "ja-track", tag: "ja"}]} onCreated={vi.fn()} onClose={vi.fn()} />);
  await user.click(screen.getByLabelText("流程包含中文")); await user.click(screen.getByLabelText("共同导出包含中文"));
  await user.click(screen.getByLabelText("启用高级字幕选项")); await user.click(screen.getByLabelText("将字幕烧录到画面"));
  await user.selectOptions(screen.getByLabelText("烧录字幕内容"), "target"); await user.selectOptions(screen.getByLabelText("字幕目标语言"), "zh");
  await user.click(screen.getByLabelText("流程包含日语")); await user.click(screen.getByLabelText("共同导出包含日语")); await user.click(screen.getByLabelText("共同导出包含中文"));
  expect((screen.getByRole("button", {name: "启动所选流程"}) as HTMLButtonElement).disabled).toBe(true);
  expect((screen.getByLabelText("字幕目标语言") as HTMLSelectElement).value).toBe("zh");
  await user.selectOptions(screen.getByLabelText("字幕目标语言"), "ja");
  expect((screen.getByRole("button", {name: "启动所选流程"}) as HTMLButtonElement).disabled).toBe(false);
});
