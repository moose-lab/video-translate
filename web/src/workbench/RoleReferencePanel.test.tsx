import {afterEach, expect, it, vi} from "vitest";
import {cleanup, render, screen, waitFor} from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import RoleReferencePanel from "./RoleReferencePanel";
import RoleEditor from "./RoleEditor";
import SourceRoleAssignment from "./SourceRoleAssignment";
import ReferenceExtractForm from "./ReferenceExtractForm";
import ReferenceBindingEditor from "./ReferenceBindingEditor";
import type {Timeline} from "./types";
import type {ReferenceVersion, Speaker} from "./referenceTypes";
// Contract doubles only. Source dialogue and reference audio facts below do not represent media generation.
const role: Speaker = {id: "role", selection_id: "selection", name: "讲解者", description: "", revision: 2, archived: false};
const row = {id: "row", revision: 3, revision_id: "row-revision", text: "Exact saved source", start_ms: 1000, end_ms: 2500, absolute_start_ms: 6000, absolute_end_ms: 7500, speaker_id: "role", original_speaker_label: "S0"};
const timeline = {editor_fingerprint: "head", project_revision: 1, source: {id: "selection", revision: 2, stale: false, source_asset_id: "asset", start_ms: 5000, end_ms: 10000, track: {audio_ordinal: 0, stream_index: 1, codec: "aac", language: "en", channels: 2, sample_rate: 48000}}, transcript: {id: "transcript", stale: false, provenance: "contract-double"}, cast: [role], cast_total: 1, segments: [row], total: 1} as Timeline;
const reference: ReferenceVersion = {id: "ref-a", reference_id: "reference", audio_asset_id: "audio", text: "Reference words", language: "en", duration_ms: 1500, flags: ["short", "overlap"], stale: false, origin: "source", source_segment_id: "row", absolute_start_ms: 6000, absolute_end_ms: 7500};
const source = {selection_revision: 2, transcript_revision: "transcript"};
const ok = (value: unknown, status = 200) => new Response(JSON.stringify(value), {status});
afterEach(() => {cleanup(); vi.restoreAllMocks();});
it("reads real-shaped roles/source/reference facts without writes, then creates and edits a role explicitly", async () => {
  const user = userEvent.setup(); const writes: {path: string; body: unknown}[] = [];
  vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
    const path = String(input);
    if (init?.method) {writes.push({path, body: JSON.parse(String(init.body))}); return ok(role);}
    if (path.includes("/speakers?")) return ok({items: [role], total: 1});
    if (path.includes("/references?")) return ok({items: [reference], total: 1});
    if (path.includes("/timeline?")) return ok(timeline);
    throw new Error(path);
  });
  render(<RoleReferencePanel projectId="p" csrf="csrf" sourceLanguage="en" refreshVersion={0} onChanged={vi.fn()} />);
  expect(await screen.findByText(/实测 1.500 秒/)).toBeTruthy();
  expect(screen.getByText(/参考音较短.*含重叠说话/)).toBeTruthy();
  expect(writes).toHaveLength(0);
  await user.type(screen.getByLabelText("新角色名称"), "第二角色");
  await user.click(screen.getByRole("button", {name: "创建角色"}));
  await waitFor(() => expect(writes[0]).toEqual({path: "/api/projects/p/speakers", body: {name: "第二角色", description: ""}}));
  const input = screen.getByLabelText("角色名称 讲解者"); await user.clear(input); await user.type(input, "新名称");
  await user.click(screen.getByRole("button", {name: "保存角色 讲解者"}));
  await waitFor(() => expect(writes[1]).toEqual({path: "/api/projects/p/speakers/role", body: {revision: 2, name: "新名称", description: ""}}));
});
it("pins source role assignment to its original source and row revision across live updates", async () => {
  const user = userEvent.setup(); let sent: unknown;
  vi.spyOn(globalThis, "fetch").mockImplementation(async (_input, init) => {sent = JSON.parse(String(init?.body)); return ok({error: {code: "REVISION_CONFLICT"}}, 409);});
  const props = {projectId: "p", csrf: "csrf", source, row, index: 1, roles: [role, {...role, id: "other", name: "第二角色"}], onChanged: vi.fn()};
  const view = render(<SourceRoleAssignment {...props} />);
  await userEvent.selectOptions(screen.getByLabelText("第 1 行角色"), "other");
  view.rerender(<SourceRoleAssignment {...props} source={{selection_revision: 9, transcript_revision: "new-transcript"}} row={{...row, revision: 8}} />);
  await user.click(screen.getByRole("button", {name: "保存第 1 行角色"}));
  await waitFor(() => expect(sent).toEqual({selection_revision: 2, transcript_revision: "transcript", revision: 3, speaker_id: "other"}));
  expect(await screen.findByText(/REVISION_CONFLICT/)).toBeTruthy();
  expect((screen.getByLabelText("第 1 行角色") as HTMLSelectElement).value).toBe("other");
});
it("extracts only the saved row's exact source snapshot after a click and reports pending measurement truthfully", async () => {
  const user = userEvent.setup(); let sent: unknown;
  vi.spyOn(globalThis, "fetch").mockImplementation(async (_input, init) => {sent = JSON.parse(String(init?.body)); return ok({run: {id: "reference-run", status: "queued"}, reference: null}, 202);});
  const props = {projectId: "p", csrf: "csrf", source, row, index: 1, sourceLanguage: "en", onChanged: vi.fn()};
  const view = render(<ReferenceExtractForm {...props} />);
  expect(screen.getByDisplayValue("Exact saved source")).toBeTruthy();
  expect(screen.getByText(/原片 6.000–7.500 秒/)).toBeTruthy();
  view.rerender(<ReferenceExtractForm {...props} source={{selection_revision: 9, transcript_revision: "new-transcript"}} row={{...row, revision: 8, text: "New source"}} />);
  expect(sent).toBeUndefined();
  await user.click(screen.getByRole("button", {name: "提取第 1 行参考音"}));
  await waitFor(() => expect(sent).toEqual({selection_revision: 2, transcript_revision: "transcript", segment_id: "row", segment_revision: 3, speaker_id: "role", text: "Exact saved source", language: "en", media: "source"}));
  expect(await screen.findByText(/实际时长与质量需等待提取完成/)).toBeTruthy();
});
it("pins a line override to loaded binding/source/subject revisions and allows explicit role inheritance", async () => {
  const user = userEvent.setup(); const writes: unknown[] = []; let bindingRevision = 4;
  vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
    if (init?.method) {writes.push(JSON.parse(String(init.body))); return writes.length === 1 ? ok({error: {code: "REVISION_CONFLICT"}}, 409) : ok({revision: 9, reference_version_id: null});}
    return String(input).includes("/speakers/") ? ok({revision: 1, reference_version_id: "ref-b"}) : ok({revision: bindingRevision, reference_version_id: "ref-a"});
  });
  const props = {projectId: "p", csrf: "csrf", source, kind: "line" as const, subjectId: "row", subjectRevision: 3, speakerId: "role", references: [reference, {...reference, id: "ref-b"}, {...reference, id: "ref-c"}], refreshVersion: 0, onChanged: vi.fn()};
  const view = render(<ReferenceBindingEditor {...props} />);
  await user.selectOptions(await screen.findByLabelText("行参考音版本"), "ref-c");
  bindingRevision = 8;
  view.rerender(<ReferenceBindingEditor {...props} source={{selection_revision: 9, transcript_revision: "new-transcript"}} subjectRevision={7} refreshVersion={1} />);
  await user.click(screen.getByRole("button", {name: "保存行参考音"}));
  await waitFor(() => expect(writes[0]).toEqual({selection_revision: 2, transcript_revision: "transcript", revision: 4, expected_segment_revision: 3, reference_version_id: "ref-c"}));
  expect(await screen.findByText(/REVISION_CONFLICT/)).toBeTruthy();
  await user.click(screen.getByRole("button", {name: "放弃参考音修改"}));
  await user.click(screen.getByRole("button", {name: "改用角色默认参考音"}));
  await waitFor(() => expect(writes[1]).toEqual({selection_revision: 9, transcript_revision: "new-transcript", revision: 8, expected_segment_revision: 7, reference_version_id: null}));
});
it("keeps a role rename on its original revision after a live update", async () => {
  const user = userEvent.setup(); let sent: unknown;
  vi.spyOn(globalThis, "fetch").mockImplementation(async (_input, init) => {sent = JSON.parse(String(init?.body)); return ok({error: {code: "REVISION_CONFLICT"}}, 409);});
  const props = {projectId: "p", csrf: "csrf", role, source, references: [reference], refreshVersion: 0, onChanged: vi.fn()};
  const view = render(<RoleEditor {...props} />);
  const name = screen.getByLabelText("角色名称 讲解者"); await user.clear(name); await user.type(name, "草稿名称");
  view.rerender(<RoleEditor {...props} role={{...role, revision: 9}} refreshVersion={1} />);
  await user.click(screen.getByRole("button", {name: "保存角色 讲解者"}));
  await waitFor(() => expect(sent).toEqual({revision: 2, name: "草稿名称", description: ""}));
  expect(await screen.findByText(/REVISION_CONFLICT/)).toBeTruthy();
  expect((name as HTMLInputElement).value).toBe("草稿名称");
});
it("archives a role only through an explicit revision-guarded action", async () => {
  const user = userEvent.setup(); let sent: unknown;
  const fetch = vi.spyOn(globalThis, "fetch").mockImplementation(async (_input, init) => {sent = JSON.parse(String(init?.body)); return ok({...role, archived: true, revision: 3});});
  render(<RoleEditor projectId="p" csrf="csrf" role={role} source={source} references={[]} refreshVersion={0} onChanged={vi.fn()} />);
  expect(fetch).not.toHaveBeenCalled();
  await user.click(screen.getByRole("button", {name: "归档角色 讲解者"}));
  await waitFor(() => expect(sent).toEqual({revision: 2, archived: true}));
});
