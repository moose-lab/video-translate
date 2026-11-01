import {useState} from "react";
import JobsPanel from "./JobsPanel";
import SourcePanel from "./SourcePanel";
import TranscriptPanel from "./TranscriptPanel";
import TargetPanel from "./TargetPanel";
import {statusName} from "./types";
import {useProjectData} from "./useProjectData";
export default function ProjectDetail({id, csrf}: {id: string; csrf: string}) {
  const [offset, setOffset] = useState(0), [runOffset, setRunOffset] = useState(0);
  const data = useProjectData(id, offset, runOffset), {project, timeline} = data;
  return <main className="content workbench"><a href="#/projects">← 所有项目</a>
    {data.error && <p role="alert" className="error">{data.error} <button className="link" onClick={data.refresh}>重新加载</button></p>}
    {!project || !timeline ? !data.error && <p role="status">正在打开项目…</p> : <>
      <div className="page-head"><div><h1>{project.name}</h1><p className="muted"><bdi>{project.source_language}</bdi> → <bdi>{project.target_languages.join(" · ")}</bdi></p></div><span className="status">{statusName(project.status)}</span></div>
      <div className="live-status" role="status"><span>{data.connection}{data.eventSequence ? ` · 事件 #${data.eventSequence}` : ""}{data.updating ? " · 正在核对状态" : ""}</span><button className="link" disabled={data.updating} onClick={data.refresh}>刷新状态</button></div>
      <div className="workbench-columns"><div><SourcePanel key={project.source_asset_id ?? "empty"} project={project} timeline={timeline} runs={data.runs.items} csrf={csrf} refresh={data.refresh} providers={data.providers} workflow={data.workflow} onWorkflow={data.setWorkflow} /><TranscriptPanel timeline={timeline} offset={offset} onOffset={setOffset} updating={data.updating} /><TargetPanel project={project} sourceTimeline={timeline} csrf={csrf} refreshVersion={data.refreshVersion} runs={data.runs.items} refresh={data.refresh} /></div><JobsPanel runs={data.runs} offset={runOffset} onOffset={setRunOffset} csrf={csrf} refresh={data.refresh} /></div>
    </>}
  </main>;
}
