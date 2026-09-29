from musefolders.models import AcousticFeatures, CollectionPlan, TrackEncoding, TrackMetadata
from musefolders.taxonomy import (
    ACTIVITY_WEIGHTS, BRIGHTNESS_WEIGHTS, brightness_score,
    compile_folders, rename_folder, score_tracks,
)
from musefolders.schemes import available_schemes, compile_scheme
from musefolders.reporting import write_validation_reports


def make_track(index: int, tempo: float, rms: float, bright: float, perc: float) -> TrackEncoding:
    return TrackEncoding(
        track_id=f"t{index}", source_path=f"C:/music/t{index}.mp3", source_size=10,
        source_mtime_ns=1, source_sha256=str(index) * 64,
        metadata=TrackMetadata(title=f"Track {index}", artist="Artist"),
        acoustic=AcousticFeatures(
            duration_s=180, tempo_bpm=tempo, tempo_confidence=.8, rms_dbfs=rms,
            dynamic_range_db=12, spectral_centroid_hz=bright, spectral_rolloff_hz=5000,
            zero_crossing_rate=.05, percussive_ratio=perc, onset_rate=perc * 3,
            harmonic_ratio=1 - perc, key="C", mode="major", key_confidence=.5,
            analyzed_audio_s=72,
        ),
    )


def test_scoring_and_folder_compilation_are_explainable():
    tracks = [
        make_track(1, 70, -30, 900, .15), make_track(2, 82, -27, 1200, .25),
        make_track(3, 108, -20, 2200, .48), make_track(4, 138, -13, 3400, .78),
    ]
    score_tracks(tracks)
    folders = compile_folders(tracks)
    assert len(folders) >= 2
    assert all(track.folder_id and track.reasons for track in tracks)
    assert tracks[0].standard.agitation < tracks[-1].standard.agitation


def test_folder_name_can_be_overridden_without_reanalysis():
    tracks = [make_track(1, 80, -28, 1000, .2), make_track(2, 120, -18, 2500, .6)]
    score_tracks(tracks)
    folders = compile_folders(tracks)
    target = folders[0]
    rename_folder(tracks, folders, target.folder_id, "我的雨天")
    assert target.name == "我的雨天"
    assert all(track.folder_name == "我的雨天" for track in tracks if track.folder_id == target.folder_id)


def test_agitation_is_absolute_not_library_relative():
    alone = make_track(1, 101, -25, 1_250, .12)
    score_tracks([alone])
    expected = alone.standard.agitation

    same_song = make_track(1, 101, -25, 1_250, .12)
    quiet = make_track(2, 62, -37, 520, .01)
    intense = make_track(3, 178, -11, 3_450, .49)
    score_tracks([quiet, same_song, intense])

    assert same_song.standard.agitation == expected


def test_brightness_uses_three_measured_spectral_components() -> None:
    track = make_track(1, 100, -24, 2500, .2)
    track.acoustic.spectral_rolloff_hz = 5500
    track.acoustic.high_frequency_ratio = .155
    assert sum(BRIGHTNESS_WEIGHTS.values()) == 1.0
    assert brightness_score(track.acoustic) == 50.0
    score_tracks([track])
    assert track.standard.brightness == 50.0


def test_activity_does_not_change_when_only_brightness_changes() -> None:
    dark = make_track(1, 120, -23, 1000, .25)
    bright = make_track(2, 120, -23, 3800, .25)
    dark.acoustic.spectral_rolloff_hz = 2500
    dark.acoustic.high_frequency_ratio = .02
    bright.acoustic.spectral_rolloff_hz = 8500
    bright.acoustic.high_frequency_ratio = .28
    assert sum(ACTIVITY_WEIGHTS.values()) == 1.0
    score_tracks([dark, bright])
    assert dark.standard.brightness < bright.standard.brightness
    assert dark.standard.agitation == bright.standard.agitation


