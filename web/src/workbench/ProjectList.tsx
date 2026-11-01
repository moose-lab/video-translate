import { useEffect, useState, type FormEvent } from "react";
import { projectsApi, type Project } from "../api/projects";
import LanguagePicker from "../settings/LanguagePicker";

export default function ProjectList({csrf}: {csrf: string}) {
  const [items, setItems] = useState<Project[]>([]), [total, setTotal] = useState(0), [offset, setOffset] = useState(0);
  const [loading, setLoading] = useState(true), [error, setError] = useState(""), [reload, setReload] = useState(0);
  const [creating, setCreating] = useState(false), [busy, setBusy] = useState(false), [name, setName] = useState("");
  const [source, setSource] = useState("auto"), [targets, setTargets] = useState<string[]>([]);
  useEffect(() => {
    const controller = new AbortController(); let active = true;
    setLoading(true); setError("");
    projectsApi.list(offset, controller.signal).then(page => { if (active) { setItems(page.items); setTotal(page.total); } })
      .catch(e => {if (active) setError(e instanceof Error ? e.message : "项目加载失败");})
      .finally(() => {if (active) setLoading(false);});
    return () => {active = false; controller.abort();};
  }, [offset, reload]);
  async function create(event: FormEvent) {
    event.preventDefault(); if (busy || !name.trim() || !targets.length) return;
    setBusy(true); setError("");
    try { const project = await projectsApi.create({name: name.trim(), source_language: source, target_languages: targets}, csrf); window.location.hash = `/projects/${encodeURIComponent(project.id)}`; }
    catch (e) {setError(e instanceof Error ? e.message : "项目创建失败");}
    finally {setBusy(false);}
  }
  return <main className="content workbench">
    <div className="page-head"><div><span className="eyebrow">WORKSPACE</span><h1>项目</h1><p className="muted">上传原片，选择片段，查看源字幕与任务状态。</p></div><button onClick={() => setCreating(!creating)} aria-expanded={creating}>新建项目</button></div>
    {error && <p className="error" role="alert">{error} <button className="link" onClick={() => setReload(x => x + 1)}>重新加载</button></p>}
    {creating && <form className="panel" onSubmit={e => void create(e)} aria-label="新建项目">
      <h2>创建项目</h2><label>项目名称<input value={name} maxLength={200} required onChange={e => setName(e.target.value)} /></label>
      <details><summary>选择源语言</summary><LanguagePicker target={false} value={source} onChange={setSource} /></details>
      <p className="muted">源语言：<bdi>{source}</bdi></p>
      <details><summary>添加目标语言</summary><LanguagePicker target value={targets.join(", ")} onChange={tag => setTargets(old => old.includes(tag) || old.length >= 20 ? old : [...old, tag])} /></details>
      <div className="language-tags">{targets.map(tag => <button className="secondary" type="button" key={tag} onClick={() => setTargets(old => old.filter(x => x !== tag))} aria-label={`移除 ${tag}`}>{tag} ×</button>)}</div>
      <p className="muted">可选择 1–20 种目标语言；仅源语言支持自动检测。</p>
      <button disabled={busy || !name.trim() || !targets.length}>{busy ? "正在创建…" : "创建项目"}</button>
    </form>}
    {loading ? <p role="status">正在加载项目…</p> : items.length === 0 ? <p className="empty">还没有项目。新建项目后上传视频。</p> : <ul className="project-list">{items.map(project => <li key={project.id}><div><a href={`#/projects/${encodeURIComponent(project.id)}`}>{project.name}</a><p className="muted"><bdi>{project.source_language}</bdi> → <bdi>{project.target_languages.join(" · ")}</bdi></p></div><span className="status">{project.status}</span></li>)}</ul>}
    {total > 50 && <nav className="actions" aria-label="项目分页"><button className="secondary" disabled={!offset || loading} onClick={() => setOffset(x => Math.max(0, x - 50))}>上一页</button><span>{offset + 1}–{Math.min(offset + 50, total)} / {total}</span><button className="secondary" disabled={offset + 50 >= total || loading} onClick={() => setOffset(x => x + 50)}>下一页</button></nav>}
  </main>;
}
