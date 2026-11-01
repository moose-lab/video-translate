import {useEffect, useState} from "react";
import {api, ApiError} from "../api/client";
import {projectPath} from "../api/projects";
import type {SourceGuard} from "./targetTypes";
import {seconds} from "./types";
import type {ReferenceBinding, ReferenceVersion} from "./referenceTypes";
import {useAction} from "./useAction";
type Props = {projectId: string; csrf: string; source: SourceGuard; kind: "line" | "role"; subjectId: string; subjectRevision: number; speakerId?: string | null; references: ReferenceVersion[]; refreshVersion: number; onChanged: () => void};
type Draft = SourceGuard & {revision: number; reference_version_id: string | null; expected_segment_revision?: number; expected_speaker_revision?: number};
export default function ReferenceBindingEditor({projectId, csrf, source, kind, subjectId, subjectRevision, speakerId, references, refreshVersion, onChanged}: Props) {
  const [binding, setBinding] = useState<ReferenceBinding | null>(null), [inherited, setInherited] = useState<ReferenceBinding | null>(null), [loadError, setLoadError] = useState(""), [draft, setDraft] = useState<Draft | null>(null);
  const {busy, error, perform} = useAction(), label = kind === "line" ? "行" : "角色", path = `${projectPath(projectId)}/${kind === "line" ? "segments" : "speakers"}/${encodeURIComponent(subjectId)}/reference`;
  useEffect(() => {
    let active = true; const controller = new AbortController();
    Promise.all([api<ReferenceBinding>(`${path}?limit=1&offset=0`, {signal: controller.signal}), kind === "line" && speakerId ? api<ReferenceBinding>(`${projectPath(projectId)}/speakers/${encodeURIComponent(speakerId)}/reference?limit=1&offset=0`, {signal: controller.signal}) : Promise.resolve(null)]).then(([binding, inherited]) => {if (active) {setBinding(binding); setInherited(inherited); setLoadError("");}}).catch(error => {if (active) setLoadError(error instanceof ApiError ? error.message : "参考音绑定读取失败。");});
    return () => {active = false; controller.abort();};
  }, [path, speakerId, refreshVersion, source.selection_revision, source.transcript_revision]);
  function body(referenceId: string | null): Draft {return {...source, revision: binding!.revision, reference_version_id: referenceId, ...(kind === "line" ? {expected_segment_revision: subjectRevision} : {expected_speaker_revision: subjectRevision})};}
  async function save(value: Draft) {const result = await perform(signal => api<ReferenceBinding>(path, {method: "PUT", signal, body: JSON.stringify(value)}, csrf)); if (result) {setBinding(result); setDraft(null); onChanged();}}
  const value = draft ? draft.reference_version_id ?? "" : binding?.reference_version_id ?? "";
  const effectiveId = binding?.reference_version_id ?? inherited?.reference_version_id, effective = references.find(reference => reference.id === effectiveId);
  return <div className="reference-binding"><h4>{label}参考音</h4>{loadError && <p className="error" role="alert">{loadError}</p>}{!binding ? !loadError && <p role="status">正在读取参考音绑定…</p> : <>
    <p className="muted">{binding.reference_version_id ? kind === "line" ? "当前使用本行独立参考音" : "当前使用角色默认参考音" : inherited?.reference_version_id ? "当前继承角色默认参考音" : "当前没有可用参考音绑定"}{effective?.stale ? " · 当前参考版本已过期，不会自动换用其他版本" : ""}{effectiveId && !effective ? " · 当前版本不在参考库本页，请翻页查找" : ""}</p>
    <label>{label}参考音版本<select value={value} disabled={busy} onChange={event => setDraft(previous => ({...(previous ?? body(event.target.value || null)), reference_version_id: event.target.value || null}))}><option value="">{kind === "line" ? "继承角色默认参考音" : "不绑定角色默认参考音"}</option>{value && !references.some(reference => reference.id === value) && <option value={value}>当前绑定版本（其他页）</option>}{references.map(reference => <option key={reference.id} value={reference.id} disabled={reference.stale}>{reference.text.slice(0, 50)} · {reference.language} · {seconds(reference.duration_ms)} 秒{reference.stale ? " · 已过期" : ""}</option>)}</select></label>
    <div className="actions"><button className="secondary" disabled={busy || !draft} onClick={() => draft && void save(draft)}>保存{label}参考音</button>{draft && <button className="link" disabled={busy} onClick={() => setDraft(null)}>放弃参考音修改</button>}{binding.reference_version_id && <button className="link" disabled={busy || !!draft} onClick={() => void save(body(null))}>{kind === "line" ? "改用角色默认参考音" : "移除角色默认参考音"}</button>}</div>
  </>}{error && <p className="error" role="alert">{error}</p>}</div>;
}
