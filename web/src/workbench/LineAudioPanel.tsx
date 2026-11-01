import {useState} from "react";
import {api} from "../api/client";
import type {AudioLine} from "./audioTypes";
import type {Segment, Run} from "./types";
import {seconds} from "./types";
import {targetPath, type SourceGuard} from "./targetTypes";
import {useAction} from "./useAction";
import {AudioAssessment} from "./AudioAssessment";
import AudioHistoryPanel from "./AudioHistoryPanel";
import VoiceQCDetails from "./VoiceQCDetails";
export type LineAudioProps = {projectId: string; tag: string; row: Segment; index: number; source: SourceGuard; line: AudioLine; csrf: string; refresh: () => void; dirty: boolean; runs: Run[]};
type Choices = {key: string; translation: boolean; reference: boolean; replace: boolean; regenerate: boolean};
const warningName = (value: string) => ({short: "参考音较短", long: "参考音较长", overlap: "含重叠说话", silence: "含较多静音"}[value] ?? "参考音需要检查");
export default function LineAudioPanel({projectId, tag, row, index, source, line, csrf, refresh, dirty, runs}: LineAudioProps) {
  const [open, setOpen] = useState(false), [history, setHistory] = useState(false), [qcDetails, setQCDetails] = useState(false), [playbackError, setPlaybackError] = useState(false);
  const [choices, setChoices] = useState<Choices | null>(null), [listened, setListened] = useState(""), [reviewed, setReviewed] = useState(""), [notice, setNotice] = useState("");
  const {busy, error, perform} = useAction(), selected = line.selected, translation = row.translation, reference = line.reference_review;
  const path = targetPath(projectId, tag);
  const snapshot = JSON.stringify([source, row.source_text_fingerprint, translation?.revision, line.selection_revision, reference?.version_id, reference?.warnings]);
  const choice = choices?.key === snapshot ? choices : {key: snapshot, translation: false, reference: false, replace: false, regenerate: false};
  const reviewKey = JSON.stringify([snapshot, selected?.id, selected?.review_revision, selected?.qc_evidence_fingerprint]);
  const base = {...source, id: row.id, translation_revision: translation?.revision ?? 0, expected_source_text_fingerprint: row.source_text_fingerprint};
  const uncertain = runs.some(run => run.target_language === tag && run.segment_id === row.id && ["synthesize", "voice_qc"].includes(run.stage) && (run.safe_error?.code === "SUBMISSION_UNCERTAIN" || run.remote_state === "submitting"));
  const outstanding = line.outstanding.some(work => ["queued", "running", "retry_wait", "cancelling", "needs_review"].includes(work.status));
  const valid = !!translation && !translation.stale && translation.source_text_fingerprint === row.source_text_fingerprint && !dirty;
  const canGenerate = valid && !!reference && !uncertain && !outstanding && !error.includes("SUBMISSION_UNCERTAIN") && (translation.approved || choice.translation) && (!reference.acknowledgement_required || choice.reference) && (!selected || choice.replace);
  const canReview = valid && selected && !selected.stale && selected.evidence_status === "validated" && listened === reviewKey && reviewed === reviewKey;
  function change(key: "translation" | "reference" | "replace" | "regenerate", checked: boolean) {setChoices({...choice, [key]: checked});}
  async function generate() {
    if (!canGenerate || !translation) return;
    const segment = {id: row.id, translation_revision: translation.revision, expected_source_text_fingerprint: row.source_text_fingerprint, selection_revision: line.selection_revision, ...(!translation.approved ? {review_translation_revision: translation.revision} : {}), ...(reference?.acknowledgement_required ? {review_reference_version_id: reference.version_id} : {})};
    const result = await perform(signal => api(`${path}/synthesize`, {method: "POST", signal, body: JSON.stringify({...source, segments: [segment], replace_selected: choice.replace, regenerate: choice.regenerate})}, csrf));
    if (result) {setNotice("配音请求已提交，请查看任务状态；生成结果需要质检与人工试听。"); refresh();}
  }
  async function qc() {
    if (!selected || !valid || selected.stale) return;
    const {id, translation_revision, expected_source_text_fingerprint} = base;
    const result = await perform(signal => api(`${path}/voice-qc`, {method: "POST", signal, body: JSON.stringify({...source, segments: [{id, translation_revision, expected_source_text_fingerprint, selection_revision: line.selection_revision, output_id: selected.id}]})}, csrf));
    if (result) {setNotice("独立语音检查请求已提交；识别完成后仍需人工试听。"); refresh();}
  }
  async function review(decision: "accepted" | "rejected") {
    if (!selected || !canReview) return;
    const result = await perform(signal => api(`${path}/segments/${encodeURIComponent(row.id)}/audio-review`, {method: "PUT", signal, body: JSON.stringify({...source, revision: selected.review_revision, translation_revision: translation!.revision, expected_source_text_fingerprint: row.source_text_fingerprint, output_id: selected.id, audio_selection_revision: line.selection_revision, qc_evidence_fingerprint: selected.qc_evidence_fingerprint, decision, note: ""})}, csrf));
    if (result) {setNotice("听审记录已保存，以服务器最新状态为准。"); setReviewed(""); refresh();}
  }
  return <div className="line-audio"><button className="link" aria-expanded={open} onClick={() => setOpen(!open)}>配音与试听 第 {index} 行 · {selected ? selected.ready ? "已审核" : "待检查" : "尚无音频"}</button>
    {open && <div><p className="muted">自然配音使用当前行或角色参考音；生成、质检和人工接受分别执行。<a href="#/services">服务配置</a></p>
      {dirty && <p className="error">请先保存或放弃此行译文修改。</p>}
      {reference ? <p className="muted">当前参考音实测 {seconds(reference.duration_ms)} 秒{reference.warnings.length ? ` · ${reference.warnings.map(warningName).join("、")}` : ""}</p> : <p className="error">此行尚无可用参考音，或参考音已过期；需要先配置行或角色参考音。</p>}
      {!translation?.approved && <label className="check-label"><input type="checkbox" checked={choice.translation} disabled={!valid || busy} onChange={event => change("translation", event.target.checked)} />我已核对当前第 {index} 行译文，允许本次生成</label>}
      {reference?.acknowledgement_required && <label className="check-label"><input type="checkbox" checked={choice.reference} disabled={busy} onChange={event => change("reference", event.target.checked)} />我已检查当前参考音及其风险，允许本次生成</label>}
      {selected && <label className="check-label"><input type="checkbox" checked={choice.replace} disabled={busy} onChange={event => change("replace", event.target.checked)} />允许替换当前选中音频</label>}
      <label className="check-label"><input type="checkbox" checked={choice.regenerate} disabled={busy} onChange={event => change("regenerate", event.target.checked)} />重新生成，不复用历史自然音频</label>
      <button className="secondary" disabled={busy || !canGenerate} onClick={() => void generate()}>生成第 {index} 行配音</button>
      {(uncertain || outstanding) && <p className="error">此行已有待处理或结果未知的配音任务，请先在任务区核查并恢复。</p>}
      {selected && <div className="selected-audio"><AudioAssessment output={selected} /><audio key={selected.id} controls preload="none" aria-label={`第 ${index} 行自然配音`} src={`/api/assets/${encodeURIComponent(selected.audio_asset_id)}/content`} onEnded={() => setListened(reviewKey)} onLoadedData={() => setPlaybackError(false)} onError={() => setPlaybackError(true)} />{playbackError && <p className="error" role="alert">当前浏览器无法播放此音频，或会话已失效。请检查文件与连接后重试。</p>}
        <div className="actions"><button className="secondary" disabled={busy || !valid || selected.stale || uncertain || ["queued", "running", "retry_wait"].includes(selected.qc.status)} onClick={() => void qc()}>检查第 {index} 行语音</button>{selected.qc.request_id && <button className="link" onClick={() => setQCDetails(!qcDetails)} aria-expanded={qcDetails}>查看识别对照</button>}</div>
        {qcDetails && selected.qc.request_id && <VoiceQCDetails projectId={projectId} tag={tag} requestId={selected.qc.request_id} segmentId={row.id} evidenceKey={JSON.stringify([selected.qc.status, selected.qc_evidence_fingerprint])} />}
        <p className="muted">完整播放此版本后，再确认听审。质检文字匹配不代表声音自然或角色一致。</p>
        <label className="check-label"><input type="checkbox" checked={reviewed === reviewKey} disabled={busy || listened !== reviewKey || !valid || selected.stale} onChange={event => setReviewed(event.target.checked ? reviewKey : "")} />我已试听此音频并核对质检风险</label>
        <div className="actions"><button className="secondary" disabled={busy || !canReview} onClick={() => void review("accepted")}>接受第 {index} 行配音</button><button className="secondary" disabled={busy || !canReview} onClick={() => void review("rejected")}>拒绝第 {index} 行配音</button></div>
      </div>}
      <button className="link" aria-expanded={history} onClick={() => setHistory(!history)}>查看第 {index} 行音频历史</button>{history && <AudioHistoryPanel projectId={projectId} tag={tag} row={row} source={source} csrf={csrf} refresh={refresh} />}
      {notice && <p className="notice" role="status">{notice}</p>}{error && <p className="error" role="alert">{error}</p>}
    </div>}
  </div>;
}
