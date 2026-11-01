import {afterEach, expect, it, vi} from "vitest";
import {subscribeProjectEvents} from "./projectEvents";
class StreamDouble {
  static all: StreamDouble[] = [];
  closed = false; listeners = new Map<string, (event: MessageEvent) => void>();
  onopen: (() => void) | null = null; onerror: (() => void) | null = null;
  constructor(public url: string) {StreamDouble.all.push(this);}
  addEventListener(name: string, callback: (event: MessageEvent) => void) {this.listeners.set(name, callback);}
  close() {this.closed = true;}
  send(sequence: number) {this.listeners.get("project_event")?.(new MessageEvent("project_event", {data: JSON.stringify({sequence, kind: "run.updated"})}));}
}
afterEach(() => {vi.useRealTimers(); vi.unstubAllGlobals(); vi.restoreAllMocks(); StreamDouble.all = [];});
it("listens to named events, deduplicates sequences, coalesces updates and cleans the old project", async () => {
  vi.useFakeTimers(); vi.stubGlobal("EventSource", StreamDouble);
  const update = vi.fn(), event = vi.fn();
  const close = subscribeProjectEvents("p", {onChange: update, onEvent: event, onState: vi.fn()});
  const stream = StreamDouble.all[0]; expect(stream.url).toBe("/api/projects/p/events/stream?after=0");
  stream.send(1); stream.send(1); stream.send(2);
  await vi.advanceTimersByTimeAsync(150);
  expect(event).toHaveBeenCalledTimes(2); expect(update).toHaveBeenCalledOnce();
  close(); expect(stream.closed).toBe(true);
  stream.send(3); await vi.advanceTimersByTimeAsync(5000);
  expect(event).toHaveBeenCalledTimes(2); expect(StreamDouble.all).toHaveLength(1);
});
it("replays JSON after disconnection and reconnects after the verified cursor", async () => {
  vi.useFakeTimers(); vi.stubGlobal("EventSource", StreamDouble);
  const fetch = vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response(JSON.stringify({items: [{sequence: 4, kind: "run.updated"}], total: 1, next_cursor: 4})));
  const close = subscribeProjectEvents("p", {onChange: vi.fn(), onEvent: vi.fn(), onState: vi.fn()});
  StreamDouble.all[0].send(3); StreamDouble.all[0].onerror?.();
  await vi.advanceTimersByTimeAsync(2500);
  expect(fetch.mock.calls.some(([path]) => String(path) === "/api/projects/p/events?after=3&limit=200")).toBe(true);
  expect(StreamDouble.all.at(-1)!.url).toBe("/api/projects/p/events/stream?after=4");
  close();
});
it("closes and stops reconnecting when replay reports session expiry", async () => {
  vi.useFakeTimers(); vi.stubGlobal("EventSource", StreamDouble);
  vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response("{}", {status: 401}));
  const expired = vi.fn(); window.addEventListener("session-expired", expired);
  const close = subscribeProjectEvents("p", {onChange: vi.fn(), onEvent: vi.fn(), onState: vi.fn()});
  StreamDouble.all[0].onerror?.(); await vi.advanceTimersByTimeAsync(10000);
  expect(expired).toHaveBeenCalledOnce(); expect(StreamDouble.all).toHaveLength(1); expect(StreamDouble.all[0].closed).toBe(true);
  close(); window.removeEventListener("session-expired", expired);
});
