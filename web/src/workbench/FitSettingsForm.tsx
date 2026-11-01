import {useEffect, useState} from "react";
import {api} from "../api/client";
import {projectPath} from "../api/projects";
import {rateValue, type FitSettings, type Rate, type SettingsResponse} from "./finishingTypes";
import {useAction} from "./useAction";
const rateKey = (rate: Rate) => `${rate.numerator}/${rate.denominator}`;
const parseRate = (value: string): Rate => {const [numerator, denominator] = value.split("/").map(Number); return {numerator, denominator};};
function RateSelect({label, value, values, disabled, onChange}: {label: string; value: Rate; values: string[]; disabled: boolean; onChange: (rate: Rate) => void}) {
  return <label>{label}<select value={rateKey(value)} disabled={disabled} onChange={event => onChange(parseRate(event.target.value))}>{[...new Set([rateKey(value), ...values])].map(key => <option value={key} key={key}>×{rateValue(parseRate(key))?.toFixed(2)}</option>)}</select></label>;
}
export default function FitSettingsForm({projectId, csrf, data, onSaved, onDirty}: {projectId: string; csrf: string; data: SettingsResponse; onSaved: () => void; onDirty?: (value: boolean) => void}) {
  const [draft, setDraft] = useState<SettingsResponse | null>(null), {busy, error, perform} = useAction(), settings = draft?.settings ?? data.settings;
  useEffect(() => {onDirty?.(!!draft);}, [draft, onDirty]);
  function edit(change: Partial<FitSettings>) {setDraft(previous => ({revision: previous?.revision ?? data.revision, settings: {...(previous?.settings ?? data.settings), ...change}}));}
  const valid = Number.isInteger(settings.max_borrow_ms) && settings.max_borrow_ms >= 0 && settings.max_borrow_ms <= 60000 && Number.isInteger(settings.max_output_duration_ms) && settings.max_output_duration_ms >= 1 && settings.max_output_duration_ms <= 57600000;
  async function save() {if (!draft || !valid) return; const result = await perform(signal => api<SettingsResponse>(`${projectPath(projectId)}/fit-settings`, {method: "PUT", signal, body: JSON.stringify(draft)}, csrf)); if (result) {setDraft(null); onSaved();}}
  return <div className="fit-settings"><h3>拟合设置</h3><p className="muted">固定画面时长优先调整语速；智能拟合可按上限延长画面。所有目标语言共享同一画面时间映射。</p>
    <div className="settings-fields"><label>拟合方式<select value={settings.mode} disabled={busy} onChange={event => edit({mode: event.target.value as FitSettings["mode"]})}><option value="fixed">固定画面时长</option><option value="smart">智能拟合画面</option></select></label>
      <RateSelect disabled={busy} label="最大语音速度" value={settings.max_audio_speed} values={["1/1", "11/10", "6/5", "3/2", "2/1"]} onChange={rate => edit({max_audio_speed: rate})} />
      <RateSelect disabled={busy} label="最大画面延长倍数" value={settings.max_picture_factor} values={["1/1", "6/5", "3/2", "2/1", "4/1"]} onChange={rate => edit({max_picture_factor: rate})} />
      <label>可借用相邻空白（毫秒）<input type="number" min={0} max={60000} step={1} value={settings.max_borrow_ms} disabled={busy} onChange={event => edit({max_borrow_ms: Number(event.target.value)})} /></label>
      <label>最大输出时长（毫秒）<input type="number" min={1} max={57600000} step={1} value={settings.max_output_duration_ms} disabled={busy} onChange={event => edit({max_output_duration_ms: Number(event.target.value)})} /></label>
    </div><div className="actions"><button className="secondary" disabled={!draft || busy || !valid} onClick={() => void save()}>保存拟合设置</button>{draft && <button className="link" disabled={busy} onClick={() => setDraft(null)}>放弃拟合设置修改</button>}</div>{!valid && <p className="error">请填写允许范围内的整数毫秒。</p>}{error && <p className="error" role="alert">{error}</p>}
  </div>;
}
