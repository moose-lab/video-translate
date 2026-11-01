import {useEffect, useState, type FormEvent} from "react";
import {api, ApiError} from "../api/client";
import {projectPath, type Page} from "../api/projects";
import type {Timeline} from "./types";
import {languageName, sourceGuard, targetPath, type LanguageTrack, type SourceGuard} from "./targetTypes";
import {parsedVoiceControls, voiceValues, type VoiceControls, type VoiceDraft, type VoiceSettings, type VoiceValues} from "./voiceSettingsTypes";
import {useAction} from "./useAction";
type Provider = {adapter?: string; revision?: number; capabilities?: {controls?: string[]}};
type Loaded = {key: string; settings: VoiceSettings; source: SourceGuard | null};
const names: (keyof VoiceControls)[] = ["ns", "gs", "dn", "sp", "du", "pp", "po"];
const equalSource = (a: SourceGuard | null, b: SourceGuard | null) => a?.selection_revision === b?.selection_revision && a?.transcript_revision === b?.transcript_revision;
function Pager({label, offset, total, disabled, onChange}: {label: string; offset: number; total: number; disabled: boolean; onChange: (offset: number) => void}) {
  return total > 50 && <nav className="actions pagination" aria-label={`${label}分页`}><button type="button" className="secondary" disabled={disabled || offset === 0} onClick={() => onChange(Math.max(0, offset - 50))}>上一页{label}</button><span>{offset + 1}–{Math.min(offset + 50, total)} / {total}</span><button type="button" className="secondary" disabled={disabled || offset + 50 >= total} onClick={() => onChange(offset + 50)}>下一页{label}</button></nav>;
}
export default function VoiceSettingsPanel({projectId, csrf, refreshVersion, onChanged}: {projectId: string; csrf: string; refreshVersion: number; onChanged: () => void}) {
  const [tracks, setTracks] = useState<Page<LanguageTrack>>({items: [], total: 0}), [timeline, setTimeline] = useState<Timeline | null>(null), [provider, setProvider] = useState<Provider | null>(null);
  const [trackOffset, setTrackOffset] = useState(0), [rowOffset, setRowOffset] = useState(0), [historyOffset, setHistoryOffset] = useState(0), [tag, setTag] = useState(""), [scope, setScope] = useState("");
  const [loaded, setLoaded] = useState<Loaded | null>(null), [draft, setDraft] = useState<VoiceDraft | null>(null), [loadError, setLoadError] = useState(""), [settingsError, setSettingsError] = useState(""), [loading, setLoading] = useState(false), [version, setVersion] = useState(0), [notice, setNotice] = useState("");
  const {busy, error, perform} = useAction(), path = projectPath(projectId), revision = refreshVersion + version;
  useEffect(() => {
    let active = true; const controller = new AbortController();
    Promise.all([api<Page<LanguageTrack>>(`${path}/language-tracks?limit=50&offset=${trackOffset}`, {signal: controller.signal}), api<Timeline>(`${path}/timeline?limit=50&offset=${rowOffset}`, {signal: controller.signal}), api<{providers: {synthesis?: Provider}}>("/provider-settings", {signal: controller.signal})]).then(([tracks, timeline, settings]) => {
      if (!active) return; setTracks(tracks); setTimeline(timeline); setProvider(settings.providers.synthesis ?? null); setTag(previous => previous || tracks.items.find(track => !track.archived && track.materialized)?.tag || ""); setLoadError("");
    }).catch(error => {if (active) setLoadError(error instanceof ApiError ? error.message : "配音参数范围读取失败，请重试。");});
    return () => {active = false; controller.abort();};
  }, [path, trackOffset, rowOffset, revision]);
  const source = timeline ? sourceGuard(timeline) : null, sourceKey = source ? `${source.selection_revision}/${source.transcript_revision}` : "";
  const settingsPath = tag ? `${targetPath(projectId, tag)}${scope ? `/segments/${encodeURIComponent(scope)}` : ""}/voice-settings` : "", key = `${settingsPath}/${historyOffset}`;
  useEffect(() => {
    if (!settingsPath || !timeline) return;
    let active = true; const controller = new AbortController(); setLoading(true);
    api<VoiceSettings>(`${settingsPath}?limit=50&offset=${historyOffset}`, {signal: controller.signal}).then(settings => {if (active) {setLoaded({key, settings, source}); setSettingsError("");}}).catch(error => {if (active) setSettingsError(error instanceof ApiError ? error.message : "配音参数读取失败，请重试。");}).finally(() => {if (active) setLoading(false);});
    return () => {active = false; controller.abort();};
  }, [settingsPath, historyOffset, sourceKey, revision, !!timeline]);
  const current = loaded?.key === key ? loaded : null, supported = provider?.adapter === "omnivoice" && names.every(name => provider.capabilities?.controls?.includes(name));
  const blocked = !!draft || busy || loading, stale = !!draft && (!equalSource(draft.source, source) || !!current && draft.revision !== current.settings.revision);
  const values = draft?.values ?? (current ? voiceValues(current.settings.controls) : null), override = draft?.override ?? current?.settings.override ?? false;
  const trackAvailable = tracks.items.some(track => track.tag === tag && track.materialized && !track.archived), rowAvailable = !scope || !!timeline?.segments.some(row => row.id === scope);
  function edit(changes: Partial<VoiceValues>, custom = true) {if (!current?.source || busy || loading || !supported) return; setDraft(previous => ({...(previous ?? {revision: current.settings.revision, source: current.source!, override: current.settings.override, values: voiceValues(current.settings.controls)}), override: custom, values: {...(previous?.values ?? voiceValues(current.settings.controls)), ...changes}})); setNotice("");}
  async function save(event: FormEvent) {
    event.preventDefault(); if (!draft || !supported || !trackAvailable || !rowAvailable || busy || loading) return;
    const controls = parsedVoiceControls(draft.values); if (draft.override && !controls) return;
    const result = await perform(signal => api<VoiceSettings>(settingsPath, {method: "PUT", signal, body: JSON.stringify({...draft.source, revision: draft.revision, controls: draft.override ? controls : null})}, csrf));
    if (result) {setLoaded({key, settings: result, source: draft.source}); setDraft(null); setNotice("配音参数已保存；后续生成使用保存的设置，实际语速与时长需要试听核对。"); setVersion(value => value + 1); onChanged();}
  }
  return <div className="voice-settings"><h3>目标语言与单行配音参数</h3><p className="muted">只修改后续合成的参数。语速与目标时长是模型提示，不保证实际时长；生成后仍需试听与质检。</p>
    {loadError && <p className="error" role="alert">{loadError} <button type="button" className="link" disabled={busy} onClick={() => setVersion(value => value + 1)}>重读配音参数范围</button></p>}
    <div className="settings-fields"><label>配音参数目标语言<select value={tag} disabled={blocked} onChange={event => {setTag(event.target.value); setScope(""); setHistoryOffset(0); setNotice("");}}><option value="">请选择已启用目标语言</option>{tracks.items.filter(track => !track.archived && track.materialized).map(track => <option value={track.tag} key={track.tag}>{languageName(track.tag)} · {track.tag}</option>)}</select></label>
      <label>参数作用范围<select value={scope} disabled={blocked || !tag} onChange={event => {setScope(event.target.value); setHistoryOffset(0); setNotice("");}}><option value="">此目标语言默认</option>{timeline?.segments.map((row, index) => <option value={row.id} key={row.id}>第 {rowOffset + index + 1} 行 · {row.text.slice(0, 70)}</option>)}</select></label></div>
    <Pager label="参数目标语言" offset={trackOffset} total={tracks.total} disabled={blocked} onChange={offset => {setTrackOffset(offset); setTag(""); setScope(""); setHistoryOffset(0);}} /><Pager label="参数源台词" offset={rowOffset} total={timeline?.total ?? 0} disabled={blocked} onChange={offset => {setRowOffset(offset); setScope(""); setHistoryOffset(0);}} />
    {!tag && <p className="muted">请先在翻译工作台启用目标语言，再设置参数。</p>}{loading && <p role="status">正在核对配音参数…</p>}{settingsError && <p className="error" role="alert">{settingsError} <button type="button" className="link" disabled={busy} onClick={() => setVersion(value => value + 1)}>重读配音参数</button></p>}
    {!supported && <p className="muted">当前服务尚未声明完整 OmniVoice 参数能力，请先检查<a href="#/services">服务配置</a>。参数编辑暂不可用。</p>}
    {current && values && <form onSubmit={event => void save(event)}><p className="muted">{current.settings.override ? scope ? "当前为本行覆盖" : "当前为目标语言自定义默认" : scope ? "当前继承目标语言默认（目标默认也可继承服务设置）" : "当前继承服务默认"} · 参数版本 {current.settings.revision}</p>
      <p className="muted">当前生效参数：语速 {current.settings.controls.sp}；目标时长 {current.settings.controls.du ?? "自动"} 秒；ns {current.settings.controls.ns}；gs {current.settings.controls.gs}；降噪 {current.settings.controls.dn ? "开" : "关"}；参考音预处理 {current.settings.controls.pp ? "开" : "关"}；输出后处理 {current.settings.controls.po ? "开" : "关"}。</p>
      <fieldset disabled={busy || loading || !supported || !source || !trackAvailable || !rowAvailable}><label className="check-label"><input type="checkbox" checked={override} onChange={event => edit({}, event.target.checked)} />使用本范围自定义参数</label><div className="settings-fields">
        <label>语速倍数<input type="number" step="any" min="0.5" max="1.5" required value={values.sp} disabled={!override} onChange={event => edit({sp: event.target.value})} /></label><label>目标时长（秒，可留空）<input type="number" step="any" min="0.01" max="10000" value={values.du} disabled={!override} onChange={event => edit({du: event.target.value})} /></label></div>
        <label className="check-label"><input type="checkbox" checked={values.dn} disabled={!override} onChange={event => edit({dn: event.target.checked})} />参考音降噪（dn）</label><label className="check-label"><input type="checkbox" checked={values.pp} disabled={!override} onChange={event => edit({pp: event.target.checked})} />参考音预处理（pp）</label><label className="check-label"><input type="checkbox" checked={values.po} disabled={!override} onChange={event => edit({po: event.target.checked})} />输出后处理（po）</label>
        <details><summary>高级合成参数</summary><div className="settings-fields"><label>采样步数（ns）<input type="number" min="4" max="64" step="1" required value={values.ns} disabled={!override} onChange={event => edit({ns: event.target.value})} /></label><label>引导强度（gs）<input type="number" min="0" max="4" step="any" required value={values.gs} disabled={!override} onChange={event => edit({gs: event.target.value})} /></label></div></details>
      </fieldset>
      {stale && <p className="error">源或配音参数已更新，草稿保留原始版本；保存仍使用原始版本校验，冲突后请放弃修改并核对新版本。</p>}{!source && <p className="muted">当前源字幕尚未就绪或已过期。</p>}
      {draft && <div className="actions"><button className="secondary" disabled={busy || loading || !supported || !trackAvailable || !rowAvailable || draft.override && !parsedVoiceControls(draft.values)}>保存配音参数</button><button type="button" className="link" disabled={busy || loading} onClick={() => {setDraft(null); setNotice("");}}>放弃配音参数修改</button></div>}
      {draft && <p className="muted">有未保存修改，请先保存或放弃，再切换目标语言、作用范围或分页。</p>}
      <details><summary>配音参数历史（{current.settings.total}）</summary><ul>{current.settings.history.map(item => <li key={item.id}>历史版本 {item.revision} · {item.override ? "自定义覆盖" : "继承"} · {item.created_at}{item.override && ` · 语速 ${item.controls.sp} / 目标时长 ${item.controls.du ?? "自动"} / ns ${item.controls.ns} / gs ${item.controls.gs} / dn ${String(item.controls.dn)} / pp ${String(item.controls.pp)} / po ${String(item.controls.po)}`}</li>)}</ul><Pager label="参数历史" offset={historyOffset} total={current.settings.total} disabled={blocked} onChange={setHistoryOffset} /></details>
    </form>}{error && <p className="error" role="alert">{error}</p>}{notice && <p className="notice" role="status">{notice}</p>}
  </div>;
}
