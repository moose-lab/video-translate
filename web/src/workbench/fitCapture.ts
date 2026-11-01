import {api, ApiError} from "../api/client";
import {projectPath} from "../api/projects";
import type {AudioPage} from "./audioTypes";
import type {Timeline} from "./types";
import {sourceGuard, targetPath, type SourceGuard} from "./targetTypes";
export type FitCell = {id: string; expected_source_revision_id: string; expected_source_text_fingerprint: string; translation_revision: number; selection_revision: number; output_id: string | null; review_revision: number; qc_evidence_fingerprint: string | null};
export type FitCapture = SourceGuard & {settings_revision: number; tracks: {tag: string; segments: FitCell[]}[]};
export async function captureFitInputs(projectId: string, tags: string[], revision: number, source: SourceGuard, signal: AbortSignal): Promise<FitCapture> {
  const tracks: FitCapture["tracks"] = []; let count = 0;
  for (const tag of tags) {
    const rows: Timeline["segments"] = [], audios: AudioPage["items"] = [];
    for (let offset = 0; offset < 1000; offset += 200) {
      const params = new URLSearchParams({target_language: tag, limit: "200", offset: String(offset)});
      const page = await api<Timeline>(`${projectPath(projectId)}/timeline?${params}`, {signal});
      const guard = sourceGuard(page);
      if (!guard || guard.selection_revision !== source.selection_revision || guard.transcript_revision !== source.transcript_revision) throw new ApiError(409, "源数据已变化，请重新读取拟合输入。", "REVISION_CONFLICT");
      if (page.total + count > 1000) throw new ApiError(422, "一次拟合最多包含 1000 个语言与台词组合，请减少选择范围。");
      rows.push(...page.segments); if (rows.length >= page.total) break;
      if (!page.segments.length) throw new ApiError(409, "源字幕分页已变化，请重新读取。");
    }
    for (let offset = 0; offset < 1000; offset += 100) {
      const page = await api<AudioPage>(`${targetPath(projectId, tag)}/synthesis?limit=100&offset=${offset}`, {signal});
      audios.push(...page.items); if (audios.length >= page.total) break;
      if (!page.items.length) throw new ApiError(409, "配音分页已变化，请重新读取。");
    }
    const segments = rows.map(row => {
      const audio = audios.find(item => item.segment_id === row.id);
      if (!audio || !row.revision_id || !row.source_text_fingerprint) throw new ApiError(409, "当前字幕或音频版本信息不完整，请刷新后重新读取。");
      return {id: row.id, expected_source_revision_id: row.revision_id, expected_source_text_fingerprint: row.source_text_fingerprint, translation_revision: row.translation?.revision ?? 0, selection_revision: audio.selection_revision, output_id: audio.selected?.id ?? null, review_revision: audio.selected?.review_revision ?? 0, qc_evidence_fingerprint: audio.selected?.qc_evidence_fingerprint ?? null};
    });
    if (!segments.length) throw new ApiError(409, "当前语言没有可拟合的源字幕。");
    count += segments.length; tracks.push({tag, segments});
  }
  return {...source, settings_revision: revision, tracks};
}
