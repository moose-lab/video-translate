import {useEffect, useRef, useState} from "react";
import {api, ApiError} from "../api/client";
import {projectPath} from "../api/projects";
import {statusName} from "./types";
import {useAction} from "./useAction";

type ImportItem = {id: string; run_id: string; adapter: string; status: string; stale: boolean; next_action: string | null; error: unknown};
export default function SourceMediaTools({projectId, revision, csrf, dirty, refreshVersion, refresh}: {projectId: string; revision: number; csrf: string; dirty: boolean; refreshVersion: number; refresh: () => void}) {
  const [open, setOpen] = useState(false), [url, setUrl] = useState(""), [items, setItems] = useState<ImportItem[]>([]), [reload, setReload] = useState(0), [loading, setLoading] = useState(false), [readError, setReadError] = useState(""), [uncertain, setUncertain] = useState(false);
  const draftRevision = useRef(revision), {busy, error, perform} = useAction();
  const path = `${projectPath(projectId)}/source-imports`;
  useEffect(() => {
    if (!open) return;
    const controller = new AbortController(); setLoading(true); setReadError("");
    api<{items: ImportItem[]}>(path, {signal: controller.signal}).then(result => {if (!controller.signal.aborted) setItems(result.items);}).catch(() => {if (!controller.signal.aborted) setReadError("无法读取链接导入记录，请重试。");}).finally(() => {if (!controller.signal.aborted) setLoading(false);});
    return () => controller.abort();
  }, [open, path, refreshVersion, reload]);
  async function submit() {
    const result = await perform(async signal => {
      try {return await api<ImportItem>(path, {method: "POST", signal, body: JSON.stringify({url, revision: draftRevision.current})}, csrf);}
      catch (failure) {if (!(failure instanceof ApiError)) {setUncertain(true); setReload(value => value + 1);} throw failure;}
    });
    if (result) {setUrl(""); setUncertain(false); setItems(current => [result, ...current.filter(item => item.id !== result.id)]); refresh();}
  }
  async function action(item: ImportItem, kind: "cancel" | "retry") {
    const result = await perform(signal => api(`/runs/${encodeURIComponent(item.run_id)}/${kind}`, {method: "POST", signal, ...(kind === "retry" ? {body: JSON.stringify({acknowledge_uncertain_submission: false})} : {})}, csrf));
    if (result) {setReload(value => value + 1); refresh();}
  }
  let valid = false; try {valid = new URL(url).protocol === "https:";} catch { /* Keep incomplete drafts editable. */ }
  return <div className="source-media-tools"><button className="link" aria-expanded={open} onClick={() => setOpen(!open)}>从公开链接导入</button>{open && <div>
    <p className="muted">支持的公开 HTTPS 视频由服务器下载。需登录、地区限制或无法下载时，请上传兼容的本地文件。</p>
    <label>公开视频 HTTPS 链接<input type="url" value={url} disabled={busy} autoComplete="off" onChange={event => {if (!url) draftRevision.current = revision; setUrl(event.target.value);}} /></label>
    <div className="actions"><button className="secondary" disabled={busy || dirty || !valid || uncertain} onClick={() => void submit()}>提交链接导入</button><button className="link" disabled={busy} onClick={() => {setUrl(""); draftRevision.current = revision; setUncertain(false);}}>放弃链接修改</button><button className="link" disabled={loading || busy} onClick={() => setReload(value => value + 1)}>刷新链接导入记录</button></div>
    {dirty && <p className="muted">请先保存或放弃源片段范围修改。</p>}{uncertain && <p role="alert" className="error">提交结果未知，正在读取持久记录。请核对任务后放弃当前草稿，再决定是否重新提交。</p>}
    {loading && <p role="status">正在读取链接导入记录…</p>}{readError && <p role="alert" className="error">{readError}</p>}{error && <p role="alert" className="error">{error}</p>}
    {items.length > 0 && <ul className="job-list">{items.map(item => <li key={item.id}><p>{item.adapter === "youtube" ? "YouTube" : "公开视频"} · {statusName(item.status)}{item.stale ? " · 已过期" : ""}</p>{item.next_action === "upload_source" && <p className="muted">此链接暂不能导入，可改用上方文件上传。</p>}<div className="actions">{["queued", "running", "retry_wait"].includes(item.status) && <button className="secondary" disabled={busy} onClick={() => void action(item, "cancel")}>取消链接导入</button>}{["failed", "cancelled"].includes(item.status) && <button className="secondary" disabled={busy || dirty || uncertain} onClick={() => void action(item, "retry")}>重试链接导入</button>}</div></li>)}</ul>}
  </div>}</div>;
}
