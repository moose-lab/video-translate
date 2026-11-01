import {useRef, useState, type FormEvent} from "react";
import {api} from "../api/client";
import {projectPath} from "../api/projects";
import LanguagePicker from "../settings/LanguagePicker";
import type {Run} from "./types";
import {statusName} from "./types";
import {useAction} from "./useAction";
export default function ReferenceUploadForm({projectId, csrf, sourceLanguage, onChanged}: {projectId: string; csrf: string; sourceLanguage: string; onChanged: () => void}) {
  const [file, setFile] = useState<File | null>(null), [text, setText] = useState(""), [language, setLanguage] = useState(sourceLanguage === "auto" ? "" : sourceLanguage), [fileError, setFileError] = useState(""), [run, setRun] = useState<Run | null>(null);
  const input = useRef<HTMLInputElement>(null), {busy, error, perform} = useAction();
  async function upload(event: FormEvent) {
    event.preventDefault(); if (!file || file.size === 0 || file.size > 64 * 1024 * 1024 || !text.trim() || !language || language === "auto") return;
    const body = new FormData(); body.append("file", file); body.append("text", text); body.append("language", language);
    const result = await perform(signal => api<{run: Run; reference: null}>(`${projectPath(projectId)}/references/upload`, {method: "POST", body, signal}, csrf));
    if (result) {setRun(result.run); setFile(null); if (input.current) input.current.value = ""; onChanged();}
  }
  return <form onSubmit={event => void upload(event)}><h3>上传参考音</h3><p className="muted">上传一段参考音及其准确原文，选择音频实际使用的语言。服务端任务完成后才会发布参考音；时长与警告以处理完成后的参考音库为准。</p>
    <fieldset disabled={busy}><label>参考音文件<input ref={input} type="file" accept="audio/*" onChange={event => {const next = event.target.files?.[0] ?? null; setFile(next); setFileError(next && next.size > 64 * 1024 * 1024 ? "参考音文件不能超过 64 MiB。" : next?.size === 0 ? "参考音文件不能为空。" : "");}} /></label>
      <label>上传参考音原文<textarea rows={3} dir="auto" required value={text} onChange={event => setText(event.target.value)} /></label><p className="muted">参考音语言：{language || "请选择明确语言"}</p><details open><summary>选择上传参考音语言</summary><LanguagePicker target value={language} onChange={setLanguage} /></details>
      <button className="secondary" disabled={!file || !!fileError || !text.trim() || !language || language === "auto"}>上传参考音</button></fieldset>
    {busy && <p role="status">正在上传，提交成功后可在任务区查看处理、取消与恢复状态。</p>}{fileError && <p className="error" role="alert">{fileError}</p>}{error && <p className="error" role="alert">{error}</p>}
    {run && <p className="notice" role="status">参考音任务 {run.id} · {statusName(run.status)}（提交时状态）。请在任务区查看最新状态、取消或恢复；处理完成后刷新参考音库。</p>}
  </form>;
}
