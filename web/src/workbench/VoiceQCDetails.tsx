import {useEffect, useState} from "react";
import {api, ApiError} from "../api/client";
import {targetPath} from "./targetTypes";
import {statusName} from "./types";
type QCLine = {id: string; segment_id: string; status: string; current: boolean; next_action: string; recognition: {segments: {text: string}[]} | null};
export default function VoiceQCDetails({projectId, tag, requestId, segmentId}: {projectId: string; tag: string; requestId: string; segmentId: string}) {
  const [line, setLine] = useState<QCLine | null>(null), [error, setError] = useState(""), [loaded, setLoaded] = useState(false);
  useEffect(() => {
    let active = true; const controller = new AbortController(); setLine(null); setError(""); setLoaded(false);
    async function read() {
      try {
        for (let offset = 0; active && offset < 1000; offset += 100) {
          const result = await api<{lines: QCLine[]; total: number}>(`${targetPath(projectId, tag)}/voice-qc/${encodeURIComponent(requestId)}?limit=100&offset=${offset}`, {signal: controller.signal});
          if (!active) return;
          const found = result.lines.find(line => line.segment_id === segmentId);
          if (found) {setLine(found); break;}
          if (offset + 100 >= result.total || result.lines.length < 100) break;
        }
      } catch (error) {if (active) setError(error instanceof ApiError ? error.message : "质检识别详情加载失败。");}
      finally {if (active) setLoaded(true);}
    }
    void read(); return () => {active = false; controller.abort();};
  }, [projectId, tag, requestId, segmentId]);
  return <div>{error ? <p className="error" role="alert">{error}</p> : line ? <><p className="muted">识别任务：{statusName(line.status)}{line.current ? "" : " · 结果已过期"}{line.next_action === "acknowledge_uncertain_submission" ? " · 远程提交结果未知，请在任务区核查" : ""}</p><p dir="auto">{line.recognition?.segments.map(row => row.text).join("") || "尚无识别文字。"}</p></> : <p role="status">{loaded ? "当前任务未找到此行识别结果，请刷新状态或查看任务区。" : "正在读取当前质检详情…"}</p>}</div>;
}
