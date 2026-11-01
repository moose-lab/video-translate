import {useEffect, useState} from "react";
import {api, ApiError} from "../api/client";
import type {AudioHistory} from "./audioTypes";
import type {Segment} from "./types";
import {seconds} from "./types";
import {targetPath, type SourceGuard} from "./targetTypes";
import {useAction} from "./useAction";
type HistorySnapshot = {history: AudioHistory; base: SourceGuard & {translation_revision: number; expected_source_text_fingerprint: string}};
export default function AudioHistoryPanel({projectId, tag, row, source, csrf, refresh}: {projectId: string; tag: string; row: Segment; source: SourceGuard; csrf: string; refresh: () => void}) {
  const [snapshot, setSnapshot] = useState<HistorySnapshot | null>(null), [offset, setOffset] = useState(0), [loadError, setLoadError] = useState("");
  const {busy, error, perform} = useAction(), path = `${targetPath(projectId, tag)}/segments/${encodeURIComponent(row.id)}`;
  useEffect(() => {
    let active = true; const controller = new AbortController();
    const base = {...source, translation_revision: row.translation?.revision ?? 0, expected_source_text_fingerprint: row.source_text_fingerprint ?? ""};
    api<AudioHistory>(`${path}/audio-history?limit=10&offset=${offset}`, {signal: controller.signal}).then(history => {if (active) {setSnapshot({history, base}); setLoadError("");}}).catch(error => {if (active) setLoadError(error instanceof ApiError ? error.message : "音频历史加载失败。");});
    return () => {active = false; controller.abort();};
    // An open page keeps its original guards; navigation to another history page takes a fresh snapshot.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [path, offset]);
  async function select(outputId: string) {
    if (!snapshot) return;
    const base = snapshot.base;
    const result = await perform(signal => api<AudioHistory>(`${path}/audio-selection`, {method: "PUT", signal, body: JSON.stringify({...base, revision: snapshot.history.selection_revision, output_id: outputId})}, csrf));
    if (result) {setSnapshot({history: result, base}); refresh();}
  }
  return <div className="audio-history"><h3>自然音频历史</h3>{loadError && <p className="error" role="alert">{loadError}</p>}{!snapshot ? <p role="status">正在读取音频历史…</p> : <>{!snapshot.history.outputs.length && <p className="muted">暂无历史音频。</p>}<ol>{snapshot.history.outputs.map((output, index) => <li key={output.id}><p className="muted">音频 {offset + index + 1} · 实测 {seconds(output.natural_duration_ms)} 秒 · {output.stale ? "已过期" : snapshot.history.selected_output_id === output.id ? "当前选用" : "未选用"}</p><audio controls preload="none" aria-label={`历史音频 ${offset + index + 1}`} src={`/api/assets/${encodeURIComponent(output.audio_asset_id)}/content`} /><button className="secondary" disabled={busy || output.stale || output.evidence_status !== "validated" || snapshot.history.selected_output_id === output.id} onClick={() => void select(output.id)}>选用历史音频 {offset + index + 1}</button></li>)}</ol>{snapshot.history.total > 10 && <nav className="actions pagination" aria-label="音频历史分页"><button className="secondary" disabled={!offset || busy} onClick={() => setOffset(Math.max(0, offset - 10))}>上一页历史音频</button><button className="secondary" disabled={offset + 10 >= snapshot.history.total || busy} onClick={() => setOffset(offset + 10)}>下一页历史音频</button></nav>}</>}{error && <p className="error" role="alert">{error}</p>}</div>;
}
