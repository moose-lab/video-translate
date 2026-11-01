import type {Timeline} from "./types";
import {seconds} from "./types";
export default function TranscriptPanel({timeline, offset, onOffset, updating}: {timeline: Timeline; offset: number; onOffset: (value: number) => void; updating: boolean}) {
  return <section className="panel" aria-labelledby="transcript-title"><div className="section-head"><h2 id="transcript-title">源字幕与角色</h2><span className="status">{timeline.transcript ? timeline.transcript.stale ? "源字幕已过期" : "待人工核对" : "尚未生成"}</span></div>
    {timeline.transcript && <p className="muted">共 {timeline.total} 行{timeline.transcript.detected_language ? ` · 检测语言 ${timeline.transcript.detected_language}` : ""}。角色名称是工作标签，请按原片核对。</p>}
    {timeline.cast.length > 0 && <p className="cast-labels">角色：{timeline.cast.filter(role => !role.archived).map(role => <span className="status" key={role.id}><bdi dir="auto">{role.name}</bdi></span>)}{timeline.cast_total > timeline.cast.length && <span>已显示 {timeline.cast.length} / {timeline.cast_total} 个角色</span>}</p>}
    {timeline.segments.length === 0 ? <p className="muted">当前没有源字幕。保存源片段后，可明确启动源分析。</p> : <ol className="transcript-list" start={offset + 1}>{timeline.segments.map(segment => <li key={segment.id}><div className="transcript-meta"><span>{seconds(segment.absolute_start_ms)}–{seconds(segment.absolute_end_ms)} 秒（原片）</span><span><bdi dir="auto">{timeline.cast.find(role => role.id === segment.speaker_id)?.name ?? segment.original_speaker_label ?? "未分配角色"}</bdi></span></div><p dir="auto">{segment.text}</p></li>)}</ol>}
    {timeline.total > 50 && <nav className="actions pagination" aria-label="源字幕分页"><button className="secondary" disabled={!offset || updating} onClick={() => onOffset(Math.max(0, offset - 50))}>上一页字幕</button><span>{offset + 1}–{Math.min(offset + 50, timeline.total)} / {timeline.total}</span><button className="secondary" disabled={offset + 50 >= timeline.total || updating} onClick={() => onOffset(offset + 50)}>下一页字幕</button></nav>}
  </section>;
}
