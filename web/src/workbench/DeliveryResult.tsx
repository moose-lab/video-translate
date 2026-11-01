import CaptionResult, {burnReceipt} from "./CaptionResult";
import {useState} from "react";
import {safeCode, safeFailureMessage} from "../api/client";
import {languageName} from "./targetTypes";
import {seconds, statusName} from "./types";
import {purposeName, type Artifact, type Delivery} from "./finishingTypes";
const assetUrl = (artifact: Artifact) => /^[A-Za-z0-9-]{1,36}$/.test(artifact.asset_id) ? `/api/assets/${artifact.asset_id}/content` : null;
const trackName = (tag: string) => ({all: "多音轨视频", original: "重定时原声", source: "源字幕"}[tag] ?? languageName(tag));
export default function DeliveryResult({delivery}: {delivery: Delivery}) {
  const [playbackError, setPlaybackError] = useState(false);
  const video = delivery.manifest_valid ? delivery.artifacts.find(artifact => artifact.format === "mp4" && assetUrl(artifact)) : null;
  const duration = video?.metadata.duration_ms, burned = !!burnReceipt(video);
  const subtitles = delivery.manifest_valid ? delivery.artifacts.filter(artifact => artifact.format === "vtt" && artifact.content_type === "text/vtt" && assetUrl(artifact)) : [];
  const defaultSubtitle = subtitles.find(artifact => artifact.track === delivery.choices.default_audio_track) ?? subtitles.find(artifact => artifact.track === "source");
  return <div className="delivery-result"><h3>{purposeName(delivery.purpose)}</h3><p role="status">{statusName(delivery.status)}{delivery.phase ? ` · ${{render: "画面处理", mix: "混音", export: "导出"}[delivery.phase] ?? "处理中"}` : ""}</p>
    {!delivery.current && <p className="error">输入已变化，此结果属于历史版本；请核对后再使用。</p>}
    {!delivery.manifest_valid && <p className="error">导出文件校验未通过，暂不提供文件。</p>}
    <p className="muted">源窗口 {seconds(delivery.source_window.end_ms - delivery.source_window.start_ms)} 秒{typeof duration === "number" ? `；输出 ${seconds(duration)} 秒` : "；输出时长尚未确认"}。画面与对照原声使用同一时间映射，对照原声也经过重定时。</p>
    {delivery.purpose === "incomplete_preview" && <p className="muted">此为未完成预览，可能包含尚未接受的配音，不代表正式成片已通过听审。</p>}
    {video && <><video key={video.asset_id} controls preload="metadata" aria-label="导出视频预览" src={assetUrl(video)!} onError={() => setPlaybackError(true)} onLoadedData={() => setPlaybackError(false)}>{subtitles.map(artifact => <track key={artifact.asset_id} kind="subtitles" src={assetUrl(artifact)!} label={trackName(artifact.track)} srcLang={/^[A-Za-z0-9-]{2,40}$/.test(artifact.track) && artifact.track !== "source" ? artifact.track : "und"} default={!burned && artifact.asset_id === defaultSubtitle?.asset_id} />)}</video>{playbackError && <p className="error" role="alert">浏览器无法播放当前导出，或会话已失效。可下载文件后检查。</p>}</>}
    {delivery.artifacts.length > 0 && delivery.manifest_valid ? <ul className="artifact-list">{delivery.artifacts.map(artifact => {const url = assetUrl(artifact); return url && <li key={artifact.asset_id}><a href={url} download>下载 {trackName(artifact.track)} · {artifact.format.toUpperCase()}</a><span className="muted">{artifact.byte_size.toLocaleString()} 字节</span></li>;})}</ul> : <p className="muted">尚无可下载文件，等待任务实际完成。</p>}
    <CaptionResult delivery={delivery} video={video} /><p className="muted">默认音轨：{trackName(delivery.choices.default_audio_track)}。</p>
    {delivery.error && <p className="error" role="alert">{safeFailureMessage(delivery.error.code)} ({safeCode(delivery.error.code)})</p>}
  </div>;
}
