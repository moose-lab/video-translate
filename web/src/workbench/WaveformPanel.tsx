import {useEffect, useState} from "react";
import {api} from "../api/client";
import {projectPath} from "../api/projects";
type WaveformGuard = {selection_revision: number; transcript_revision: string | null};
import {statusName, seconds} from "./types";
import {useAction} from "./useAction";

type Bin = {start_sample: number; end_sample: number; min: number; max: number; rms: number};
type Envelope = {policy: string; sample_rate: number; channels: number; sample_count: number; duration_ms: number; bin_count: number; bins: Bin[]; clock: string; provenance: {source_start_ms: number; source_end_ms: number; selection_revision: number; transcript_revision: string | null; output_id?: string}};
type Job = {id: string; run_id: string; kind: string; output_id: string | null; current: boolean; status: string; artifact: unknown; waveform: unknown; error: unknown};
type Discovery = {source: {available: boolean}; natural_voice: {output_id: string}[]; items: Job[]};
function validEnvelope(value: unknown, source: WaveformGuard, outputId?: string): value is Envelope {
  if (!value || typeof value !== "object") return false;
  const data = value as Envelope;
  if (data.policy !== "pcm-envelope-v1" || !Number.isSafeInteger(data.sample_rate) || data.sample_rate < 8000 || data.sample_rate > 192000 || !Number.isSafeInteger(data.channels) || data.channels < 1 || data.channels > 8 || !Number.isSafeInteger(data.sample_count) || data.sample_count < 1 || !Number.isFinite(data.duration_ms) || data.duration_ms <= 0 || Math.abs(data.duration_ms - data.sample_count / data.sample_rate * 1000) > 1 || !Number.isSafeInteger(data.bin_count) || data.bin_count < 1 || data.bin_count > 2000 || data.bin_count > data.sample_count || !Array.isArray(data.bins) || data.bins.length !== data.bin_count) return false;
  if (data.clock !== (outputId ? "natural_audio_relative" : "source_selection_relative") || data.provenance?.selection_revision !== source.selection_revision || data.provenance?.transcript_revision !== source.transcript_revision || (outputId && data.provenance.output_id !== outputId)) return false;
  if (!outputId && (!Number.isFinite(data.provenance.source_start_ms) || !Number.isFinite(data.provenance.source_end_ms) || data.provenance.source_start_ms < 0 || Math.abs(data.provenance.source_end_ms - data.provenance.source_start_ms - data.duration_ms) > 1)) return false;
  let end = 0;
  for (const [index, bin] of data.bins.entries()) {if (!bin || !Number.isSafeInteger(bin.start_sample) || !Number.isSafeInteger(bin.end_sample) || bin.start_sample !== Math.floor(index * data.sample_count / data.bin_count) || bin.end_sample !== Math.floor((index + 1) * data.sample_count / data.bin_count) || bin.start_sample !== end || bin.end_sample <= end || bin.end_sample > data.sample_count || ![bin.min, bin.max, bin.rms].every(Number.isFinite) || bin.min < -1 || bin.max > 1 || bin.min > bin.max || bin.rms < 0 || bin.rms > Math.max(Math.abs(bin.min), Math.abs(bin.max)) + 1e-12) return false; end = bin.end_sample;}
  return end === data.sample_count;
}
export default function WaveformPanel({projectId, source, csrf, outputId, dirty = false, refreshVersion = 0, onSeek}: {projectId: string; source: WaveformGuard; csrf: string; outputId?: string; dirty?: boolean; refreshVersion?: number; onSeek: (milliseconds: number) => void}) {
  const [open, setOpen] = useState(false), [reload, setReload] = useState(0), [loading, setLoading] = useState(false), [readError, setReadError] = useState(""), [job, setJob] = useState<Job | null>(null), [available, setAvailable] = useState(false), [position, setPosition] = useState(0);
  const {busy, error, perform} = useAction(), path = `${projectPath(projectId)}/waveforms`, kind = outputId ? "natural_voice" : "source", label = outputId ? "自然配音" : "源音频";
  useEffect(() => {
    if (!open) return;
    const controller = new AbortController(); setLoading(true); setReadError(""); setJob(null); setAvailable(false);
    (async () => {
      const discovery = await api<Discovery>(path, {signal: controller.signal});
      if (controller.signal.aborted) return;
      setAvailable(outputId ? discovery.natural_voice.some(item => item.output_id === outputId) : discovery.source.available);
      const matching = discovery.items.filter(item => item.kind === kind && item.output_id === (outputId ?? null));
      const found = matching.find(item => item.current) ?? matching[0];
      if (found) {const detail = found.status === "succeeded" && found.artifact ? await api<Job>(`${path}/${encodeURIComponent(found.id)}`, {signal: controller.signal}) : found; if (!controller.signal.aborted) setJob(detail);}
    })().catch(() => {if (!controller.signal.aborted) setReadError("波形读取失败，请刷新重试。");}).finally(() => {if (!controller.signal.aborted) setLoading(false);});
    return () => controller.abort();
  }, [open, reload, path, outputId, kind, source.selection_revision, source.transcript_revision, refreshVersion]);
  const envelope = job?.current && validEnvelope(job.waveform, source, outputId) ? job.waveform : null;
  async function calculate() {const result = await perform(async signal => {
    const admitted = await api<Job>(path, {method: "POST", signal, body: JSON.stringify({guard: source, kind, ...(outputId ? {output_id: outputId} : {}), bins: 600})}, csrf);
    return admitted.status === "succeeded" && admitted.artifact ? api<Job>(`${path}/${encodeURIComponent(admitted.id)}`, {signal}) : admitted;
  }); if (result) setJob(result);}
  async function action(action: "cancel" | "retry") {if (!job) return; const result = await perform(signal => api(`/runs/${encodeURIComponent(job.run_id)}/${action}`, {method: "POST", signal, ...(action === "retry" ? {body: JSON.stringify({acknowledge_uncertain_submission: false})} : {})}, csrf)); if (result) setReload(value => value + 1);}
  return <div className="waveform-panel"><button className="link" aria-expanded={open} onClick={() => setOpen(!open)}>查看{label}波形</button>{open && <div>
    <p className="muted">服务器实测 PCM 最小值、最大值与 RMS；波形不代表拟合完成或试听已接受。</p>
    {loading && <p role="status">正在读取波形…</p>}{job && <p role="status">波形：{statusName(job.status)}{!job.current ? " · 输入已过期" : ""}</p>}
    {envelope && <><p className="muted">{envelope.sample_rate} Hz · {envelope.channels} 声道 · {envelope.sample_count} 采样帧</p><p className="muted">{outputId ? "从此行自然音频的 0 秒开始；尚未进行时长拟合。" : `片段内 0 秒对应原片 ${seconds(envelope.provenance.source_start_ms)} 秒`}</p>
      <svg role="img" aria-label={`实测${label}波形`} viewBox="0 0 1000 100" width="100%" height="100" preserveAspectRatio="none"><title>{label}实测峰值包络和 RMS</title>{envelope.bins.map((bin, index) => {const x = bin.start_sample / envelope.sample_count * 1000, width = (bin.end_sample - bin.start_sample) / envelope.sample_count * 1000; return <g key={index}><rect className="waveform-envelope" x={x} y={50 - bin.max * 45} width={width} height={Math.max(.1, (bin.max - bin.min) * 45)} fill="currentColor" opacity=".35"/><rect className="waveform-rms" x={x} y={50 - bin.rms * 45} width={width} height={Math.max(.1, bin.rms * 90)} fill="currentColor"/></g>;})}</svg>
      <label>{label}波形播放位置<input type="range" min={0} max={envelope.duration_ms} step={1} value={Math.min(position, envelope.duration_ms)} onChange={event => {const value = Number(event.target.value); setPosition(value); onSeek(value + (outputId ? 0 : envelope.provenance.source_start_ms));}} /></label><p className="muted">片段内 {seconds(position)} / {seconds(envelope.duration_ms)} 秒</p></>}
    {job?.status === "succeeded" && !envelope && <p className="error" role="alert">波形不可用或输入已变化，请重新读取或计算。</p>}
    {!loading && !available && <p className="muted">{outputId ? "当前行自然音频尚不可用。" : "请先完成当前源片段的音轨提取，准备工作 PCM 音频。"}</p>}
    <div className="actions"><button className="link" disabled={loading || busy} onClick={() => setReload(value => value + 1)}>刷新{label}波形</button><button className="secondary" disabled={loading || busy || dirty || !available || !!job && ["queued", "running", "retry_wait"].includes(job.status)} onClick={() => void calculate()}>计算{label}波形</button>{job && ["queued", "running", "retry_wait"].includes(job.status) && <button className="secondary" disabled={busy} onClick={() => void action("cancel")}>取消波形任务</button>}{job && job.current && ["failed", "cancelled"].includes(job.status) && <button className="secondary" disabled={busy || dirty} onClick={() => void action("retry")}>重试波形任务</button>}</div>
    {readError && <p className="error" role="alert">{readError}</p>}{error && <p className="error" role="alert">{error}</p>}
  </div>}</div>;
}
