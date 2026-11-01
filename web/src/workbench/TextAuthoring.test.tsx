import {afterEach, expect, it, vi} from "vitest";
import {cleanup, render, screen, waitFor} from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import SourceRowEditor from "./SourceRowEditor";
import SubtitleImportPanel from "./SubtitleImportPanel";
import TargetContextEditor from "./TargetContextEditor";
import type {Timeline} from "./types";
// Contract doubles only. All dialogue, parser responses and context text are synthetic UI fixtures.
const row = {id: "s1", revision: 3, revision_id: "source-a", text: "Source words", start_ms: 1000, end_ms: 3000, absolute_start_ms: 6000, absolute_end_ms: 8000, speaker_id: "role", original_speaker_label: null};
const source = {selection_revision: 2, transcript_revision: "transcript-a"};
const cue = {id: "cue-1", index: 0, number: 1, start_ms: 1000, end_ms: 3000, text: "Imported words", voice_label: null, warnings: [], errors: [], proposed_matches: [{segment_id: "s1", source_number: 1, source_revision: 3, revision: 4, locked: false}]};
const preview = {digest: "digest", cues: [cue], conflicts: [], ...source};
const ok = (value: unknown, status = 200) => new Response(JSON.stringify(value), {status});
afterEach(() => {cleanup(); vi.restoreAllMocks();});
it("keeps source text and time edits on the original source/row guard after live updates", async () => {
  const user = userEvent.setup(); let saved: unknown;
  vi.spyOn(globalThis, "fetch").mockImplementation(async (_input, init) => {saved = JSON.parse(String(init?.body)); return ok({error: {code: "REVISION_CONFLICT"}}, 409);});
  const props = {projectId: "p", csrf: "csrf", source, row, index: 1, windowDuration: 10000, onSaved: vi.fn()};
  const view = render(<SourceRowEditor {...props} />);
  const text = screen.getByLabelText("源文字 第 1 行"); await user.clear(text); await user.type(text, "Manual correction");
  const end = screen.getByLabelText("源结束毫秒 第 1 行"); await user.clear(end); await user.type(end, "3500");
  view.rerender(<SourceRowEditor {...props} source={{selection_revision: 8, transcript_revision: "transcript-b"}} row={{...row, revision: 9, text: "New server text"}} />);
  await user.click(screen.getByRole("button", {name: "保存源第 1 行"}));
  await waitFor(() => expect(saved).toEqual({...source, revision: 3, text: "Manual correction", start_ms: 1000, end_ms: 3500}));
  expect(await screen.findByText(/REVISION_CONFLICT/)).toBeTruthy();
  expect((text as HTMLTextAreaElement).value).toBe("Manual correction");
});
it("previews timed source import then explicitly applies the exact guarded content and cue mapping", async () => {
  const user = userEvent.setup(); const writes: {path: string; body: unknown}[] = [];
  vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {writes.push({path: String(input), body: JSON.parse(String(init?.body))}); return String(input).endsWith("/preview") ? ok(preview) : ok({transcript_revision: "manual-transcript", count: 1}, 201);});
  const props = {projectId: "p", csrf: "csrf", guard: source, roles: [], onSaved: vi.fn()};
  const view = render(<SubtitleImportPanel {...props} />);
  const content = "1\n00:00:01,000 --> 00:00:03,000\nImported words";
  await user.type(screen.getByLabelText("导入字幕内容"), content);
  await user.click(screen.getByRole("button", {name: "预览导入"}));
  await screen.findByText("Imported words");
  expect(writes).toHaveLength(1);
  view.rerender(<SubtitleImportPanel {...props} guard={{selection_revision: 9, transcript_revision: "other-transcript"}} />);
  await user.click(screen.getByRole("button", {name: "应用新源字幕版本"}));
  await waitFor(() => expect(writes[1]).toEqual({path: "/api/projects/p/source/import/apply", body: {...source, format: "srt", content, digest: "digest", mapping: [{cue_id: "cue-1", segment_id: null, revision: 0, speaker_id: null, use_voice_label: false}], mode: "new_transcript", force_locked: false}}));
  expect(await screen.findByText(/手动导入已应用 1 行/)).toBeTruthy();
});
it("requires explicit target cue mapping and never forces a locked or approved target", async () => {
  const user = userEvent.setup(); const writes: unknown[] = [];
  vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
    if (init?.method) {writes.push(JSON.parse(String(init.body))); return String(input).endsWith("/preview") ? ok(preview) : ok({count: 1});}
    return ok({segments: [{...row, translation: {revision: 4, locked: false, approved: false}}], total: 1});
  });
  render(<SubtitleImportPanel projectId="p" csrf="csrf" guard={source} tag="zh" roles={[]} onSaved={vi.fn()} />);
  await user.type(screen.getByLabelText("导入字幕内容"), "1. Imported words");
  await user.selectOptions(screen.getByLabelText("导入格式"), "numbered");
  await user.click(screen.getByRole("button", {name: "预览导入"}));
  const apply = await screen.findByRole("button", {name: "应用目标译文导入"}) as HTMLButtonElement;
  expect(apply.disabled).toBe(true); expect(writes).toHaveLength(1);
  await user.selectOptions(await screen.findByLabelText("导入行 1 对应源行"), "s1");
  await user.click(apply);
  await waitFor(() => expect(writes[1]).toMatchObject({mapping: [{cue_id: "cue-1", segment_id: "s1", revision: 4}], force_locked: false, ...source}));
});
it("loads the exact current context from paginated history and pins edits to the original track revision", async () => {
  const user = userEvent.setup(); let saved: unknown;
  vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
    if (init?.method) {saved = JSON.parse(String(init.body)); return ok({error: {code: "REVISION_CONFLICT"}}, 409);}
    return String(input).includes("offset=50") ? ok({items: [{id: "current-context", summary: "Current summary", glossary: {term: "译法"}}], total: 51}) : ok({items: Array.from({length: 50}, (_, index) => ({id: `old-${index}`, summary: "Old", glossary: {}})), total: 51});
  });
  const track = {id: "track", tag: "zh", mode: "Cinematic" as const, revision: 4, archived: false, materialized: true, context_revision_id: "current-context"};
  const props = {projectId: "p", csrf: "csrf", track, refreshVersion: 0, onSaved: vi.fn()};
  const view = render(<TargetContextEditor {...props} />);
  const summary = await screen.findByLabelText("翻译上下文摘要");
  await user.clear(summary); await user.type(summary, "Manual summary");
  view.rerender(<TargetContextEditor {...props} track={{...track, revision: 8}} refreshVersion={1} />);
  await user.click(screen.getByRole("button", {name: "保存上下文与术语"}));
  await waitFor(() => expect(saved).toEqual({revision: 4, summary: "Manual summary", glossary: {term: "译法"}}));
  expect(await screen.findByText(/REVISION_CONFLICT/)).toBeTruthy();
});
it("splits and merges only through explicit commands with captured row revisions", async () => {
  const user = userEvent.setup(); const writes: {path: string; body: unknown}[] = [];
  vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {writes.push({path: String(input), body: JSON.parse(String(init?.body))}); return ok({segments: []});});
  const props = {projectId: "p", csrf: "csrf", source, row, next: {...row, id: "s2", revision: 4, text: "Next words", start_ms: 3000, end_ms: 4000}, index: 1, windowDuration: 10000, onSaved: vi.fn()};
  render(<SourceRowEditor {...props} />);
  await user.click(screen.getByRole("button", {name: "拆分源第 1 行"}));
  await user.type(screen.getByLabelText("拆分后第二行文字"), "Second part");
  await user.click(screen.getByRole("button", {name: "确认拆分为两行"}));
  await waitFor(() => expect(writes[0]).toEqual({path: "/api/projects/p/segments/s1/split", body: {...source, revision: 3, parts: [{text: "Source words", start_ms: 1000, end_ms: 2000, speaker_id: "role"}, {text: "Second part", start_ms: 2000, end_ms: 3000, speaker_id: "role"}]}}));
  await user.click(screen.getByRole("button", {name: "与下一源行合并"}));
  await user.click(screen.getByRole("button", {name: "确认合并这两行"}));
  await waitFor(() => expect(writes[1]).toEqual({path: "/api/projects/p/segments/merge", body: {...source, segments: [{id: "s1", revision: 3}, {id: "s2", revision: 4}], text: "Source words\nNext words", start_ms: 1000, end_ms: 4000, speaker_id: "role"}}));
});
it("keeps locked and approved target rows unavailable to import and invalidates preview when content changes", async () => {
  const user = userEvent.setup(); let applyCalls = 0;
  vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
    if (String(input).endsWith("/apply")) {applyCalls++; return ok({count: 1});}
    if (init?.method) return ok(preview);
    return ok({segments: [{...row, translation: {revision: 4, locked: true, approved: false}}, {...row, id: "s2", translation: {revision: 5, locked: false, approved: true}}], total: 2});
  });
  render(<SubtitleImportPanel projectId="p" csrf="csrf" guard={source} tag="zh" roles={[]} onSaved={vi.fn()} />);
  const content = screen.getByLabelText("导入字幕内容");
  await user.type(content, "1. Imported words"); await user.selectOptions(screen.getByLabelText("导入格式"), "numbered");
  await user.click(screen.getByRole("button", {name: "预览导入"}));
  await screen.findByLabelText("导入行 1 对应源行");
  expect((await screen.findByRole("option", {name: /已锁定/}) as HTMLOptionElement).disabled).toBe(true);
  expect((screen.getByRole("option", {name: /已确认/}) as HTMLOptionElement).disabled).toBe(true);
  expect((screen.getByRole("button", {name: "应用目标译文导入"}) as HTMLButtonElement).disabled).toBe(true);
  await user.type(content, " changed");
  expect(screen.queryByRole("button", {name: "应用目标译文导入"})).toBeNull();
  expect(applyCalls).toBe(0);
});
it("blocks source paging and merging a dirty next row until explicit discard", async () => {
  const {default: SourceAuthoringSection} = await import("./SourceAuthoringSection");
  const user = userEvent.setup();
  vi.spyOn(globalThis, "fetch").mockResolvedValue(ok({source: {revision: 2, start_ms: 0, end_ms: 10000, stale: false}, transcript: {id: "transcript-a", stale: false}, segments: [row, {...row, id: "s2", text: "Next words"}], total: 51, cast: []}));
  render(<SourceAuthoringSection projectId="p" csrf="csrf" refreshVersion={0} onSaved={vi.fn()} />);
  await user.click(screen.getByRole("button", {name: "编辑或导入源字幕"}));
  await user.type(await screen.findByLabelText("源文字 第 2 行"), " draft");
  expect((screen.getByRole("button", {name: "下一页源文字"}) as HTMLButtonElement).disabled).toBe(true);
  expect((screen.getByRole("button", {name: "与下一源行合并"}) as HTMLButtonElement).disabled).toBe(true);
  await user.click(screen.getByRole("button", {name: "放弃源第 2 行修改"}));
  await user.click(screen.getByRole("button", {name: "与下一源行合并"}));
  expect((screen.getByRole("button", {name: "下一页源文字"}) as HTMLButtonElement).disabled).toBe(true);
  expect((screen.getByLabelText("源文字 第 2 行") as HTMLTextAreaElement).disabled).toBe(true);
  await user.click(screen.getByRole("button", {name: "放弃结构修改"}));
  expect((screen.getByRole("button", {name: "下一页源文字"}) as HTMLButtonElement).disabled).toBe(false);
});
