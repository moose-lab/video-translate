import {useState} from "react";
import {api} from "../api/client";
import {projectPath} from "../api/projects";
import {languageName} from "./targetTypes";
import {purposeName, type Delivery, type FitDetail} from "./finishingTypes";
import {useAction} from "./useAction";
export default function DeliveryForm({projectId, csrf, plan, onCreated}: {projectId: string; csrf: string; plan: FitDetail; onCreated: (value: Delivery) => void}) {
  const [frameRate, setFrameRate] = useState("30/1"), [background, setBackground] = useState("1"), [voice, setVoice] = useState("1"), [comparison, setComparison] = useState(true), [captions, setCaptions] = useState("sidecar"), [defaultTrack, setDefaultTrack] = useState(plan.tracks[0]?.tag ?? "original"), [ack, setAck] = useState(false);
  const {busy, error, perform} = useAction(), choices = [...plan.tracks.map(track => track.tag), ...(comparison ? ["original"] : [])];
  const gainValid = background !== "" && voice !== "" && [Number(background), Number(voice)].every(value => Number.isFinite(value) && value >= 0 && value <= 4);
  const eligible = plan.current && plan.status === "succeeded" && plan.timeline_feasible && !!plan.plan && (plan.purpose !== "dub" || plan.dub_ready);
  const valid = eligible && gainValid && choices.includes(defaultTrack) && (plan.purpose !== "incomplete_preview" || ack);
  async function create() {
    if (!valid) return;
    const [numerator, denominator] = frameRate.split("/").map(Number);
    const result = await perform(signal => api<Delivery>(`${projectPath(projectId)}/deliveries`, {method: "POST", signal, body: JSON.stringify({fit_plan_id: plan.id, expected_fit_run_id: plan.run_id, purpose: plan.purpose, frame_rate: {numerator, denominator}, background_gain: Number(background), voice_gain: Number(voice), include_original_comparison: comparison, default_audio_track: defaultTrack, captions})}, csrf));
    if (result) onCreated(result);
  }
  return <div className="delivery-form"><h3>创建导出 · {purposeName(plan.purpose)}</h3>{!eligible && <p className="error">此方案尚未就绪、已过期或不满足正式配音要求，请先核对拟合与听审状态。</p>}
    <div className="settings-fields"><label>输出帧率<select value={frameRate} disabled={busy} onChange={event => setFrameRate(event.target.value)}>{[["24/1", "24"], ["25/1", "25"], ["30/1", "30"], ["50/1", "50"], ["60/1", "60"], ["24000/1001", "23.976"], ["30000/1001", "29.970"], ["60000/1001", "59.940"]].map(([value, label]) => <option key={value} value={value}>{label} fps</option>)}</select></label>
      <label>背景音量倍数<input type="number" min={0} max={4} step={0.1} value={background} disabled={busy} onChange={event => setBackground(event.target.value)} /></label><label>配音音量倍数<input type="number" min={0} max={4} step={0.1} value={voice} disabled={busy} onChange={event => setVoice(event.target.value)} /></label>
      <label>字幕输出<select value={captions} disabled={busy} onChange={event => setCaptions(event.target.value)}><option value="sidecar">独立 SRT/VTT 文件</option><option value="none">不输出字幕</option></select></label>
      <label>默认音轨<select value={defaultTrack} disabled={busy} onChange={event => setDefaultTrack(event.target.value)}>{choices.map(tag => <option key={tag} value={tag}>{tag === "original" ? "重定时原声" : languageName(tag)}</option>)}</select></label>
    </div><label className="check-label"><input type="checkbox" checked={comparison} disabled={busy || plan.purpose === "original_only"} onChange={event => {setComparison(event.target.checked); if (!event.target.checked && defaultTrack === "original") setDefaultTrack(plan.tracks[0]?.tag ?? "");}} />包含重定时原声对照音轨</label>
    {plan.purpose === "incomplete_preview" && <label className="check-label"><input type="checkbox" checked={ack} disabled={busy} onChange={event => setAck(event.target.checked)} />我了解这是未完成试听预览，可能仍有未接受的配音或质检风险</label>}
    <p className="muted">点击后开始画面处理、混音与文件导出。画面和原声对照按同一拟合时间映射处理；字幕不会烧录到画面。</p><button disabled={busy || !valid} onClick={() => void create()}>{busy ? "正在提交导出…" : "创建导出"}</button>{error && <p className="error" role="alert">{error}</p>}
  </div>;
}