def test_selectable_schemes_cover_every_track_once_and_keep_genre_unverified():
    tracks = [
        make_track(1, 76, -31, 850, .10), make_track(2, 101, -23, 1600, .25),
        make_track(3, 145, -14, 3200, .45),
    ]
    for track in tracks:
        track.metadata.genre = "Blues"
    score_tracks(tracks)
    assert all(track.genre_status == "embedded_unverified" for track in tracks)
    assert "genre_agitation" not in available_schemes(tracks)
    assert all(set(track.tags) == {"instrument", "tempo", "loudness", "tonality", "key", "agitation", "brightness", "rhythmicity"} for track in tracks)
    for scheme in ("agitation_brightness", "tempo_loudness", "tonality_agitation"):
        folders, keys = compile_scheme(tracks, scheme, language="en")
        assert len(keys) == 2
        assert sorted(tid for folder in folders for tid in folder.track_ids) == ["t1", "t2", "t3"]
        assert all("Blues" not in folder.name for folder in folders)
    folders, keys = compile_scheme(tracks, "custom", tag_keys=["rhythmicity"], language="zh")
    assert keys == ["rhythmicity"]
    assert folders


def test_genre_scheme_only_uses_explicit_verified_evidence():
    tracks = [make_track(1, 80, -27, 1000, .2), make_track(2, 135, -15, 3000, .4)]
    score_tracks(tracks)
    tracks[0].genre_status = "verified"
    tracks[0].genre_value = "J-pop"
    tracks[0].genre_source = "test record URL"
    assert "genre_agitation" in available_schemes(tracks)
    folders, _ = compile_scheme(tracks, "genre_agitation", language="en")
    assert any("J-pop" in folder.name for folder in folders)
    assert any("Unverified" in folder.name for folder in folders)


def test_reporting_alternative_schemes_does_not_mutate_confirmed_plan(tmp_path):
    tracks = [make_track(1, 80, -30, 900, .1), make_track(2, 140, -16, 3000, .4)]
    score_tracks(tracks)
    folders, _ = compile_scheme(tracks, "agitation_brightness")
    plan = CollectionPlan("test", str(tmp_path), "poetic", folders, tracks)
    before = [(t.folder_id, t.folder_name) for t in tracks]
    evidence = {"discovered": 2, "analyzed": 2, "failed": 0, "unsupported": 0,
                "cache_hits": 0, "elapsed_s": 1.0, "source_mutations": 0}
    write_validation_reports(plan, evidence, tmp_path)
    assert [(t.folder_id, t.folder_name) for t in tracks] == before


def test_weak_beat_is_not_presented_as_certain_tempo():
    track = make_track(1, 123.05, -25, 1200, .02)
    track.acoustic.tempo_confidence = .45
    score_tracks([track])
    assert track.acoustic.tempo_bpm == 123.05
    assert track.tags["tempo"] == "unsteady"


def test_key_tag_separates_tonic_from_mode_and_keeps_uncertainty():
    c_major = make_track(1, 90, -24, 1300, .2)
    g_major = make_track(2, 90, -24, 1300, .2)
    weak_key = make_track(3, 90, -24, 1300, .2)
    g_major.acoustic.key = "G"
    weak_key.acoustic.key_confidence = .1
    tracks = score_tracks([c_major, g_major, weak_key])

    assert [track.tags["tonality"] for track in tracks] == ["major", "major", "uncertain"]
    assert [track.tags["key"] for track in tracks] == ["C:major", "G:major", "uncertain"]
    mode_folders, _ = compile_scheme(tracks, "custom", tag_keys=["tonality"], language="zh")
    key_folders, _ = compile_scheme(tracks, "custom", tag_keys=["key"], language="zh")
    assert len(mode_folders) == 2
    assert {folder.name for folder in key_folders} == {"调性 C大调", "调性 G大调", "调性 待确定"}
    english_folders, _ = compile_scheme(tracks, "custom", tag_keys=["key"], language="en")
    assert {folder.name for folder in english_folders} == {"Key C major", "Key G major", "Key Uncertain"}

    # A plan saved before the new tag was added can still group by full key.
    del c_major.tags["key"]
    compile_scheme(tracks, "custom", tag_keys=["key"], language="zh")
    assert c_major.tags["key"] == "C:major"

