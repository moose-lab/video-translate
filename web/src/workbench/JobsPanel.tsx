import {useState} from "react";
import {api, safeCode, safeFailureMessage} from "../api/client";
import type {Page} from "../api/projects";
import type {Run} from "./types";
import {stageName, statusName} from "./types";
import {useAction} from "./useAction";
export default function JobsPanel({runs, offset, onOffset, csrf, refresh}: {runs: Page<Run>; offset: number; onOffset: (value: number) => void; csrf: string; refresh: () => void}) {
  const {busy, error, perform} = useAction(); const [uncertain, setUncertain] = useState<string | null>(null), [acknowledged, setAcknowledged] = useState(false), [notice, setNotice] = useState("");
  async function retry(run: Run, acknowledge = false) {
    const unknownSubmission = run.safe_error?.code === "SUBMISSION_UNCERTAIN" || (run.remote_state === "submitting" && !run.remote_id);
    if (unknownSubmission && !acknowledge) {setUncertain(run.id); setAcknowledged(false); return;}
    const result = await perform(signal => api<Run>(`/runs/${encodeURIComponent(run.id)}/retry`, {method: "POST", signal, body: JSON.stringify({acknowledge_uncertain_submission: acknowledge})}, csrf));
    if (result) {setUncertain(null); setNotice(run.remote_id && run.remote_state !== "completed" ? "已请求恢复已有远程任务的轮询。" : "重试请求已提交，请查看任务实际状态。"); refresh();}
  }
  async function cancel(run: Run) {
    const result = await perform(signal => api<Run>(`/runs/${encodeURIComponent(run.id)}/cancel`, {method: "POST", signal}, csrf));
    if (result) {setNotice("取消请求已提交；远程任务是否停止以之后的状态为准。"); refresh();}
  }
  return <section className="panel" aria-labelledby="jobs-title"><div className="section-head"><h2 id="jobs-title">任务</h2><span className="muted">{runs.total} 项</span></div>
    {error && <p role="alert" className="error">{error}</p>}{notice && <p role="status" className="notice">{notice}</p>}
    {runs.items.length === 0 ? <p className="muted">尚无任务。上传后读取媒体信息，选择源片段后再开始分析。</p> : <ul className="job-list">{runs.items.map(run => <li key={run.id}><div className="section-head"><strong>{stageName(run.stage)}{run.target_language ? ` · ${run.target_language}` : ""}</strong><span className="status">{statusName(run.status)}{run.is_stale ? " · 输入已过期" : ""}</span></div>
      <p className="muted">尝试 {run.attempt_count} 次{run.remote_id && run.remote_state !== "completed" ? " · 已有远程任务，重试会恢复轮询" : ""}</p>
      {run.safe_error && <p className="error">{safeFailureMessage(run.safe_error.code)} ({safeCode(run.safe_error.code)})</p>}
      <div className="actions">{["failed", "stale", "needs_review", "cancelled"].includes(run.status) && <button className="secondary" disabled={busy} onClick={() => void retry(run)}>重试</button>}{["queued", "running", "retry_wait"].includes(run.status) && <button className="secondary" disabled={busy} onClick={() => void cancel(run)}>取消任务</button>}</div>
      {uncertain === run.id && <div className="uncertainty" role="group" aria-label="确认未知提交"><p>上次远程提交结果未知，重试可能重复提交。先核查远程任务，再作出选择。</p><label className="check-label"><input type="checkbox" checked={acknowledged} onChange={e => setAcknowledged(e.target.checked)} />我已核查远程任务，了解重试可能重复提交</label><div className="actions"><button disabled={busy || !acknowledged} onClick={() => void retry(run, true)}>确认重试此任务</button><button className="secondary" disabled={busy} onClick={() => setUncertain(null)}>保留当前状态</button></div></div>}
    </li>)}</ul>}
    {runs.total > 50 && <nav className="actions pagination" aria-label="任务分页"><button className="secondary" disabled={!offset || busy} onClick={() => onOffset(Math.max(0, offset - 50))}>上一页任务</button><span>{offset + 1}–{Math.min(offset + 50, runs.total)} / {runs.total}</span><button className="secondary" disabled={offset + 50 >= runs.total || busy} onClick={() => onOffset(offset + 50)}>下一页任务</button></nav>}
  </section>;
}
