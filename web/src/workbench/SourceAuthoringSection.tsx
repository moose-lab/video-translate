import {useEffect, useState} from "react";
import {api, ApiError} from "../api/client";
import {projectPath} from "../api/projects";
import {sourceGuard} from "./targetTypes";
import type {Timeline} from "./types";
import SourceRowEditor from "./SourceRowEditor";
import SubtitleImportPanel from "./SubtitleImportPanel";
function SourceAuthoringPanel({projectId, csrf, refreshVersion, onSaved}: {projectId: string; csrf: string; refreshVersion: number; onSaved: () => void}) {
  const [timeline, setTimeline] = useState<Timeline | null>(null), [offset, setOffset] = useState(0), [version, setVersion] = useState(0), [error, setError] = useState("");
  useEffect(() => {let active = true; const controller = new AbortController(); api<Timeline>(`${projectPath(projectId)}/timeline?limit=50&offset=${offset}`, {signal: controller.signal}).then(value => {if (active) {setTimeline(value); setError("");}}).catch(error => {if (active) setError(error instanceof ApiError ? error.message : "源字幕编辑数据读取失败。");}); return () => {active = false; controller.abort();};}, [projectId, offset, refreshVersion, version]);
  function saved() {setVersion(value => value + 1); onSaved();}
  const guard = timeline ? sourceGuard(timeline) : null, selected = timeline?.source && !timeline.source.stale ? timeline.source : null;
  return <div>{error && <p className="error" role="alert">{error}</p>}{!timeline ? !error && <p role="status">正在读取源字幕编辑数据…</p> : <>
    {guard && <ol className="source-edit-rows">{timeline.segments.map((row, index) => <li key={row.id}><SourceRowEditor projectId={projectId} csrf={csrf} source={guard} row={row} next={timeline.segments[index + 1]} index={offset + index + 1} windowDuration={selected!.end_ms - selected!.start_ms} onSaved={saved} /></li>)}</ol>}
    {timeline.total > 50 && <nav className="actions pagination" aria-label="源文字编辑分页"><button className="secondary" disabled={!offset} onClick={() => setOffset(Math.max(0, offset - 50))}>上一页源文字</button><span>{offset + 1}–{Math.min(offset + 50, timeline.total)} / {timeline.total}</span><button className="secondary" disabled={offset + 50 >= timeline.total} onClick={() => setOffset(offset + 50)}>下一页源文字</button></nav>}
    {selected ? <SubtitleImportPanel projectId={projectId} csrf={csrf} guard={{selection_revision: selected.revision, transcript_revision: timeline.transcript?.id ?? null}} roles={timeline.cast} onSaved={saved} /> : <p className="muted">请先保存有效源片段，再编辑或手动导入源字幕。</p>}
  </>}</div>;
}
export default function SourceAuthoringSection(props: {projectId: string; csrf: string; refreshVersion: number; onSaved: () => void}) {
  const [open, setOpen] = useState(false), [visited, setVisited] = useState(false);
  return <section className="panel"><div className="section-head"><h2>源字幕文字与时间</h2><button className="secondary" aria-expanded={open} aria-controls="source-authoring-content" onClick={() => {setVisited(true); setOpen(!open);}}>{open ? "收起源字幕编辑" : "编辑或导入源字幕"}</button></div><p className="muted">人工修正文稿与片段内时间，或导入带时间的字幕；所有变更保留实际来源。</p><div id="source-authoring-content" hidden={!open}>{visited && <SourceAuthoringPanel {...props} />}</div></section>;
}
