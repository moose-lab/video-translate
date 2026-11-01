import {useEffect, useState} from "react";
import {api, ApiError} from "../api/client";
import {projectPath} from "../api/projects";
import type {Timeline, Segment} from "./types";
import {seconds} from "./types";
import {targetPath} from "./targetTypes";
import type {CueMapping, ImportFormat, ImportGuard, ImportReview} from "./importTypes";
import {useAction} from "./useAction";
type RequestBody = ImportGuard & {format: ImportFormat; content: string};
type TargetMap = CueMapping & {protected: boolean; label: string};
type Props = {projectId: string; csrf: string; guard: ImportGuard; tag?: string; roles: {id: string; name: string; archived?: boolean}[]; onSaved: () => void; onDirty?: (value: boolean) => void};
const cueError = (code: string) => ({INVALID_TIMING: "时间范围无效", OUTSIDE_WINDOW: "超出已选源片段", EMPTY_TEXT: "文字为空"}[code] ?? "字幕内容需要检查");
export default function SubtitleImportPanel({projectId, csrf, guard, tag, roles, onSaved, onDirty}: Props) {
  const [draft, setDraft] = useState<RequestBody | null>(null), [review, setReview] = useState<{data: ImportReview; request: RequestBody; path: string} | null>(null), [mapping, setMapping] = useState<Record<string, TargetMap | CueMapping>>({}), [offset, setOffset] = useState(0), [notice, setNotice] = useState("");
  const [lookup, setLookup] = useState<{rows: Segment[]; total: number; offset: number}>({rows: [], total: 0, offset: 0}), [lookupOffset, setLookupOffset] = useState(0), [lookupError, setLookupError] = useState(""), [lookupLoading, setLookupLoading] = useState(false);
  const {busy, error, perform} = useAction(), values = draft ?? {...guard, format: "srt" as const, content: ""}, path = tag ? `${targetPath(projectId, tag)}/import` : `${projectPath(projectId)}/source/import`;
  useEffect(() => {onDirty?.(!!draft && !notice);}, [draft, notice, onDirty]);
  function edit(change: Partial<Pick<RequestBody, "format" | "content">>) {setDraft(previous => ({...(previous ?? {...guard, format: "srt", content: ""}), ...change})); setReview(null); setMapping({}); setNotice(""); setOffset(0);}
  async function preview() {
    const request = {...values};
    const result = await perform(signal => api<ImportReview>(`${path}/preview`, {method: "POST", signal, body: JSON.stringify(request)}, csrf));
    if (result) {setReview({data: result, request, path}); setOffset(0); setLookupOffset(0); setNotice(""); setMapping(tag ? {} : Object.fromEntries(result.cues.map(cue => [cue.id, {cue_id: cue.id, segment_id: null, revision: 0, speaker_id: null, use_voice_label: false}])));}
  }
  useEffect(() => {
    if (!review || !tag) return;
    let active = true; const controller = new AbortController(); setLookupLoading(true); setLookupError("");
    const params = new URLSearchParams({target_language: tag, limit: "100", offset: String(lookupOffset)});
    api<Timeline>(`${projectPath(projectId)}/timeline?${params}`, {signal: controller.signal}).then(page => {if (active) setLookup({rows: page.segments, total: page.total, offset: lookupOffset});}).catch(error => {if (active) setLookupError(error instanceof ApiError ? error.message : "源行映射列表读取失败。");}).finally(() => {if (active) setLookupLoading(false);});
    return () => {active = false; controller.abort();};
  }, [projectId, tag, review, lookupOffset]);
  const complete = review && review.data.cues.every(cue => !cue.errors.length && !!mapping[cue.id] && (!tag || (!!mapping[cue.id].segment_id && !(mapping[cue.id] as TargetMap).protected)));
  const mappedIds = review?.data.cues.flatMap(cue => mapping[cue.id]?.segment_id ? [mapping[cue.id].segment_id] : []) ?? [];
  const unique = !tag || new Set(mappedIds).size === mappedIds.length;
  async function apply() {
    if (!review || !complete || !unique) return;
    const bodyMapping = review.data.cues.map(cue => {const {protected: _protected, label: _label, ...value} = mapping[cue.id] as TargetMap; return value;});
    const result = await perform(signal => api<{count: number}>(`${review.path}/apply`, {method: "POST", signal, body: JSON.stringify({...review.request, digest: review.data.digest, mapping: bodyMapping, mode: tag ? "replace_current" : "new_transcript", force_locked: false})}, csrf));
    if (result) {setNotice(`手动导入已应用 ${result.count} 行；来源会记录为导入，仍需人工核对。`); setReview(null); onSaved();}
  }
  function targetChoice(cueId: string, id: string) {
    if (!id) {setMapping(previous => {const next = {...previous}; delete next[cueId]; return next;}); return;}
    const row = lookup.rows.find(row => row.id === id); if (!row) return;
    setMapping(previous => ({...previous, [cueId]: {cue_id: cueId, segment_id: row.id, revision: row.translation?.revision ?? 0, protected: !!row.translation?.locked || !!row.translation?.approved, label: `源第 ${lookup.offset + lookup.rows.indexOf(row) + 1} 行 · ${row.text.slice(0, 50)}`}}));
  }
  return <div className="subtitle-import"><h3>{tag ? "手动导入目标译文" : "手动导入源字幕"}</h3><p className="muted">{tag ? "每条字幕都必须明确映射到源行；已锁定或已确认的译文默认保留。" : "仅支持带时间的 SRT/VTT。应用会创建新的活动源字幕版本，旧版本保留；已有译文与配音可能过期。这不会进行自动语音识别。"}</p>
    <label>导入格式<select value={values.format} disabled={busy} onChange={event => edit({format: event.target.value as ImportFormat})}><option value="srt">SRT</option><option value="vtt">WebVTT</option>{tag && <option value="numbered">编号文本（1. 译文）</option>}</select></label><label>导入字幕内容<textarea dir="auto" rows={6} maxLength={262144} disabled={busy} value={values.content} onChange={event => edit({content: event.target.value})} /></label>
    <div className="actions"><button className="secondary" disabled={busy || !values.content.trim() || new TextEncoder().encode(values.content).length > 262144} onClick={() => void preview()}>预览导入</button>{draft && <button className="link" disabled={busy} onClick={() => {setDraft(null); setReview(null); setMapping({}); setNotice("");}}>清空导入草稿</button>}</div>
    {review && <div className="import-review"><h4>导入预览 · 共 {review.data.cues.length} 行</h4><p className="muted">时间相对已选源片段；将应用全部预览行，不限于当前显示页。</p>
      {tag && <><p className="muted">源行选择页 {lookup.offset + 1}–{Math.min(lookup.offset + 100, lookup.total)} / {lookup.total}。已锁定或已确认行不可选；需先调整保护状态后重新预览。</p>{lookupLoading && <p role="status">正在读取源行映射…</p>}{lookupError && <p role="alert" className="error">{lookupError}</p>}{lookup.total > 100 && <nav className="actions pagination" aria-label="导入源行查找分页"><button className="secondary" disabled={!lookupOffset || lookupLoading} onClick={() => setLookupOffset(Math.max(0, lookupOffset - 100))}>上一页映射源行</button><button className="secondary" disabled={lookupOffset + 100 >= lookup.total || lookupLoading} onClick={() => setLookupOffset(lookupOffset + 100)}>下一页映射源行</button></nav>}</>}
      <ol start={offset + 1} className="import-cues">{review.data.cues.slice(offset, offset + 50).map((cue, index) => <li key={cue.id}><p dir="auto">{cue.text}</p>{cue.start_ms !== null && cue.end_ms !== null && <p className="muted">{seconds(cue.start_ms)}–{seconds(cue.end_ms)} 秒</p>}{cue.errors.length > 0 && <p className="error">{cue.errors.map(cueError).join("、")}</p>}{cue.warnings.length > 0 && <p className="error">说话标签有歧义，请明确选择角色。</p>}
        {tag ? <><label>导入行 {offset + index + 1} 对应源行<select value={mapping[cue.id]?.segment_id ?? ""} disabled={busy || lookupLoading} onChange={event => targetChoice(cue.id, event.target.value)}><option value="">请选择源行（不会自动映射）</option>{mapping[cue.id]?.segment_id && !lookup.rows.some(row => row.id === mapping[cue.id].segment_id) && <option value={mapping[cue.id].segment_id!}>{(mapping[cue.id] as TargetMap).label}</option>}{lookup.rows.map((row, rowIndex) => <option key={row.id} value={row.id} disabled={!!row.translation?.locked || !!row.translation?.approved}>源第 {lookup.offset + rowIndex + 1} 行 · {row.text.slice(0, 50)}{row.translation?.locked ? " · 已锁定" : row.translation?.approved ? " · 已确认" : ""}</option>)}</select></label>{cue.proposed_matches.length > 0 && <p className="muted">预览建议源行：{cue.proposed_matches.map(match => match.source_number).join("、")}。请自行核对并选择。</p>}</> : <label>导入行 {offset + index + 1} 角色<select disabled={busy} value={mapping[cue.id]?.use_voice_label ? "voice-label" : mapping[cue.id]?.speaker_id ?? ""} onChange={event => setMapping(previous => ({...previous, [cue.id]: {cue_id: cue.id, segment_id: null, revision: 0, speaker_id: event.target.value && event.target.value !== "voice-label" ? event.target.value : null, use_voice_label: event.target.value === "voice-label"}}))}><option value="">未分配角色</option>{roles.filter(role => !role.archived).map(role => <option key={role.id} value={role.id}>{role.name}</option>)}{cue.voice_label && <option value="voice-label">按字幕标签创建角色：{cue.voice_label}</option>}</select></label>}
      </li>)}</ol>
      {review.data.cues.length > 50 && <nav className="actions pagination" aria-label="导入预览分页"><button className="secondary" disabled={!offset} onClick={() => setOffset(Math.max(0, offset - 50))}>上一页导入行</button><button className="secondary" disabled={offset + 50 >= review.data.cues.length} onClick={() => setOffset(offset + 50)}>下一页导入行</button></nav>}
      {!unique && <p className="error">每条导入字幕必须映射到不同源行。</p>}<button className="secondary" disabled={busy || !complete || !unique} onClick={() => void apply()}>{tag ? "应用目标译文导入" : "应用新源字幕版本"}</button>
    </div>}{notice && <p className="notice" role="status">{notice}</p>}{error && <p className="error" role="alert">{error}</p>}
  </div>;
}
