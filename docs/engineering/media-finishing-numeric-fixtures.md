# Numeric fixtures for finishing verification

These are planned test expectations, not measured renders or completed Task6
evidence. They refine the approved [finishing boundaries](../superpowers/specs/2026-10-30-media-finishing-boundaries.md),
whose pinned upstream sources were inspected through Agent Reach. Write the
Task6 execution plan against final gated5B interfaces before implementing them.
All durations below are seconds relative to the selected source window.

## Shared Smart Fit with overlapping roles

Fixture settings: no voice speed change or silence borrowing; picture extension
limit permits the required factors; natural voices remain their measured length.
Source window is0–4. RoleA occupies0–2 and has a3-second natural voice. RoleB
occupies1–3 and has a4-second natural voice. Their required local output/source
time factors are1.5 and2. On each source partition use the largest active factor,
once, with factor1 in uncovered intervals.

| Source partition | Active factors | Applied factor | Output partition |
| --- | --- | --- | --- |
|0–1|A:1.5|1.5|0–1.5|
|1–2|A:1.5, B:2|2|1.5–3.5|
|2–3|B:2|2|3.5–5.5|
|3–4|none|1|5.5–6.5|

Thus the common map has endpoints`(0,0),(1,1.5),(2,3.5),(3,5.5),(4,6.5)`.
A's actual voice placement is0–3; B's is1.5–5.5. Do not multiply the overlap
factors, concatenate the roles or force A's voice to fill its mapped0–3.5 slot.
Source-time A captions map to0–3.5; speech-duration target captions are0–3.
Both are valid only under their explicitly recorded coordinate policies.

The real CPU fixture should use distinct voice frequency/onset/end markers and
numbered source frames. Measure each rendered onset/end and the common video's
coverage with declared sample/frame/codec tolerances. Retain the end markers;
checking only filter text or total duration is insufficient.

## Two target tracks require one video map

Source window0–4 has lines0–2 and3–4. Chinese natural lengths are3 and1;
Japanese natural lengths are4 and1. With the same no-speed/no-borrow settings:

| Export selection | Common map endpoints | Second-line onset | Output duration |
| --- | --- | --- | --- |
|Chinese only|`(0,0),(2,3),(3,4),(4,5)`|4|5|
|Japanese only|`(0,0),(2,4),(3,5),(4,6)`|5|6|
|Both targets in one MP4|`(0,0),(2,4),(3,5),(4,6)`|5 for both|6|

The separate Chinese5-second mix is not eligible for the6-second two-target
export: its second voice starts one second early. Reuse natural voice assets,
then derive placements/background/original comparison/captions from the common
selected plan. Similar voice lengths or shared first onsets do not prove map
compatibility. Verify actual muxed stream count, chosen default and language tags.

## Fixed picture and bounded audio adjustment

With identity picture timing, a line0–2 has a2.5-second natural voice. If the
next same-role line starts at3 and there is an allowed half-second of otherwise
available silence, the first line may end at2.5; the next onset remains3. Record
the borrowed interval explicitly. This fixture contains no intervening role, so
it does not decide an additional cross-role borrowing policy.

With no borrowing available, maximum audio speed1.2 cannot fit2.5 seconds into2
seconds: required1.25 exceeds the configured bound. Report that line for review,
without dropping its tail, moving another onset or silently editing wording.
An explicitly permitted1.25 speed may fit it. Use actual CPU audio with pitch
and end markers to check pitch preservation and measured placement, including
any documented codec padding. Natural source audio and its QC identity remain
unchanged by the derived adjustment.

## Dialogue union and gain protection

Use source window0–5 with dialogue intervals1–3 and2–4. Their union is1–4.
The source working track has a distinctive original-dialogue marker only in
that union; the instrumental has a separate identifiable bed marker. Inside the
union's crossfade-free interior, the bed must use the instrumental once. At2
and3 there must be no second removal, attenuation notch or extra crossfade caused
by the overlap. Outside the union use the source working track. Test the bounded
crossfades around1 and4 separately, then apply the common map to the entire bed.

For a separate unity-gain float fixture, align two voice impulses of0.6 with a
bed sample of0.1. Their unprotected sum is1.3. A documented uniform attenuation
policy with ceiling0.98 would apply0.98/1.3; a limiter implementation must instead
report and validate its actual behavior. Both must show measured unclipped output.
Never infer successful protection from FFmpeg's implicit input-count averaging.
Measure the raw sum and the protected exported samples; a gain-only edit must
leave translation, natural generation, recognition and the timing plan reusable.

## Preconditions and remaining actual evidence

Use gated5B's exact selected-audio/readiness/current-review proofs. Diagnostic QC
of stale audio, a passing text match or one accepted line cannot authorize a full
target export. Ordinary exports block hard stale/integrity/missing-line issues;
an explicit incomplete preview remains labelled as such. Every plan/output needs
captured source/target/audio/settings lineage and publication conflict/restart
tests. All waveform/peak/frame/caption/stream expectations above still need real
FFmpeg execution and full decode in Task6; neither this note nor its arithmetic
check establishes finishing capability or final EN→ZH/JA acceptance.
