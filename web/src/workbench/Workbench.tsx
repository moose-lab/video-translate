import { useEffect, useState } from "react";
import { projectsApi, type Project } from "../api/projects";
import ProjectList from "./ProjectList";
function currentProject() { const match = /^#\/projects\/([A-Za-z0-9-]+)$/.exec(window.location.hash); return match?.[1] ?? null; }
function ProjectDetail({id}: {id: string}) {
  const [project, setProject] = useState<Project | null>(null), [error, setError] = useState("");
  useEffect(() => {let active = true; const controller = new AbortController(); projectsApi.get(id, controller.signal).then(value => {if (active) setProject(value);}).catch(e => {if (active) setError(e instanceof Error ? e.message : "项目加载失败");}); return () => {active = false; controller.abort();};}, [id]);
  return <main className="content workbench"><a href="#/projects">← 所有项目</a>{error ? <p role="alert" className="error">{error}</p> : project ? <><h1>{project.name}</h1><p className="muted">{project.source_language} → {project.target_languages.join(" · ")}</p><p>项目状态：{project.status}</p><p className="muted">原片与源字幕工作台正在接入。</p></> : <p role="status">正在打开项目…</p>}</main>;
}
export default function Workbench({csrf}: {csrf: string}) {
  const [id, setId] = useState(currentProject);
  useEffect(() => { const changed = () => setId(currentProject()); window.addEventListener("hashchange", changed); return () => window.removeEventListener("hashchange", changed); }, []);
  return id ? <ProjectDetail key={id} id={id} /> : <ProjectList csrf={csrf} />;
}
