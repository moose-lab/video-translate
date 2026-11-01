import {afterEach, expect, it, vi} from "vitest";
import {captureFitInputs} from "./fitCapture";
// Contract doubles only: paging and immutable guards, no inference or media execution.
afterEach(() => vi.restoreAllMocks());
it("captures every row across source and audio pages without replacing server revision identities", async () => {
  const rows = Array.from({length: 201}, (_, index) => ({id: `s-${index}`, revision_id: `revision-${index}`, source_text_fingerprint: `fp-${index}`, translation: {revision: 3}}));
  const audio = rows.map(row => ({segment_id: row.id, selection_revision: 4, selected: {id: `audio-${row.id}`, review_revision: 5, qc_evidence_fingerprint: `qc-${row.id}`}}));
  const fetch = vi.spyOn(globalThis, "fetch").mockImplementation(async input => {
    const url = new URL(String(input), "http://localhost"), offset = Number(url.searchParams.get("offset")), limit = Number(url.searchParams.get("limit"));
    const data = url.pathname.endsWith("/timeline") ? {source: {revision: 2, stale: false}, transcript: {id: "transcript", stale: false}, total: rows.length, segments: rows.slice(offset, offset + limit)} : {total: audio.length, items: audio.slice(offset, offset + limit)};
    return new Response(JSON.stringify(data));
  });
  const result = await captureFitInputs("p", ["zh"], 7, {selection_revision: 2, transcript_revision: "transcript"}, new AbortController().signal);
  expect(result.tracks[0].segments).toHaveLength(201);
  expect(result.tracks[0].segments[200]).toEqual({id: "s-200", expected_source_revision_id: "revision-200", expected_source_text_fingerprint: "fp-200", translation_revision: 3, selection_revision: 4, output_id: "audio-s-200", review_revision: 5, qc_evidence_fingerprint: "qc-s-200"});
  expect(fetch).toHaveBeenCalledTimes(5);
});
