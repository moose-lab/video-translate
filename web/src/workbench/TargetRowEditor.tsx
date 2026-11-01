import {api} from "../api/client";
import type {Segment, Timeline} from "./types";
import {seconds} from "./types";
import {rowGuard, type TargetDraft, targetPath} from "./targetTypes";
import {useAction} from "./useAction";
type Props = {projectId: string; tag: string; timeline: Timeline; row: Segment; index: number; csrf: string; draft?: TargetDraft; onDraft: (draft: TargetDraft | undefined) => void; onSaved: () => void};
export default function TargetRowEditor({projectId, tag, timeline, row, index, csrf, draft, onDraft, onSaved}: Props) {
  const guard = rowGuard(timeline, row), translation = row.translation, {busy, error, perform} = useAction();
  const values = draft ?? {text: translation?.text ?? "", locked: translation?.locked ?? false};
  const staleDraft = draft && guard && (draft.selection_revision !== guard.selection_revision || draft.transcript_revision !== guard.transcript_revision || draft.expected_source_text_fingerprint !== guard.expected_source_text_fingerprint || draft.revision !== guard.revision);
  function edit(change: {text?: string; locked?: boolean}) {if (guard) onDraft({...guard, approved: false, ...values, ...draft, ...change});}
  async function save() {
    if (!draft || !draft.text.trim()) return;
    const result = await perform(signal => api(`${targetPath(projectId, tag)}/segments/${encodeURIComponent(row.id)}`, {method: "PATCH", signal, body: JSON.stringify(draft)}, csrf));
    if (result) {onDraft(undefined); onSaved();}
  }
  async function approve() {
    if (!guard || draft || !translation || translation.stale) return;
    const {selection_revision, transcript_revision, ...rowRevision} = guard;
    const result = await perform(signal => api(`${targetPath(projectId, tag)}/approve`, {method: "POST", signal, body: JSON.stringify({selection_revision, transcript_revision, segments: [{id: row.id, ...rowRevision}]})}, csrf));
    if (result) onSaved();
  }
  return <li className="target-row"><div className="transcript-meta"><span>第 {index} 行 · {seconds(row.absolute_start_ms)}–{seconds(row.absolute_end_ms)} 秒</span><span>{translation?.stale ? "译文已过期" : translation?.approved ? "译文已确认" : translation ? "译文待确认" : "尚无译文"}{translation?.locked ? " · 已锁定" : ""}</span></div>
    <div className="translation-columns"><div><span className="field-caption">源文字</span><p dir="auto">{row.text}</p></div><div><label className="field-caption">目标文字 第 {index} 行<textarea dir="auto" rows={3} maxLength={20000} value={values.text} disabled={!guard || busy} onChange={event => edit({text: event.target.value})} /></label></div></div>
    <label className="check-label"><input type="checkbox" aria-label={`锁定第 ${index} 行`} checked={values.locked} disabled={!guard || busy} onChange={event => edit({locked: event.target.checked})} />锁定此行，自动翻译时保留</label>
    {staleDraft && <p className="error">源版本已变化，或服务器译文已更新。当前修改仍保留；保存发生冲突时请核对后放弃或重新编辑。</p>}
    {draft && <p className="muted">修改尚未保存，保存后需要重新确认译文。</p>}
    <div className="actions"><button className="secondary" disabled={!draft || !draft.text.trim() || busy} onClick={() => void save()}>保存第 {index} 行</button>{draft && <button className="link" disabled={busy} onClick={() => onDraft(undefined)}>放弃第 {index} 行修改</button>}<button className="secondary" disabled={!!draft || !guard || !translation || translation.stale || translation.approved || busy} onClick={() => void approve()}>确认第 {index} 行译文</button></div>
    {error && <p className="error" role="alert">{error}</p>}
  </li>;
}
