import {act, renderHook, waitFor} from "@testing-library/react";
import {afterEach, expect, it, vi} from "vitest";
import {subscribeProjectEvents} from "./projectEvents";
import {useProjectData} from "./useProjectData";
vi.mock("./projectEvents", () => ({subscribeProjectEvents: vi.fn(() => () => {})}));
// Read-only project/event contract doubles; no real runtime requests.
afterEach(() => vi.restoreAllMocks());
it("keeps persistent pipeline event IDs out of the legacy source workflow lookup", async () => {
  const fetch = vi.spyOn(globalThis, "fetch").mockImplementation(async () => new Response("{}"));
  const view = renderHook(() => useProjectData("p", 0, 0));
  const callback = vi.mocked(subscribeProjectEvents).mock.calls.at(-1)![1];
  act(() => callback.onEvent({sequence: 1, kind: "pipeline.updated", facts: {workflow_id: "pipeline-id"}}));
  await waitFor(() => expect(view.result.current.eventSequence).toBe(1));
  expect(fetch.mock.calls.some(([path]) => String(path).includes("/workflow/pipeline-id"))).toBe(false);
  act(() => callback.onEvent({sequence: 2, kind: "workflow.updated", facts: {workflow_id: "source-id"}}));
  await waitFor(() => expect(fetch.mock.calls.some(([path]) => String(path).includes("/workflow/source-id"))).toBe(true));
  view.unmount();
});
