import {useEffect, useState} from "react";
import {api, ApiError} from "../api/client";
import type {Page} from "../api/projects";
import {targetPath, type LanguageTrack} from "./targetTypes";
import {useAction} from "./useAction";
type Context = {id: string; summary: string; glossary: Record<string, string>; provenance?: string};
type Draft = {revision: number; summary: string; terms: {source: string; target: string}[]};
async function readContext(path: string, id: string, signal: AbortSignal): Promise<Context> {
  const first = await api<Page<Context>>(`${path}/contexts?limit=50&offset=0`, {signal}), match = first.items.find(item => item.id === id);
  if (match) return match;
  for (let offset = Math.floor((first.total - 1) / 50) * 50; offset >= 50; offset -= 50) {
    const page = await api<Page<Context>>(`${path}/contexts?limit=50&offset=${offset}`, {signal}), found = page.items.find(item => item.id === id);
    if (found) return found;
  }
  throw new ApiError(409, "未找到当前上下文版本，请重新读取；不会以其他历史版本替代。");
}
export default function TargetContextEditor({projectId, csrf, track, refreshVersion, onSaved, onDirty}: {projectId: string; csrf: string; track: LanguageTrack; refreshVersion: number; onSaved: () => void; onDirty?: (value: boolean) => void}) {
  const [snapshot, setSnapshot] = useState<{revision: number; context: Context} | null>(null), [draft, setDraft] = useState<Draft | null>(null), [loadError, setLoadError] = useState(""), [version, setVersion] = useState(0);
  const {busy, error, perform} = useAction(), path = targetPath(projectId, track.tag);
  useEffect(() => {
    if (!track.context_revision_id) {setLoadError("当前语言未提供可读取的上下文版本。"); return;}
    let active = true; const controller = new AbortController(), revision = track.revision;
    readContext(path, track.context_revision_id, controller.signal).then(context => {if (active) {setSnapshot({revision, context}); setLoadError("");}}).catch(error => {if (active) setLoadError(error instanceof ApiError ? error.message : "上下文读取失败，请重试。");});
    return () => {active = false; controller.abort();};
  }, [path, track.context_revision_id, track.revision, refreshVersion, version]);
  useEffect(() => {onDirty?.(!!draft);}, [draft, onDirty]);
  const initial = snapshot ? {revision: snapshot.revision, summary: snapshot.context.summary, terms: Object.entries(snapshot.context.glossary).map(([source, target]) => ({source, target}))} : null, values = draft ?? initial;
  function edit(change: Partial<Pick<Draft, "summary" | "terms">>) {if (initial) setDraft(previous => ({...(previous ?? initial), ...change}));}
  const valid = values && values.summary.length <= 20000 && values.terms.length <= 200 && values.terms.every(term => term.source.trim() && term.target.trim() && term.source.length <= 200 && term.target.length <= 500) && new Set(values.terms.map(term => term.source)).size === values.terms.length && values.terms.reduce((total, term) => total + term.source.length + term.target.length, 0) <= 20000;
  async function save() {if (!draft || !valid) return; const result = await perform(signal => api(path, {method: "PATCH", signal, body: JSON.stringify({revision: draft.revision, summary: draft.summary, glossary: Object.fromEntries(draft.terms.map(term => [term.source, term.target]))})}, csrf)); if (result) {setDraft(null); setVersion(value => value + 1); onSaved();}}
  return <div className="context-editor"><h3>翻译上下文与术语</h3><p className="muted">人工填写的摘要与术语将用于后续翻译。保存会更新当前语言设置，使依赖旧上下文的工作需要重新核对。</p>{loadError && <p className="error" role="alert">{loadError} <button className="link" onClick={() => setVersion(value => value + 1)}>重新读取上下文</button></p>}{!values ? !loadError && <p role="status">正在读取当前上下文版本…</p> : <>
    <label>翻译上下文摘要<textarea dir="auto" rows={5} maxLength={20000} value={values.summary} disabled={busy} onChange={event => edit({summary: event.target.value})} /></label><h4>术语表</h4>{values.terms.map((term, index) => <div className="glossary-row" key={index}><label>术语 {index + 1}<input dir="auto" maxLength={200} value={term.source} disabled={busy} onChange={event => edit({terms: values.terms.map((value, position) => position === index ? {...value, source: event.target.value} : value)})} /></label><label>译法 {index + 1}<input dir="auto" maxLength={500} value={term.target} disabled={busy} onChange={event => edit({terms: values.terms.map((value, position) => position === index ? {...value, target: event.target.value} : value)})} /></label><button className="link" disabled={busy} onClick={() => edit({terms: values.terms.filter((_, position) => position !== index)})}>删除术语 {index + 1}</button></div>)}<button className="link" disabled={busy || values.terms.length >= 200} onClick={() => edit({terms: [...values.terms, {source: "", target: ""}]})}>添加术语</button>
    {!valid && <p className="error">术语及译法不能为空，术语不能重复，并需符合字数上限。</p>}<div className="actions"><button className="secondary" disabled={busy || !draft || !valid} onClick={() => void save()}>保存上下文与术语</button>{draft && <button className="link" disabled={busy} onClick={() => setDraft(null)}>放弃上下文修改</button>}</div>
  </>}{error && <p className="error" role="alert">{error}</p>}</div>;
}
