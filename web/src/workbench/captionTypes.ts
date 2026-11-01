export type CaptionOptions = {formats: ("srt" | "vtt" | "ass")[]; burn_in: boolean; track: "source" | "target" | "bilingual"; target_track?: string; font_profile: "auto" | "sans" | "cjk" | "arabic" | "hebrew"; font_size: number; style: "outlined"};
export const defaultCaptionOptions = (): CaptionOptions => ({formats: ["srt", "vtt"], burn_in: false, track: "source", font_profile: "auto", font_size: 42, style: "outlined"});
export function validCaptionOptions(value: CaptionOptions | null, tags: string[]) {return !value || ((value.formats.length > 0 || value.burn_in) && Number.isSafeInteger(value.font_size) && value.font_size >= 12 && value.font_size <= 96 && (value.track === "source" ? !value.target_track : !!value.target_track && tags.includes(value.target_track)));}
export type FontFact = {family: string; face?: number; sha256?: string; glyph_count?: number; glyphs_sha256?: string};
export type CaptionReceipt = {mode: string; track: string; target_track?: string | null; font_size?: number; style?: string; fonts?: FontFact[]};
export type CaptionProof = {fonts: FontFact[]; glyph_count: number; options?: CaptionOptions; cue_manifest_sha256?: string};
export function captionIssue(error: {issue?: unknown; missing?: unknown} | null | undefined): string {
  const messages: Record<string, string> = {FONT_GLYPHS_MISSING: "服务器字体无法覆盖所需字形，请调整字体类别或字幕内容后重新导出。", FONT_UNAVAILABLE: "服务器未找到可用的指定字体类别，字幕尚未完成。", FONT_PROOF_CHANGED: "字幕字体核查结果已变化，请核对服务环境后重新导出。", CAPTION_TRACK_EMPTY: "所选烧录字幕轨没有有效字幕，请检查源字幕与目标语言。", CAPTION_LIMIT: "字幕内容超出当前处理上限。"};
  if (typeof error?.issue !== "string" || !Object.hasOwn(messages, error.issue)) return "";
  const missing = Array.isArray(error.missing) ? error.missing.filter((value): value is string => typeof value === "string" && /^U\+[0-9A-F]{4,6}$/.test(value)).slice(0, 16) : [];
  return messages[error.issue] + (missing.length ? ` 缺少字形：${missing.join("、")}${Array.isArray(error.missing) && error.missing.length > missing.length ? "（仅显示部分）" : ""}` : "");
}
