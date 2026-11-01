"""Pure CPU delivery phases; SQL checkpoints remain in the ordinary worker adapter."""

from fractions import Fraction


def render(snapshot, assets, plan, root, limits, check, load_asset, store_file):
    from ..media.audio import extract_audio, validate_audio
    from ..media.fit_audio import fit_voice, retime_audio
    from ..media.fit_video import retime_video

    choices = snapshot["choices"]
    source = load_asset("source")
    video = retime_video(
        source,
        root / "picture.mp4",
        source_sha256=assets["source"].sha256,
        absolute_start_ms=snapshot["parent_snapshot"]["start_ms"],
        absolute_end_ms=snapshot["parent_snapshot"]["end_ms"],
        plan=plan,
        frame_rate=Fraction(
            choices["frame_rate"]["numerator"], choices["frame_rate"]["denominator"]
        ),
        limits=limits,
        check=check,
    )
    if "working" in assets:
        working = validate_audio(
            load_asset("working"),
            max_bytes=limits.max_output_bytes,
            max_duration=57600,
            timeout=600,
            check=check,
        )
    else:
        working = extract_audio(
            source,
            root / "working.wav",
            audio_ordinal=snapshot["source_audio_ordinal"],
            start_ms=snapshot["parent_snapshot"]["start_ms"],
            end_ms=snapshot["parent_snapshot"]["end_ms"],
            sample_rate=48000,
            channels=2,
            timeout=600,
            check=check,
        )
    original = retime_audio(working, plan, root / "original.wav", limits=limits, check=check)
    outputs = [
        store_file(video, "delivery_picture", "mp4"),
        store_file(working, "delivery_working", "wav"),
        store_file(original, "delivery_original", "wav"),
    ]
    for index, placement in enumerate(plan.placements):
        key = "voice:" + placement.track_key + ":" + placement.segment_key
        natural = validate_audio(
            load_asset(key),
            max_bytes=limits.max_output_bytes,
            max_duration=57600,
            timeout=600,
            check=check,
        )
        fitted = fit_voice(
            natural,
            root / f"fitted-{index}.wav",
            speed=placement.audio_speed,
            limits=limits,
            check=check,
        )
        entry = store_file(fitted, "delivery_voice_" + str(index), "wav")
        entry.update(track_id=placement.track_key, segment_id=placement.segment_key)
        outputs.append(entry)
    return outputs


