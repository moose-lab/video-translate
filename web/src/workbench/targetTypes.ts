import type {Segment, Timeline} from "./types";
export type Translation = {revision: number; revision_id?: string; text: string; locked: boolean; approved: boolean; stale: boolean; needs_review: boolean; source_text_fingerprint: string};
export type LanguageTrack = {id?: string; tag: string; revision: number; mode: "Fast" | "Cinematic" | "Autofit"; archived: boolean; materialized: boolean};
export type SourceGuard = {selection_revision: number; transcript_revision: string};
export type TranslationGuard = SourceGuard & {revision: number; expected_source_text_fingerprint: string};
export type TargetDraft = TranslationGuard & {text: string; locked: boolean; approved: boolean};
export type TranslationCommand = {id: string; target_language: string; mode: string; status: string; next_action: string | null; phases: {id: string; phase: string; status: string; run_id: string}[]; suggestions: {phase_id: string; segment_id: string; text: string; estimated: boolean; stale: boolean; applied: boolean; estimated_duration_ms?: number | null}[]; skipped_ids: string[]};
export const targetPath = (project: string, tag: string) => `/projects/${encodeURIComponent(project)}/language-tracks/${encodeURIComponent(tag)}`;
export function sourceGuard(timeline: Timeline): SourceGuard | null {return timeline.source && timeline.transcript && !timeline.source.stale && !timeline.transcript.stale ? {selection_revision: timeline.source.revision, transcript_revision: timeline.transcript.id} : null;}
export function rowGuard(timeline: Timeline, row: Segment): TranslationGuard | null {const source = sourceGuard(timeline); return source && row.source_text_fingerprint ? {...source, revision: row.translation?.revision ?? 0, expected_source_text_fingerprint: row.source_text_fingerprint} : null;}
export function languageName(tag: string): string {try {return new Intl.DisplayNames(["zh"], {type: "language"}).of(tag) ?? tag;} catch {return tag;}}
export const phaseName = (phase: string) => ({context: "提炼完整语境", draft: "生成译文", refine: "润色译文", shorten: "生成精简建议"}[phase] ?? "翻译处理");
