import {useEffect, useState} from "react";
import {api, ApiError} from "../api/client";
import {projectPath, type Page} from "../api/projects";
import {purposeName, type Delivery, type DeliverySummary} from "./finishingTypes";
import {statusName} from "./types";
import DeliveryResult from "./DeliveryResult";
function savedId(key: string) {const value = new URLSearchParams(window.location.hash.split("?")[1]).get(key); return value && /^[A-Za-z0-9-]{1,36}$/.test(value) ? value : "";}
export default function FinishingPanel({projectId, refreshVersion}: {projectId: string; csrf: string; refreshVersion: number}) {
  const [deliveries, setDeliveries] = useState<Page<DeliverySummary>>({items: [], total: 0}), [offset, setOffset] = useState(0), [selected, setSelected] = useState(() => savedId("delivery"));
  const [delivery, setDelivery] = useState<Delivery | null>(null), [error, setError] = useState("");
  const path = projectPath(projectId);
  useEffect(() => {let active = true; const controller = new AbortController(); api<Page<DeliverySummary>>(`${path}/deliveries?limit=50&offset=${offset}`, {signal: controller.signal}).then(page => {if (active) {setDeliveries(page); setSelected(previous => previous || page.items[0]?.id || ""); setError("");}}).catch(error => {if (active) setError(error instanceof ApiError ? error.message : "导出列表加载失败，请刷新重试。");}); return () => {active = false; controller.abort();};}, [path, offset, refreshVersion]);
  useEffect(() => {if (!selected) return; let active = true; const controller = new AbortController(); api<Delivery>(`${path}/deliveries/${encodeURIComponent(selected)}`, {signal: controller.signal}).then(value => {if (active) {setDelivery(value); setError("");}}).catch(error => {if (active) setError(error instanceof ApiError ? error.message : "导出详情加载失败。");}); return () => {active = false; controller.abort();};}, [path, selected, refreshVersion]);
  function select(id: string) {setSelected(id); setDelivery(null); const [base, query] = window.location.hash.split("?"); const params = new URLSearchParams(query); params.set("delivery", id); window.history.replaceState(null, "", `${base || `#/projects/${projectId}`}?${params}`);}
  return <section className="panel finishing-panel" aria-labelledby="finishing-title"><h2 id="finishing-title">拟合与导出</h2>{error && <p className="error" role="alert">{error}</p>}
    {deliveries.items.length > 0 ? <label>已提交的导出<select value={selected} onChange={event => select(event.target.value)}>{deliveries.items.map((item, index) => <option key={item.id} value={item.id}>导出 {offset + index + 1} · {purposeName(item.purpose)} · {statusName(item.status)}</option>)}</select></label> : <p className="muted">尚无导出任务。</p>}
    {deliveries.total > 50 && <nav className="actions pagination" aria-label="导出分页"><button className="secondary" disabled={!offset} onClick={() => setOffset(Math.max(0, offset - 50))}>上一页导出</button><button className="secondary" disabled={offset + 50 >= deliveries.total} onClick={() => setOffset(offset + 50)}>下一页导出</button></nav>}
    {delivery && <DeliveryResult key={delivery.id} delivery={delivery} />}
  </section>;
}
