import {api, ApiError} from "../api/client";
import {projectPath} from "../api/projects";
export type ProjectEvent = {sequence: number; kind: string; facts?: {workflow_id?: string}};
type Callbacks = {onChange: () => void; onEvent: (event: ProjectEvent) => void; onState: (value: string) => void};
export function subscribeProjectEvents(id: string, callbacks: Callbacks): () => void {
  let active = true, cursor = 0, recovering = false, stream: EventSource | undefined;
  let reconnect: ReturnType<typeof setTimeout> | undefined, coalesce: ReturnType<typeof setTimeout> | undefined;
  const controller = new AbortController(), path = projectPath(id);
  function changed() {if (!coalesce) coalesce = setTimeout(() => {coalesce = undefined; if (active) callbacks.onChange();}, 100);}
  function receive(event: ProjectEvent) {
    if (!active || !Number.isSafeInteger(event.sequence) || event.sequence <= cursor || typeof event.kind !== "string") return;
    callbacks.onEvent(event); cursor = event.sequence; changed();
  }
  async function recover() {
    if (!active || recovering) return;
    recovering = true;
    if (stream) stream.onerror = null;
    stream?.close(); callbacks.onState("正在重连 · 核对项目事件");
    try {
      // Bound each replay cycle; remaining history resumes from this verified cursor.
      for (let page = 0; active && page < 5; page++) {
        const result = await api<{items: ProjectEvent[]; next_cursor: number}>(`${path}/events?after=${cursor}&limit=200`, {signal: controller.signal});
        if (!active) return;
        result.items.forEach(receive);
        if (result.items.length < 200) break;
      }
      if (!active) return;
      changed(); callbacks.onState(typeof EventSource === "undefined" ? "定时核对项目状态" : "正在重连");
    } catch (error) {
      if (!active) return;
      if (error instanceof ApiError && [401, 403, 404].includes(error.status)) {callbacks.onState("实时连接已停止，请重新打开项目"); close(); return;}
      callbacks.onState("连接中断 · 稍后核对");
    }
    recovering = false;
    if (active) reconnect = setTimeout(connect, 2000);
  }
  function connect() {
    if (!active) return;
    if (typeof EventSource === "undefined") {void recover(); return;}
    callbacks.onState("正在连接项目事件");
    stream = new EventSource(`/api${path}/events/stream?after=${cursor}`);
    stream.addEventListener("project_event", event => {try {receive(JSON.parse((event as MessageEvent).data));} catch {void recover();}});
    stream.onopen = () => {if (active) callbacks.onState("实时连接正常");};
    stream.onerror = () => {if (active) void recover();};
  }
  function close() {active = false; stream?.close(); controller.abort(); clearTimeout(reconnect); clearTimeout(coalesce);}
  connect(); return close;
}
