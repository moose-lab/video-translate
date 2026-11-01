import {useEffect, useRef, useState, type FormEvent} from "react";
import {api} from "../api/client";
import {projectPath, type Project} from "../api/projects";
import type {ProbeFacts, ProviderRequirements, Run, SourceSelection, SourceWorkflow, Timeline} from "./types";
import {seconds, stageName, statusName} from "./types";
import {useAction} from "./useAction";
import SourceMediaTools from "./SourceMediaTools";
import WaveformPanel from "./WaveformPanel";

type Props = {project: Project; timeline: Timeline; runs: Run[]; csrf: string; refresh: () => void; providers: ProviderRequirements | null; workflow: SourceWorkflow | null; onWorkflow: (value: SourceWorkflow) => void; refreshVersion?: number};
export default function SourcePanel({project, timeline, runs, csrf, refresh, providers, workflow, onWorkflow, refreshVersion = 0}: Props) {
  const path = projectPath(project.id), selection = timeline.source;
  const editableSelection = selection?.source_asset_id === project.source_asset_id ? selection : null;
  const [file, setFile] = useState<File | null>(null), [uploading, setUploading] = useState(false), [playbackError, setPlaybackError] = useState(false), [savedProbe, setSavedProbe] = useState<Run | null>(null);
  const [start, setStart] = useState(String(editableSelection?.start_ms ?? 0)), [end, setEnd] = useState(String(editableSelection?.end_ms ?? "")), [ordinal, setOrdinal] = useState(String(editableSelection?.track.audio_ordinal ?? 0)), [dirty, setDirty] = useState(false);
  const draftBase = useRef({revision: project.revision, sourceAssetId: project.source_asset_id});
  const {busy, error, perform} = useAction(), fileInput = useRef<HTMLInputElement>(null), video = useRef<HTMLVideoElement>(null);
  const probe = runs.find(run => run.stage === "probe" && run.status === "succeeded" && !run.is_stale) ?? savedProbe;
  const facts = probe?.result as ProbeFacts | null | undefined;
  const duration = facts?.duration_ms ?? editableSelection?.track.duration_ms;
  const audio = facts?.audio ?? (editableSelection ? [editableSelection.track] : []);
  useEffect(() => {
    const probeId = editableSelection?.track.probe_run_id;
    if (!probeId || runs.some(run => run.id === probeId)) return;
    let active = true; const controller = new AbortController();
    api<Run>(`/runs/${encodeURIComponent(probeId)}`, {signal: controller.signal}).then(run => {if (active && run.status === "succeeded" && !run.is_stale) setSavedProbe(run);}).catch(() => {});
    return () => {active = false; controller.abort();};
  }, [editableSelection?.track.probe_run_id, runs]);
  useEffect(() => {
    if (dirty) return;
    draftBase.current = {revision: project.revision, sourceAssetId: project.source_asset_id};
    setStart(String(editableSelection?.start_ms ?? 0)); setEnd(duration === undefined ? "" : String(editableSelection?.end_ms ?? duration)); setOrdinal(String(editableSelection?.track.audio_ordinal ?? audio[0]?.audio_ordinal ?? 0));
  }, [editableSelection?.id, duration, dirty, project.revision, project.source_asset_id]);
  const from = Number(start), to = Number(end), audioOrdinal = Number(ordinal);
  const valid = duration !== undefined && start !== "" && end !== "" && Number.isSafeInteger(from) && Number.isSafeInteger(to) && from >= 0 && from < to && to <= duration && audio.some(track => track.audio_ordinal === audioOrdinal);
  async function upload(event: FormEvent) {
    event.preventDefault(); if (!file) return;
    setUploading(true);
    const body = new FormData(); body.append("file", file);
    const result = await perform(signal => api<{project: Project}>(`${path}/source`, {method: "POST", body, signal}, csrf));
    setUploading(false);
    if (result) {setFile(null); if (fileInput.current) fileInput.current.value = ""; refresh();}
  }
  async function save(event: FormEvent) {
    event.preventDefault(); if (!valid) return;
    const result = await perform(signal => api<SourceSelection>(`${path}/source-selection`, {method: "PUT", signal, body: JSON.stringify({revision: draftBase.current.revision, source_asset_id: draftBase.current.sourceAssetId, audio_ordinal: audioOrdinal, start_ms: from, end_ms: to})}, csrf));
    if (result) {setDirty(false); refresh();}
  }
  async function analyse() {
    const result = await perform(signal => api<SourceWorkflow>(`${path}/workflow`, {method: "POST", signal, body: JSON.stringify({action: "analyse", expected_editor_fingerprint: timeline.editor_fingerprint, auto_advance: false})}, csrf));
    if (result) {onWorkflow(result); refresh();}
  }
  return <section className="panel" aria-labelledby="source-title">
    <div className="section-head"><h2 id="source-title">原片与源片段</h2>{selection && <span className="status">{selection.stale ? "选择已过期" : "已选择源片段"}</span>}</div>
    {project.source_asset_id && <><video ref={video} key={project.source_asset_id} aria-label="原片播放器" controls preload="metadata" src={`/api/assets/${encodeURIComponent(project.source_asset_id)}/content`} onError={() => setPlaybackError(true)} /><p className="muted">播放器播放上传原片；源分析使用下方选择的音轨与时间范围。</p></>}
    {playbackError && <p className="error" role="alert">浏览器无法播放此文件或当前会话已失效。请尝试 H.264/AAC 编码 MP4，或重新上传兼容视频。</p>}
    <form onSubmit={e => void upload(e)}><label>选择原片文件<input ref={fileInput} type="file" accept=".mp4,.m4v,.mov,.webm,.mkv,.avi" disabled={busy} onChange={e => setFile(e.target.files?.[0] ?? null)} /></label>
      {file && <p className="muted">{file.name} · {file.size.toLocaleString()} 字节{project.source_asset_id ? " · 上传将替换当前原片并使旧选择失效" : ""}</p>}
      <button disabled={!file || busy}>{uploading ? "正在上传，请稍候…" : "上传原片"}</button>{uploading && <p role="status">正在传输文件，尚无可用字节进度。</p>}
    </form>
    <SourceMediaTools projectId={project.id} revision={project.revision} csrf={csrf} dirty={dirty || busy} refreshVersion={refreshVersion} refresh={refresh} />
    {selection && <WaveformPanel projectId={project.id} source={{selection_revision: selection.revision, transcript_revision: timeline.transcript?.id ?? null}} csrf={csrf} dirty={dirty || selection.stale} refreshVersion={refreshVersion} onSeek={milliseconds => {if (video.current) video.current.currentTime = milliseconds / 1000;}} />}
    {project.source_asset_id && <div className="probe-info"><button className="secondary" disabled={busy || runs.some(run => run.stage === "probe" && ["queued", "running", "retry_wait"].includes(run.status))} onClick={() => void perform(signal => api<Run>(`${path}/runs`, {method: "POST", signal, body: JSON.stringify({stage: "probe"})}, csrf)).then(result => {if (result) refresh();})}>读取媒体信息</button>
      {duration !== undefined && <p className="muted">原片时长 {seconds(duration)} 秒{facts?.video?.codec ? ` · 视频 ${facts.video.codec}` : ""}{facts?.video?.width ? ` · ${facts.video.width} × ${facts.video.height}` : ""}</p>}
    </div>}
    {audio.length > 0 && <form onSubmit={e => void save(e)} aria-label="源片段选择"><label>分析音轨<select value={ordinal} disabled={busy} onChange={e => {setOrdinal(e.target.value); setDirty(true);}}>{audio.map(track => <option key={track.audio_ordinal} value={track.audio_ordinal}>音轨 {track.audio_ordinal} · {track.codec} · {track.language ?? "语言未知"} · {track.channels} 声道</option>)}</select></label>
      <div className="range-fields"><label>开始时间（毫秒）<input type="number" min={0} max={duration} step={1} value={start} disabled={busy} onChange={e => {setStart(e.target.value); setDirty(true);}} /></label><label>结束时间（毫秒）<input type="number" min={1} max={duration} step={1} value={end} disabled={busy} onChange={e => {setEnd(e.target.value); setDirty(true);}} /></label></div>
      {!valid && <p className="error">请在原片时长内选择有效范围：开始小于结束，使用整数毫秒。</p>}
      {selection && <p className="muted">服务器已选：{seconds(selection.start_ms)}–{seconds(selection.end_ms)} 秒 · 音轨 {selection.track.audio_ordinal} · 选择版本 {selection.revision}</p>}
      <div className="actions"><button className="secondary" disabled={busy || !valid}>保存源片段</button>{dirty && <button className="link" type="button" disabled={busy} onClick={() => setDirty(false)}>放弃范围修改</button>}</div>
    </form>}
    {selection && !selection.stale && <div className="analysis-actions"><h3>源分析</h3><p className="muted">提取音轨 → 分离人声 → 识别源字幕与角色，之后等待源字幕与角色审核。</p>
      <p className="muted">所需服务：背景分离{providers ? (providers.providers.separation ? "已配置" : "未配置") : "状态待检查"}、识别{providers ? (providers.providers.transcription ? "已配置" : "未配置") : "状态待检查"}。<a href="#/services">服务配置</a></p>
      <button disabled={busy || dirty || (workflow?.status === "running")} onClick={() => void analyse()}>分析所选源片段</button>{dirty && <p className="muted">请先保存或重新加载所改范围。</p>}
      {workflow && <p role="status">源分析：{statusName(workflow.status)}{workflow.stage ? ` · ${stageName(workflow.stage)}` : ""}{workflow.next_action === "source_and_cast_review" ? " · 源字幕与角色待审核" : workflow.next_action ? " · 需要检查后继续" : ""}</p>}
      {timeline.transcript && <p className="muted">已有源字幕供人工核对；此按钮不会自动执行后续翻译与配音。</p>}
    </div>}
    {error && <p className="error" role="alert">{error}</p>}
  </section>;
}
