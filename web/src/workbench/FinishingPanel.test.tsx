import {afterEach, expect, it, vi} from "vitest";
import {cleanup, render, screen} from "@testing-library/react";
import FinishingPanel from "./FinishingPanel";
// Contract doubles only: these exports are fabricated metadata, never real rendered media.
const delivery = {id: "delivery", run_id: "delivery-run", fit_plan_id: "fit", purpose: "incomplete_preview", status: "succeeded", current: true, phase: "export", manifest_valid: true, retiming: "shared_fit_map", comparison_kind: "retimed_original", source_window: {start_ms: 0, end_ms: 59510}, choices: {default_audio_track: "zh", captions: "sidecar"}, artifacts: [{format: "mp4", track: "all", asset_id: "video", byte_size: 123456, sha256: "checksum", content_type: "video/mp4", download_url: "/api/assets/video/content", metadata: {duration_ms: 76780}}, {format: "srt", track: "zh", asset_id: "captions", byte_size: 123, sha256: "checksum", content_type: "application/x-subrip", download_url: "/api/assets/captions/content", metadata: {}}], error: null, limitations: ["Hard subtitles are not implemented"]};
const ok = (value: unknown, status = 200) => new Response(JSON.stringify(value), {status});
afterEach(() => {cleanup(); vi.restoreAllMocks(); window.history.replaceState(null, "", "/");});
it("opens actual delivery artifacts with truthful retimed-preview labels and no mutations", async () => {
  const fetch = vi.spyOn(globalThis, "fetch").mockImplementation(async input => String(input).includes("/deliveries?") ? ok({items: [{id: "delivery", purpose: "incomplete_preview", status: "succeeded", current: null}], total: 1}) : ok(delivery));
  render(<FinishingPanel projectId="p" csrf="csrf" refreshVersion={0} />);
  expect(await screen.findByLabelText("导出视频预览")).toBeTruthy();
  expect(screen.getByLabelText("导出视频预览").getAttribute("src")).toBe("/api/assets/video/content");
  expect(screen.getByText(/源窗口 59.510 秒.*输出 76.780 秒/)).toBeTruthy();
  expect(screen.getByRole("heading", {name: "未完成试听预览"})).toBeTruthy();
  expect(screen.getByText(/对照原声也经过重定时/)).toBeTruthy();
  expect(screen.getByRole("link", {name: /下载.*MP4/}).getAttribute("href")).toBe("/api/assets/video/content");
  expect(screen.getByRole("link", {name: /下载.*SRT/}).getAttribute("href")).toBe("/api/assets/captions/content");
  expect(fetch.mock.calls.every(([, init]) => !init?.method)).toBe(true);
});
it("marks historical outputs stale and never invents artifacts for unfinished delivery", async () => {
  vi.spyOn(globalThis, "fetch").mockImplementation(async input => String(input).includes("/deliveries?") ? ok({items: [{id: "delivery", purpose: "incomplete_preview", status: "running"}], total: 1}) : ok({...delivery, current: false, status: "running", phase: "mix", artifacts: []}));
  render(<FinishingPanel projectId="p" csrf="csrf" refreshVersion={0} />);
  expect(await screen.findByText(/输入已变化/)).toBeTruthy();
  expect(screen.getByText(/混音/)).toBeTruthy();
  expect(screen.queryByLabelText("导出视频预览")).toBeNull();
  expect(screen.queryByRole("link", {name: /下载/})).toBeNull();
});
it("shows selected delivery loading during rehydration and renders the returned private artifact", async () => {
  let finish!: (value: Response) => void;
  vi.spyOn(globalThis, "fetch").mockImplementation(async input => String(input).includes("/deliveries?") ? ok({items: [{id: "delivery", purpose: "incomplete_preview", status: "succeeded"}], total: 1}) : new Promise<Response>(resolve => {finish = resolve;}));
  render(<FinishingPanel projectId="p" csrf="csrf" refreshVersion={0} />);
  expect(await screen.findByText("正在读取所选导出详情…")).toBeTruthy();
  finish(ok(delivery));
  expect(await screen.findByLabelText("导出视频预览")).toBeTruthy();
});
it("preserves a detail error when a later list response arrives and offers an explicit read retry", async () => {
  window.history.replaceState(null, "", "/#/projects/p?delivery=delivery");
  let finishList!: (value: Response) => void;
  vi.spyOn(globalThis, "fetch").mockImplementation(async input => String(input).includes("/deliveries?") ? new Promise<Response>(resolve => {finishList = resolve;}) : ok({error: {code: "INTERNAL_ERROR"}}, 500));
  render(<FinishingPanel projectId="p" csrf="csrf" refreshVersion={0} />);
  await screen.findByText(/服务器暂时无法完成操作/);
  finishList(ok({items: [{id: "delivery", purpose: "incomplete_preview", status: "succeeded"}], total: 1}));
  await screen.findByRole("combobox", {name: "已提交的导出"});
  expect(screen.getByText(/服务器暂时无法完成操作/)).toBeTruthy();
  expect(screen.getByRole("button", {name: "重新读取导出详情"})).toBeTruthy();
});
