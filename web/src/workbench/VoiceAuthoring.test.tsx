import {afterEach, expect, it, vi} from "vitest";
import {cleanup, render, screen, waitFor} from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import RoleReferencePanel from "./RoleReferencePanel";
// Contract doubles only; these tests never validate media or call inference.
const controls = {ns: 32, gs: 2, dn: true, sp: 1, du: null, pp: true, po: true};
const source = {id: "selection", revision: 2, stale: false};
const baseTimeline = {source, transcript: {id: "transcript", stale: false}, segments: [{id: "row", revision: 1, text: "Source line", absolute_start_ms: 0, absolute_end_ms: 1000}], total: 1};
const settings = {revision: 4, override: true, controls, history: [{id: "v4", revision: 4, override: true, controls, created_at: "2026-11-01T00:00:00Z"}], total: 1};
const ok = (data: unknown, status = 200) => new Response(JSON.stringify(data), {status});
function fixture({write, currentSettings = () => settings, timeline = () => baseTimeline}: {write?: (path: string, init: RequestInit) => Response | Promise<Response>; currentSettings?: () => typeof settings; timeline?: () => typeof baseTimeline} = {}) {
  return vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
    const path = String(input);
    if (init?.method) return write ? write(path, init) : ok({});
    if (path.includes("/languages?")) return ok({items: [{code: "en", name: "英语", variants: [], is_auto: false}, {code: "zh", name: "中文", variants: [], is_auto: false}]});
    if (path.includes("/provider-settings")) return ok({providers: {synthesis: {adapter: "omnivoice", revision: 2, capabilities: {controls: Object.keys(controls)}}}});
    if (path.includes("/language-tracks?")) return ok({items: [{tag: "en", revision: 1, materialized: true, archived: false}, {tag: "zh", revision: 1, materialized: true, archived: false}], total: 2});
    if (path.includes("/voice-settings")) return ok(currentSettings());
    if (path.includes("/timeline?")) return ok(timeline());
    if (path.includes("/speakers?") || path.includes("/references?")) return ok({items: [], total: 0});
    throw new Error(path);
  });
}
const props = {projectId: "p", csrf: "csrf", sourceLanguage: "en", refreshVersion: 0, onChanged: vi.fn()};
afterEach(() => {cleanup(); vi.restoreAllMocks();});
it("uploads exact multipart audio/text/explicit language and displays the real queued task", async () => {
  const user = userEvent.setup(); let sent: FormData | undefined;
  fixture({write: (path, init) => {expect(path).toBe("/api/projects/p/references/upload"); sent = init.body as FormData; expect(new Headers(init.headers).get("X-CSRF-Token")).toBe("csrf"); return ok({run: {id: "reference-run", stage: "reference", status: "queued"}, reference: null}, 202);}});
  render(<RoleReferencePanel {...props} />);
  const input = await screen.findByLabelText("参考音文件");
  await user.upload(input, new File(["audio"], "sample.wav", {type: "audio/wav"}));
  await user.type(screen.getByLabelText("上传参考音原文"), "Exact reference text");
  await user.click(screen.getByRole("button", {name: "中文 · zh"}));
  await user.click(screen.getByRole("button", {name: "上传参考音"}));
  await waitFor(() => expect(sent).toBeInstanceOf(FormData));
  expect([...sent!.keys()]).toEqual(["file", "text", "language"]);
  expect(sent!.get("text")).toBe("Exact reference text"); expect(sent!.get("language")).toBe("zh");
  expect(await screen.findByText(/reference-run.*排队中/)).toBeTruthy();
  expect(screen.getByText(/时长与警告以处理完成后的参考音库为准/)).toBeTruthy();
});
it("blocks reference files over the real 64 MiB endpoint limit without uploading", async () => {
  const user = userEvent.setup(); const fetch = fixture(); render(<RoleReferencePanel {...props} />);
  const file = new File(["audio"], "large.wav", {type: "audio/wav"}); Object.defineProperty(file, "size", {value: 64 * 1024 * 1024 + 1});
  await user.upload(await screen.findByLabelText("参考音文件"), file);
  expect(screen.getByText(/不能超过 64 MiB/)).toBeTruthy();
  expect(fetch.mock.calls.filter(([, init]) => init?.method)).toHaveLength(0);
});
it("pins dirty controls and CAS/source guards through live refresh and blocks scope switches", async () => {
  const user = userEvent.setup(); let sent: unknown, current = settings, timeline = baseTimeline;
  fixture({currentSettings: () => current, timeline: () => timeline, write: (_path, init) => {sent = JSON.parse(String(init.body)); return ok({error: {code: "REVISION_CONFLICT"}}, 409);}});
  const view = render(<RoleReferencePanel {...props} />);
  const speed = await screen.findByLabelText("语速倍数"); await user.clear(speed); await user.type(speed, "1.2");
  current = {...settings, revision: 9, controls: {...controls, sp: 0.8}}; timeline = {...baseTimeline, source: {...source, revision: 7}, transcript: {id: "new-transcript", stale: false}};
  view.rerender(<RoleReferencePanel {...props} refreshVersion={1} />);
  await screen.findByText(/源或配音参数已更新/);
  expect((speed as HTMLInputElement).value).toBe("1.2");
  expect((screen.getByLabelText("配音参数目标语言") as HTMLSelectElement).disabled).toBe(true);
  expect((screen.getByLabelText("参数作用范围") as HTMLSelectElement).disabled).toBe(true);
  await user.click(screen.getByRole("button", {name: "保存配音参数"}));
  await waitFor(() => expect(sent).toEqual({selection_revision: 2, transcript_revision: "transcript", revision: 4, controls: {...controls, sp: 1.2}}));
  expect(await screen.findByText(/REVISION_CONFLICT/)).toBeTruthy();
  await user.click(screen.getByRole("button", {name: "放弃配音参数修改"}));
  await waitFor(() => expect((screen.getByLabelText("语速倍数") as HTMLInputElement).value).toBe("0.8"));
});
it("saves line inheritance as null with its own revision and shows effective settings history", async () => {
  const user = userEvent.setup(); let sent: unknown, writePath = "";
  fixture({write: (path, init) => {writePath = path; sent = JSON.parse(String(init.body)); return ok({...settings, revision: 5, override: false});}});
  render(<RoleReferencePanel {...props} />);
  await screen.findByLabelText("语速倍数");
  await user.selectOptions(screen.getByLabelText("参数作用范围"), "row");
  await screen.findByText(/当前为本行覆盖/);
  await user.click(screen.getByLabelText("使用本范围自定义参数"));
  await user.click(screen.getByRole("button", {name: "保存配音参数"}));
  await waitFor(() => expect(writePath).toBe("/api/projects/p/language-tracks/en/segments/row/voice-settings"));
  expect(sent).toEqual({selection_revision: 2, transcript_revision: "transcript", revision: 4, controls: null});
  expect(screen.getByText(/当前生效参数/)).toBeTruthy();
  expect(screen.getByText(/历史版本 4/)).toBeTruthy();
});
it("refreshes the published reference library explicitly without restarting reference work", async () => {
  const user = userEvent.setup(), fetch = fixture(); render(<RoleReferencePanel {...props} />);
  await user.click(await screen.findByRole("button", {name: "刷新参考音库"}));
  await waitFor(() => expect(fetch.mock.calls.filter(([input]) => String(input).includes("/references?"))).toHaveLength(2));
  expect(fetch.mock.calls.filter(([, init]) => init?.method)).toHaveLength(0);
});
it("accepts finite control precision allowed by the backend contract", async () => {
  const user = userEvent.setup(); let sent: unknown;
  fixture({write: (_path, init) => {sent = JSON.parse(String(init.body)); return ok({...settings, revision: 5});}});
  render(<RoleReferencePanel {...props} />);
  const speed = await screen.findByLabelText("语速倍数"); await user.clear(speed); await user.type(speed, "1.125");
  await user.click(screen.getByRole("button", {name: "保存配音参数"}));
  await waitFor(() => expect(sent).toEqual({selection_revision: 2, transcript_revision: "transcript", revision: 4, controls: {...controls, sp: 1.125}}));
});
