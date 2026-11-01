import {captionIssue, type CaptionReceipt} from "./captionTypes";
import type {Artifact, Delivery} from "./finishingTypes";
import {languageName} from "./targetTypes";
export function burnReceipt(video: Artifact | null | undefined): CaptionReceipt | null {const receipt = video?.metadata.captions; return receipt && typeof receipt === "object" && receipt.mode === "burn_in" ? receipt : null;}
const tagName = (tag?: string | null) => tag && /^[A-Za-z0-9-]{2,40}$/.test(tag) ? languageName(tag) : "待核对语言";
export default function CaptionResult({delivery, video}: {delivery: Delivery; video: Artifact | null | undefined}) {
  const receipt = burnReceipt(video), options = delivery.choices.caption_options, proof = delivery.manifest_valid ? delivery.caption_status : null;
  const formats = options ? options.formats.filter(format => ["srt", "vtt", "ass"].includes(format)).map(format => format.toUpperCase()).join(" / ") : delivery.choices.captions === "sidecar" ? "SRT / VTT" : "无";
  const fonts = Array.isArray(proof?.fonts) ? proof.fonts.slice(0, 16).flatMap(font => typeof font.family === "string" && /^[\p{L}\p{N} .()_-]{1,100}$/u.test(font.family) ? [font.family] : []) : [];
  const issue = captionIssue(delivery.error);
  return <div className="caption-result"><p className="muted">字幕文件设置：{formats || "无"}。{receipt ? `画面已烧录${receipt.track === "bilingual" ? `源语与${tagName(receipt.target_track)}双语` : receipt.track === "target" ? tagName(receipt.target_track) : receipt.track === "source" ? "源语字幕" : "字幕（内容待核对）"}，无法关闭。` : options?.burn_in ? "已请求烧录，尚无带烧录信息的视频产物。" : "该导出未请求画面烧录。"}</p>
    {receipt && typeof receipt.font_size === "number" && Number.isSafeInteger(receipt.font_size) && receipt.font_size >= 12 && receipt.font_size <= 96 && <p className="muted">烧录基准字号 {receipt.font_size}（720p），{receipt.style === "outlined" ? "白字描边" : "样式待核对"}。</p>}
    {proof && Number.isSafeInteger(proof.glyph_count) && proof.glyph_count >= 0 && proof.glyph_count <= 2000000 && <p className="muted">此次字形核查：{proof.glyph_count} 个字形{fonts.length ? `；本次字体：${fonts.join("、")}` : "；字体信息待核对"}。</p>}
    {issue && <p className="error" role="alert">{issue}</p>}
  </div>;
}
