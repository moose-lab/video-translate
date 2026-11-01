import {useState} from "react";
import {api} from "../api/client";
import {projectPath} from "../api/projects";
import LanguagePicker from "../settings/LanguagePicker";
import type {Segment} from "./types";
import {seconds} from "./types";
import type {SourceGuard} from "./targetTypes";
import {useAction} from "./useAction";
export default function ReferenceExtractForm({projectId, csrf, source, row, index, sourceLanguage, onChanged}: {projectId: string; csrf: string; source: SourceGuard; row: Segment; index: number; sourceLanguage: string; onChanged: () => void}) {
  const [snapshot, setSnapshot] = useState(() => ({source, row})), [language, setLanguage] = useState(sourceLanguage !== "auto" ? sourceLanguage : ""), [media, setMedia] = useState("source"), [notice, setNotice] = useState("");
  const {busy, error, perform} = useAction(), changed = snapshot.source.selection_revision !== source.selection_revision || snapshot.source.transcript_revision !== source.transcript_revision || snapshot.row.revision !== row.revision;
  async function extract() {
    if (!language || !snapshot.row.revision) return;
    const result = await perform(signal => api(`${projectPath(projectId)}/references/extract`, {method: "POST", signal, body: JSON.stringify({...snapshot.source, segment_id: snapshot.row.id, segment_revision: snapshot.row.revision, speaker_id: snapshot.row.speaker_id, text: snapshot.row.text, language, media})}, csrf));
    if (result) {setNotice("参考音提取请求已提交，实际时长与质量需等待提取完成。发布后可选作行或角色参考音。"); onChanged();}
  }
  return <div className="reference-extract"><h4>从本行提取参考音</h4><p className="muted">原片 {seconds(snapshot.row.absolute_start_ms)}–{seconds(snapshot.row.absolute_end_ms)} 秒；使用当前选择的源音轨。提取严格沿用本行已保存的文字与时间范围。</p>
    <label>参考音原文<textarea dir="auto" rows={2} value={snapshot.row.text} readOnly /></label><label>参考音来源<select value={media} disabled={busy} onChange={event => setMedia(event.target.value)}><option value="source">原片音轨</option><option value="vocals">已分离人声</option></select></label>
    <p className="muted">参考音语言：{language || "请选择明确语言"}</p><details><summary>选择参考音语言</summary><LanguagePicker target value={language} onChange={setLanguage} /></details>
    {changed && <p className="error">源版本已更新，当前参考草稿仍保留打开时的原文与版本。<button className="link" disabled={busy} onClick={() => setSnapshot({source, row})}>使用当前源版本</button></p>}
    <button className="secondary" disabled={busy || !language || !snapshot.row.revision || !snapshot.row.text.trim()} onClick={() => void extract()}>提取第 {index} 行参考音</button>{notice && <p className="notice" role="status">{notice}</p>}{error && <p className="error" role="alert">{error}</p>}
  </div>;
}
