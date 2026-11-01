import type {SourceGuard} from "./targetTypes";
export type VoiceControls = {ns: number; gs: number; dn: boolean; sp: number; du: number | null; pp: boolean; po: boolean};
export type VoiceSettings = {revision: number; override: boolean; controls: VoiceControls; history: {id: string; revision: number; override: boolean; controls: VoiceControls; created_at: string}[]; total: number};
export type VoiceValues = Omit<VoiceControls, "ns" | "gs" | "sp" | "du"> & {ns: string; gs: string; sp: string; du: string};
export type VoiceDraft = {revision: number; source: SourceGuard; override: boolean; values: VoiceValues};
export const voiceValues = (controls: VoiceControls): VoiceValues => ({...controls, ns: String(controls.ns), gs: String(controls.gs), sp: String(controls.sp), du: controls.du === null ? "" : String(controls.du)});
export function parsedVoiceControls(values: VoiceValues): VoiceControls | null {
  const ns = Number(values.ns), gs = Number(values.gs), sp = Number(values.sp), du = values.du.trim() === "" ? null : Number(values.du);
  return values.ns.trim() && values.gs.trim() && values.sp.trim() && Number.isInteger(ns) && ns >= 4 && ns <= 64 && Number.isFinite(gs) && gs >= 0 && gs <= 4 && Number.isFinite(sp) && sp >= 0.5 && sp <= 1.5 && (du === null || Number.isFinite(du) && du >= 0.01 && du <= 10000) ? {...values, ns, gs, sp, du} : null;
}