def mix_tracks(snapshot, plan, root, limits, check, load_asset, store_file, restore, render):
    from ..media.audio import validate_audio
    from ..media.background import build_background
    from ..media.delivery_mix import mix
    from ..media.fit_audio import retime_audio

    choices = snapshot["choices"]
    tracks = snapshot["parent_snapshot"]["tracks"]
    _, working_entry, original_entry = render[:3]
    original_path = restore(original_entry)
    outputs = []
    original_audio = validate_audio(
        original_path,
        max_bytes=limits.max_output_bytes,
        max_duration=57600,
        timeout=600,
        check=check,
    )
    if choices["include_original_comparison"]:
        protected = mix(
            original_audio,
            [],
            root / "protected-original.wav",
            background_gain=1.0,
            voice_gain=0.0,
            limits=limits,
            check=check,
        )
        entry = store_file(protected, "delivery_mix_original", "wav")
        entry["track"] = "original"
        outputs.append(entry)
    if tracks:
        working_audio = validate_audio(
            restore(working_entry),
            max_bytes=limits.max_output_bytes,
            max_duration=57600,
            timeout=600,
            check=check,
        )
        instrumental = validate_audio(
            load_asset("instrumental"),
            max_bytes=limits.max_output_bytes,
            max_duration=57600,
            timeout=600,
            check=check,
        )
        voices = {(e["track_id"], e["segment_id"]): e for e in render[3:]}
        for index, track in enumerate(tracks):
            intervals = tuple(
                (r["start_ms"], r["end_ms"])
                for r in snapshot["rows"]
                if r["track_id"] == track["id"] and r["included"]
            )
            fade = min([10] + [(b - a) // 2 for a, b in intervals])
            background = build_background(
                working_audio,
                instrumental,
                root / f"bed-{index}.wav",
                source_duration_ms=plan.source_duration_ms,
                dialogue_intervals=intervals,
                crossfade_ms=fade,
                limits=limits,
                check=check,
            )
            retimed = retime_audio(
                background,
                plan,
                root / f"retimed-bed-{index}.wav",
                limits=limits,
                check=check,
            )
            included = []
            for placement in plan.placements:
                if placement.track_key == track["id"]:
                    voice = validate_audio(
                        restore(voices[placement.track_key, placement.segment_key]),
                        max_bytes=limits.max_output_bytes,
                        max_duration=57600,
                        timeout=600,
                        check=check,
                    )
                    included.append((voice, placement.output_start_ms, placement.voice_end_ms))
            mixed = mix(
                retimed,
                included,
                root / f"mix-{index}.wav",
                background_gain=choices["background_gain"],
                voice_gain=choices["voice_gain"],
                limits=limits,
                check=check,
            )
            entry = store_file(mixed, "delivery_mix_" + str(index), "wav")
            entry.update(track=track["tag"], included_source_intervals=[list(v) for v in intervals])
            outputs.append(entry)
    return outputs


def export(
    snapshot, plan, root, budget, store_file, restore, render, mixed, *, caption_context=None
):
    from ..media.delivery_captions import sidecars
    from ..media.delivery_export import mp3, mux

    choices = snapshot["choices"]
    tracks = snapshot["parent_snapshot"]["tracks"]
    picture = render[0]
    picture_path = restore(picture)
    audios = [(entry["track"], restore(entry)) for entry in mixed]
    duration = picture["metadata"]["duration_ms"]
    outputs = []
    caption_receipt = None
    options = choices.get("caption_options")
    if options and options["burn_in"]:
        from ..execution.inputs import fingerprint
        from ..media.subtitle_finishing import burn_in
        from .delivery_subtitles import burn_cues

        grouped, fonts, proof = caption_context
        burned = burn_in(
            picture_path,
            burn_cues(grouped, options),
            root / "burned.mp4",
            fonts=fonts,
            width=picture["metadata"]["width"],
            height=picture["metadata"]["height"],
            budget=budget,
            font_size=options["font_size"],
            wrap_unicode=options.get("layout_policy") == "unicode_wrap_v2",
        )
        burned.facts["caption_proof_sha256"] = fingerprint(proof)
        outputs.append(store_file(burned, "delivery_burned_picture", "mp4"))
        picture_path = burned.path
        caption_receipt = dict(
            mode="burn_in",
            track=options["track"],
            target_track=options.get("target_track"),
            font_size=options["font_size"],
            style=options["style"],
            fonts=proof["fonts"],
            cue_manifest_sha256=proof["cue_manifest_sha256"],
            font_proof_sha256=fingerprint(proof),
            burned_picture_sha256=burned.facts["sha256"],
            ass_sha256=burned.facts["ass_sha256"],
        )
        if "layout_policy" in options:
            caption_receipt["layout_policy"] = options["layout_policy"]
            caption_receipt["layout_capability"] = burned.facts["layout_capability"]
    movie = mux(
        picture_path,
        audios,
        root / "delivery.mp4",
        default_track=choices["default_audio_track"],
        duration_ms=duration,
        budget=budget,
        video_metadata=picture["metadata"],
        original_language=snapshot["source_language"],
    )
    if caption_receipt:
        movie.facts["captions"] = caption_receipt
    movie_entry = store_file(movie, "delivery_movie", "mp4")
    outputs.append(movie_entry)
    artifacts = [
        dict(
            object_id=movie_entry["object_id"],
            format="mp4",
            track="all" if tracks else "original",
        )
    ]
    for index, entry in enumerate(mixed):
        artifacts.append(dict(object_id=entry["object_id"], format="wav", track=entry["track"]))
        encoded = mp3(
            restore(entry),
            root / f"audio-{index}.mp3",
            budget=budget,
            expected_samples=entry["metadata"]["sample_count"],
        )
        mp3_entry = store_file(encoded, "delivery_mp3_" + str(index), "mp3")
        outputs.append(mp3_entry)
        artifacts.append(dict(object_id=mp3_entry["object_id"], format="mp3", track=entry["track"]))
        if entry["track"] != "original":
            comparison = [
                (e["track"], restore(e))
                for e in mixed
                if e["track"] in {"original", entry["track"]}
            ]
            separate = mux(
                picture_path,
                comparison,
                root / f"target-{index}.mp4",
                default_track=entry["track"],
                duration_ms=duration,
                budget=budget,
                video_metadata=picture["metadata"],
                original_language=snapshot["source_language"],
            )
            if caption_receipt:
                separate.facts["captions"] = caption_receipt
            exported = store_file(separate, "delivery_target_" + str(index), "mp4")
            outputs.append(exported)
            artifacts.append(
                dict(object_id=exported["object_id"], format="mp4", track=entry["track"])
            )
    if options or choices["captions"] == "sidecar":
        for index, (track, format, media) in enumerate(
            sidecars(
                plan,
                snapshot["cues"],
                tracks,
                root,
                formats=[v for v in options["formats"] if v != "ass"]
                if options
                else ("srt", "vtt"),
            )
        ):
            entry = store_file(media, "delivery_caption_" + str(index), format)
            outputs.append(entry)
            artifacts.append(dict(object_id=entry["object_id"], format=format, track=track))
    if options and "ass" in options["formats"]:
        from ..execution.inputs import fingerprint
        from ..media.subtitle_finishing import ass_file

        grouped, fonts, proof = caption_context
        for index, (track, rows) in enumerate(grouped.items()):
            caption = ass_file(
                rows,
                root / f"captions-{index}.ass",
                width=picture["metadata"]["width"],
                height=picture["metadata"]["height"],
                family=fonts[0].family,
                font_size=options["font_size"],
                fonts=fonts,
            )
            caption.facts.update(
                cue_policy="target_actual_declared_speech_source_mapped_cue_v1",
                clock="selection_relative_shared_map",
                cue_ids=[row["id"] for row in rows],
                cue_manifest_sha256=fingerprint(rows),
                first_cue_ms=min((r["start_ms"] for r in rows), default=None),
                last_cue_ms=max((r["end_ms"] for r in rows), default=None),
                fonts=proof["fonts"],
                font_proof_sha256=fingerprint(proof),
            )
            entry = store_file(caption, "delivery_ass_" + str(index), "ass")
            outputs.append(entry)
            artifacts.append(dict(object_id=entry["object_id"], format="ass", track=track))
    return outputs, artifacts
