import {useEffect, useState} from "react";
import {api, ApiError} from "../api/client";
import {projectPath, type Page} from "../api/projects";
import type {Timeline} from "./types";
import {statusName} from "./types";
import {sourceGuard, languageName} from "./targetTypes";
import {purposeName, type Delivery, type FitDetail, type FitSummary, type SettingsResponse} from "./finishingTypes";
import {captureFitInputs, type FitCapture} from "./fitCapture";
import {useAction} from "./useAction";
import FitSettingsForm from "./FitSettingsForm";
import FitPlanView from "./FitPlanView";
import DeliveryForm from "./DeliveryForm";
type Props = {projectId: string; csrf: string; refreshVersion: number; targetLanguages: string[]; sourceTimeline: Timeline; onDelivery: (value: Delivery) => void};
export default function FitWorkspace({projectId, csrf, refreshVersion, targetLanguages, sourceTimeline, onDelivery}: Props) {
  const [settings, setSettings] = useState<SettingsResponse | null>(null), [plans, setPlans] = useState<Page<FitSummary>>({items: [], total: 0}), [offset, setOffset] = useState(0), [version, setVersion] = useState(0), [loadError, setLoadError] = useState("");
  const [selected, setSelected] = useState(() => {const value = new URLSearchParams(window.location.hash.split("?")[1]).get("fit"); return value && /^[A-Za-z0-9-]{1,36}$/.test(value) ? value : "";}), [plan, setPlan] = useState<FitDetail | null>(null);
  const [tags, setTags] = useState<string[]>(targetLanguages.includes("zh") ? ["zh"] : targetLanguages.slice(0, 1)), [purpose, setPurpose] = useState<"dub" | "incomplete_preview">("incomplete_preview"), [capture, setCapture] = useState<(FitCapture & {purpose: "dub" | "incomplete_preview"}) | null>(null), [settingsDirty, setSettingsDirty] = useState(false);
  const {busy, error, perform} = useAction(), path = projectPath(projectId), source = sourceGuard(sourceTimeline), revision = refreshVersion + version;
  function reload() {setVersion(value => value + 1);}
  useEffect(() => {
    let active = true; const controller = new AbortController();
    Promise.all([api<SettingsResponse>(`${path}/fit-settings?limit=1&offset=0`, {signal: controller.signal}), api<Page<FitSummary>>(`${path}/fit-plans?limit=50&offset=${offset}`, {signal: controller.signal})]).then(([settings, plans]) => {if (active) {setSettings(settings); setPlans(plans); setSelected(previous => previous || plans.items[0]?.id || ""); setLoadError("");}}).catch(error => {if (active) setLoadError(error instanceof ApiError ? error.message : "拟合设置或方案列表加载失败。");});
    return () => {active = false; controller.abort();};
  }, [path, offset, revision]);
  useEffect(() => {
    if (!selected) return; let active = true; const controller = new AbortController();
    api<FitDetail>(`${path}/fit-plans/${encodeURIComponent(selected)}?limit=100&offset=0`, {signal: controller.signal}).then(value => {if (active) {setPlan(value); setLoadError("");}}).catch(error => {if (active) setLoadError(error instanceof ApiError ? error.message : "拟合方案加载失败。");});
    return () => {active = false; controller.abort();};
  }, [path, selected, revision]);
  function select(id: string) {setSelected(id); setPlan(null); const [base, query] = window.location.hash.split("?"); const params = new URLSearchParams(query); params.set("fit", id); window.history.replaceState(null, "", `${base || `#/projects/${projectId}`}?${params}`);}
  async function readInputs() {if (!source || !settings || !tags.length || settingsDirty) return; const result = await perform(signal => captureFitInputs(projectId, tags, settings.revision, source, signal)); if (result) setCapture({...result, purpose});}
  async function createPlan() {if (!capture || settingsDirty) return; const result = await perform(signal => api<FitDetail>(`${path}/fit-plans`, {method: "POST", signal, body: JSON.stringify(capture)}, csrf)); if (result) {setSelected(result.id); setPlan(result); reload();}}
  return <div className="fit-workspace">{loadError && <p className="error" role="alert">{loadError} <button className="link" onClick={reload}>重新读取拟合状态</button></p>}
    {settings ? <><FitSettingsForm projectId={projectId} csrf={csrf} data={settings} onDirty={setSettingsDirty} onSaved={() => {setCapture(null); reload();}} />
      <div className="fit-capture"><h3>生成拟合方案</h3><label>拟合用途<select value={purpose} disabled={busy} onChange={event => {setPurpose(event.target.value as typeof purpose); setCapture(null);}}><option value="incomplete_preview">未完成试听预览</option><option value="dub">正式配音（所有行已接受）</option></select></label>
        <fieldset disabled={busy}><legend>拟合语言（最多 16 种）</legend>{targetLanguages.map(tag => <label key={tag} className="check-label"><input type="checkbox" checked={tags.includes(tag)} disabled={!tags.includes(tag) && tags.length >= 16} onChange={event => {setTags(previous => event.target.checked ? [...previous, tag] : previous.filter(value => value !== tag)); setCapture(null);}} />{languageName(tag)} · {tag}</label>)}</fieldset>
        <p className="muted">先读取所选语言的全部台词、当前音频与听审版本，再明确提交拟合。读取后不会随实时更新自动替换已读取的版本。</p>
        {!source && <p className="muted">当前源字幕尚未就绪或已过期。</p>}{settingsDirty && <p className="muted">请先保存或放弃拟合设置修改。</p>}
        <div className="actions"><button className="secondary" disabled={busy || !source || !tags.length || settingsDirty} onClick={() => void readInputs()}>读取拟合输入</button><button className="secondary" disabled={busy || !capture || settingsDirty} onClick={() => void createPlan()}>生成拟合方案</button></div>
        {capture && <p className="notice">已读取 {capture.tracks.reduce((total, track) => total + track.segments.length, 0)} 行 · {purposeName(capture.purpose)}。如遇版本冲突，修改仍保留，请明确重新读取后再提交。</p>}
      </div>
    </> : !loadError && <p role="status">正在读取拟合设置…</p>}
    {plans.items.length > 0 && <label>已有拟合方案<select value={selected} onChange={event => select(event.target.value)}>{plans.items.map((item, index) => <option key={item.id} value={item.id}>方案 {offset + index + 1} · {purposeName(item.purpose)} · {statusName(item.status)}</option>)}</select></label>}
    {plans.total > 50 && <nav className="actions pagination" aria-label="拟合方案分页"><button className="secondary" disabled={!offset} onClick={() => {setOffset(Math.max(0, offset - 50)); setSelected(""); setPlan(null);}}>上一页方案</button><button className="secondary" disabled={offset + 50 >= plans.total} onClick={() => {setOffset(offset + 50); setSelected(""); setPlan(null);}}>下一页方案</button></nav>}
    {plan && <><FitPlanView key={plan.id} plan={plan} /><DeliveryForm key={plan.id} projectId={projectId} csrf={csrf} plan={plan} onCreated={onDelivery} /></>}{error && <p className="error" role="alert">{error}</p>}
  </div>;
}
