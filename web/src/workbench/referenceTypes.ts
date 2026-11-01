export type Speaker = {id: string; selection_id: string; name: string; description: string; revision: number; archived: boolean};
export type ReferenceVersion = {id: string; reference_id: string; audio_asset_id: string; text: string; language: string; duration_ms: number; flags: string[]; stale: boolean; origin: string; source_segment_id?: string | null; absolute_start_ms?: number | null; absolute_end_ms?: number | null};
export type ReferenceBinding = {revision: number; reference_version_id: string | null};
export const referenceWarning = (value: string) => ({short: "参考音较短", long: "参考音较长", overlap: "含重叠说话", silence: "含较多静音"}[value] ?? "需要人工检查");
