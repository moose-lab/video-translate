export type ImportGuard = {selection_revision: number; transcript_revision: string | null};
export type ImportFormat = "srt" | "vtt" | "numbered";
export type Cue = {id: string; index: number; number: number | null; start_ms: number | null; end_ms: number | null; text: string; voice_label: string | null; warnings: string[]; errors: string[]; proposed_matches: {segment_id: string; source_number: number; source_revision: number; revision: number; locked: boolean}[]};
export type ImportReview = ImportGuard & {digest: string; cues: Cue[]; conflicts: {cue_id: string; code: string}[]};
export type CueMapping = {cue_id: string; segment_id: string | null; revision: number; speaker_id?: string | null; use_voice_label?: boolean};
