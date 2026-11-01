import {useEffect, useRef, useState} from "react";
import {api} from "../api/client";
import type {Project} from "../api/projects";
import type {Run, Timeline} from "./types";
import {languageName, rowGuard, sourceGuard, targetPath, type LanguageTrack, type TargetDraft, type TranslationCommand} from "./targetTypes";
import {useTargetData} from "./useTargetData";
import {useAction} from "./useAction";
import TargetRowEditor from "./TargetRowEditor";
import TranslationCommandPanel from "./TranslationCommandPanel";
function route() {const query = window.location.hash.split("?")[1] ?? "", params = new URLSearchParams(query); return {tag: params.get("target"), command: /^[A-Za-z0-9-]{1,36}$/.test(params.get("command") ?? "") ? params.get("command") : null};}
type Props = {project: Project; sourceTimeline: Timeline; csrf: string; refreshVersion: number; runs: Run[]; refresh: () => void};
export default function TargetPanel({project, sourceTimeline, csrf, refreshVersion, runs, refresh}: Props) {
  const tags = [...new Set([...project.target_languages, ...(sourceTimeline.language_tracks ?? []).filter(track => !track.archived).map(track => track.tag)])];
  const [location, setLocation] = useState(route), [offset, setOffset] = useState(0), [version, setVersion] = useState(0), [drafts, setDrafts] = useState<Record<string, TargetDraft>>({});
  const tag = tags.includes(location.tag ?? "") ? location.tag! : tags[0] ?? "";
  const data = useTargetData(project.id, tag, offset, refreshVersion + version, location.command), {timeline} = data;
  const [modeDraft, setModeDraft] = useState<LanguageTrack["mode"] | null>(null), modeBase = useRef<number | null>(null), {busy, error, perform} = useAction();
  const track = timeline?.language_tracks?.find(track => track.tag === tag && !track.archived), mode = modeDraft ?? track?.mode ?? "Fast";
  useEffect(() => {const changed = () => {setLocation(route()); setOffset(0); setModeDraft(null); modeBase.current = null;}; window.addEventListener("hashchange", changed); return () => window.removeEventListener("hashchange", changed);}, []);
  function navigate(target: string, command?: string) {const params = new URLSearchParams({target}); if (command) params.set("command", command); window.location.hash = `/projects/${encodeURIComponent(project.id)}?${params}`; setLocation({tag: target, command: command ?? null});}
  function reload() {setVersion(value => value + 1); refresh();}
  const guard = timeline ? sourceGuard(timeline) : null;
  const dirty = Object.keys(drafts).some(key => key.startsWith(`${tag}/`));
  const unresolved = runs.some(run => run.target_language === tag && run.stage.startsWith("translation_") && (run.remote_state === "submitting" || run.safe_error?.code === "SUBMISSION_UNCERTAIN" || ["queued", "running", "retry_wait", "cancelling"].includes(run.status))) || data.command?.next_action === "acknowledge_uncertain_submission" || data.command?.status === "running" || error.includes("SUBMISSION_UNCERTAIN") || error.includes("RUN_ACTIVE");
  async function saveMode() {
    const result = await perform(signal => api(targetPath(project.id, tag), {method: "PATCH", signal, body: JSON.stringify({revision: modeBase.current ?? track?.revision, mode})}, csrf));
    if (result) {setModeDraft(null); modeBase.current = null; reload();}
  }
  async function activate() {const result = await perform(signal => api(`/projects/${encodeURIComponent(project.id)}/language-tracks`, {method: "POST", signal, body: JSON.stringify({tag, mode})}, csrf)); if (result) reload();}
  async function translate() {
    if (!timeline || !guard || !track?.materialized || dirty || unresolved || modeDraft) return;
    const segments = timeline.segments.map(row => ({id: row.id, revision: row.translation?.revision ?? 0, expected_source_text_fingerprint: row.source_text_fingerprint, locked: row.translation?.locked ?? false, approved: row.translation?.approved ?? false}));
    const result = await perform(signal => api<TranslationCommand>(`${targetPath(project.id, tag)}/translate`, {method: "POST", signal, body: JSON.stringify({...guard, track_revision: track.revision, segments, force_replace: false})}, csrf));
    if (result) {navigate(tag, result.id); reload();}
  }
  return <section className="panel target-panel" aria-labelledby="target-title"><h2 id="target-title">翻译工作台</h2>
    <div className="target-tabs" role="tablist" aria-label="目标语言">{tags.map(target => <button role="tab" aria-selected={target === tag} key={target} className={target === tag ? "" : "secondary"} onClick={() => navigate(target)}>{languageName(target)} · {target}</button>)}</div>
    {!tags.length ? <p className="muted">项目尚未声明目标语言。</p> : !timeline ? <p role="status">{data.error || "正在加载译文…"}</p> : <>
      {data.loading && <p role="status" className="muted">正在核对译文状态…</p>}
      {data.error && <p className="error" role="alert">{data.error} <button className="link" onClick={reload}>重新加载译文</button></p>}
      {!guard && <p className="muted">源字幕尚未就绪或已过期，请先完成并核对源分析。</p>}
      {!track?.materialized ? <div><p className="muted">此目标语言尚未启用，启用后可手动填写或请求翻译。</p><button className="secondary" disabled={busy || !guard} onClick={() => void activate()}>启用{languageName(tag)}译文</button></div> : <>
        <div className="translation-tools"><label>翻译模式<select value={mode} disabled={busy} onChange={event => {if (!modeDraft) modeBase.current = track.revision; setModeDraft(event.target.value as LanguageTrack["mode"]);}}><option value="Fast">快速逐行（Fast）</option><option value="Cinematic">完整语境（Cinematic）</option><option value="Autofit">语境与时长建议（Autofit）</option></select></label>{modeDraft && <div className="actions"><button className="secondary" disabled={busy} onClick={() => void saveMode()}>保存翻译模式</button><button className="link" onClick={() => {setModeDraft(null); modeBase.current = null;}}>放弃模式修改</button></div>}
          <button disabled={busy || !guard || dirty || !!modeDraft || unresolved || !timeline.segments.some(row => rowGuard(timeline, row) && !row.translation?.locked && !row.translation?.approved)} onClick={() => void translate()}>翻译本页未保护行</button></div>
        <p className="muted">仅点击后请求云端翻译；已锁定或已确认的译文保留。Autofit 提供时长估计与精简建议，不保证配音时长。</p>
        {unresolved && <p className="error">当前目标有未完成或结果未知的翻译任务，请先在任务区核查并恢复原任务。</p>}
        {dirty && <p className="muted">有未保存的译文修改，请先保存或放弃，再请求自动翻译。</p>}
        <ol className="target-rows">{timeline.segments.map((row, index) => <TargetRowEditor key={`${tag}/${row.id}`} projectId={project.id} tag={tag} timeline={timeline} row={row} index={offset + index + 1} csrf={csrf} draft={drafts[`${tag}/${row.id}`]} onDraft={draft => setDrafts(previous => {const next = {...previous}; if (draft) next[`${tag}/${row.id}`] = draft; else delete next[`${tag}/${row.id}`]; return next;})} onSaved={reload} />)}</ol>
        {timeline.total > 50 && <nav className="actions pagination" aria-label="译文分页"><button className="secondary" disabled={!offset || data.loading} onClick={() => setOffset(Math.max(0, offset - 50))}>上一页译文</button><span>{offset + 1}–{Math.min(offset + 50, timeline.total)} / {timeline.total}</span><button className="secondary" disabled={offset + 50 >= timeline.total || data.loading} onClick={() => setOffset(offset + 50)}>下一页译文</button></nav>}
      </>}
      {data.command && <TranslationCommandPanel command={data.command} />}{data.commandError && <p className="error" role="alert">{data.commandError}</p>}
    </>}{error && <p className="error" role="alert">{error}</p>}
  </section>;
}
