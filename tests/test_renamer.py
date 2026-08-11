import os

import acoustid
import pytest
import requests

from gestor_listas.renamer import (
    TrackInfo,
    _collect_files,
    _ensure_ffmpeg_on_path,
    _parse_acoustid_result,
    _process_file,
    build_filename,
    enrich_from_musicbrainz,
    fingerprint_file,
    identify_track,
    is_audio_file,
    lookup_fingerprint,
    rename_file,
    resolve_target,
    run_rename,
    sanitize_component,
    track_from_tags,
)


class TestIsAudioFile:
    def test_known_extension(self) -> None:
        assert is_audio_file("song.mp3") is True
        assert is_audio_file("song.FLAC") is True

    def test_unknown_extension(self) -> None:
        assert is_audio_file("song.txt") is False
        assert is_audio_file("song") is False


class TestSanitizeComponent:
    def test_strips_and_collapses_spaces(self) -> None:
        assert sanitize_component("  Artista    Test  ") == "Artista Test"

    def test_removes_illegal_chars(self) -> None:
        assert sanitize_component('A*?<>|:"B') == "AB"

    def test_slash_becomes_ampersand_separator(self) -> None:
        assert sanitize_component("Isabel Aaiún/Fernando Moreno") == "Isabel Aaiún & Fernando Moreno"

    def test_truncates_to_180(self) -> None:
        assert len(sanitize_component("x" * 500)) == 180


class TestBuildFilename:
    def test_basic(self) -> None:
        track = TrackInfo(title="Canción", artist="Artista")
        assert build_filename(track, ".mp3") == "Artista - Canción.mp3"

    def test_with_year(self) -> None:
        track = TrackInfo(title="Canción", artist="Artista", year="1999")
        assert build_filename(track, ".mp3", include_year=True) == "Artista - Canción (1999).mp3"

    def test_year_ignored_when_missing(self) -> None:
        track = TrackInfo(title="Canción", artist="Artista")
        assert build_filename(track, ".flac", include_year=True) == "Artista - Canción.flac"


class TestResolveTarget:
    def test_same_name_returns_source(self, tmp_path) -> None:
        source = tmp_path / "Artista - Canción.mp3"
        source.write_bytes(b"\x00" * 128)
        track = TrackInfo(title="Canción", artist="Artista")
        assert resolve_target(source, track) == source

    def test_adds_suffix_on_collision(self, tmp_path) -> None:
        source = tmp_path / "basura.mp3"
        source.write_bytes(b"\x00" * 128)
        (tmp_path / "Artista - Canción.mp3").write_bytes(b"\x00" * 128)
        track = TrackInfo(title="Canción", artist="Artista")
        assert resolve_target(source, track) == tmp_path / "Artista - Canción (1).mp3"


class TestRenameFile:
    def test_renames(self, tmp_path) -> None:
        source = tmp_path / "basura.mp3"
        source.write_bytes(b"\x00" * 128)
        track = TrackInfo(title="Canción", artist="Artista")
        new = rename_file(source, track)
        assert new == tmp_path / "Artista - Canción.mp3"
        assert new.exists()

    def test_same_name_returns_none(self, tmp_path) -> None:
        source = tmp_path / "Artista - Canción.mp3"
        source.write_bytes(b"\x00" * 128)
        track = TrackInfo(title="Canción", artist="Artista")
        assert rename_file(source, track) is None


class TestParseAcoustidResult:
    def test_parses_recording(self) -> None:
        data = {
            "results": [
                {
                    "score": 0.9,
                    "recordings": [
                        {
                            "title": "Song",
                            "artists": [{"name": "Artist"}],
                            "id": "rec-1",
                            "releases": [{"title": "Album", "date": "2020-05-01"}],
                        }
                    ],
                }
            ]
        }
        tracks = _parse_acoustid_result(data)
        assert len(tracks) == 1
        track = tracks[0]
        assert track.title == "Song"
        assert track.artist == "Artist"
        assert track.album == "Album"
        assert track.year == "2020"
        assert track.score == 0.9
        assert track.recording_id == "rec-1"

    def test_empty_results(self) -> None:
        assert _parse_acoustid_result({"results": []}) == []


class TestLookupFingerprint:
    def test_ok_status_returns_candidates(self, mocker) -> None:
        mocker.patch(
            "gestor_listas.renamer.acoustid.lookup",
            return_value={
                "status": "ok",
                "results": [{"score": 0.8, "recordings": [{"title": "Song", "artists": []}]}],
            },
        )
        tracks = lookup_fingerprint("KEY", 10.0, "fp")
        assert len(tracks) == 1
        assert tracks[0].title == "Song"

    def test_webservice_error_returns_empty(self, mocker) -> None:
        mocker.patch(
            "gestor_listas.renamer.acoustid.lookup",
            side_effect=acoustid.WebServiceError("boom"),
        )
        assert lookup_fingerprint("KEY", 10.0, "fp") == []

    def test_bad_status_returns_empty(self, mocker) -> None:
        mocker.patch(
            "gestor_listas.renamer.acoustid.lookup",
            return_value={"status": "error"},
        )
        assert lookup_fingerprint("KEY", 10.0, "fp") == []


class TestIdentifyTrack:
    def test_filters_below_min_score(self, mocker) -> None:
        mocker.patch(
            "gestor_listas.renamer.lookup_fingerprint",
            return_value=[TrackInfo(title="A", artist="X", score=0.2)],
        )
        assert identify_track("KEY", 10.0, "fp", min_score=0.5) is None

    def test_returns_best_and_enriches(self, mocker) -> None:
        best = TrackInfo(title="A", artist="X", score=0.9, recording_id="rec-1")
        mocker.patch(
            "gestor_listas.renamer.lookup_fingerprint",
            return_value=[best, TrackInfo(title="B", artist="Y", score=0.6)],
        )
        mocker.patch("gestor_listas.renamer.enrich_from_musicbrainz", return_value=best)
        result = identify_track("KEY", 10.0, "fp")
        assert result is best


class TestEnrichFromMusicbrainz:
    def test_fills_metadata(self, mocker) -> None:
        resp = mocker.Mock()
        resp.json.return_value = {
            "title": "Real Title",
            "artist-credit": [{"name": "Real Artist", "joinphrase": ""}],
            "releases": [{"title": "Real Album", "date": "2001-02-03"}],
            "rating": {"value": 4.5, "count": 10},
        }
        mocker.patch("gestor_listas.renamer.requests.get", return_value=resp)
        track = TrackInfo(title="T", artist="A", recording_id="rec-1")
        result = enrich_from_musicbrainz(track)
        assert result.title == "Real Title"
        assert result.artist == "Real Artist"
        assert result.album == "Real Album"
        assert result.year == "2001"
        assert result.rating == 4.5
        assert result.rating_count == 10

    def test_request_error_keeps_track(self, mocker) -> None:
        mocker.patch(
            "gestor_listas.renamer.requests.get",
            side_effect=requests.exceptions.Timeout(),
        )
        track = TrackInfo(title="T", artist="A", recording_id="rec-1")
        assert enrich_from_musicbrainz(track) is track

    def test_without_recording_id_returns_unchanged(self) -> None:
        track = TrackInfo(title="T", artist="A")
        assert enrich_from_musicbrainz(track) is track


class TestCollectFiles:
    def test_collects_audio_from_dir(self, tmp_path) -> None:
        (tmp_path / "a.mp3").write_bytes(b"\x00")
        (tmp_path / "b.flac").write_bytes(b"\x00")
        (tmp_path / "notes.txt").write_text("x")
        (tmp_path / "sub").mkdir()
        (tmp_path / "sub" / "c.ogg").write_bytes(b"\x00")

        files = _collect_files([tmp_path], recursive=False)
        assert sorted(p.name for p in files) == ["a.mp3", "b.flac"]

        files = _collect_files([tmp_path], recursive=True)
        assert sorted(p.name for p in files) == ["a.mp3", "b.flac", "c.ogg"]

    def test_accepts_file_and_dir(self, tmp_path) -> None:
        mp3 = tmp_path / "a.mp3"
        mp3.write_bytes(b"\x00")
        files = _collect_files([mp3, tmp_path], recursive=False)
        assert mp3 in files


class TestTrackFromTags:
    def test_reads_title_and_artist(self, tmp_path, mocker) -> None:
        mocker.patch(
            "gestor_listas.renamer.MutagenFile",
            return_value={"title": ["Mocatriz"], "artist": ["Ojete Calor"],
                          "album": ["Mocatriz"], "date": ["2019-02-08"]},
        )
        track = track_from_tags(tmp_path / "7_A.mp3")
        assert track is not None
        assert track.title == "Mocatriz"
        assert track.artist == "Ojete Calor"
        assert track.album == "Mocatriz"
        assert track.year == "2019"

    def test_first_element_when_list(self, tmp_path, mocker) -> None:
        mocker.patch(
            "gestor_listas.renamer.MutagenFile",
            return_value={"title": ["A", "B"], "artist": ["X"]},
        )
        track = track_from_tags(tmp_path / "song.mp3")
        assert track is not None
        assert track.title == "A"

    def test_missing_tags_returns_none(self, tmp_path, mocker) -> None:
        mocker.patch("gestor_listas.renamer.MutagenFile", return_value=None)
        assert track_from_tags(tmp_path / "song.mp3") is None

    def test_no_artist_returns_none(self, tmp_path, mocker) -> None:
        mocker.patch(
            "gestor_listas.renamer.MutagenFile",
            return_value={"title": ["A"]},
        )
        assert track_from_tags(tmp_path / "song.mp3") is None

    def test_exception_returns_none(self, tmp_path, mocker) -> None:
        mocker.patch("gestor_listas.renamer.MutagenFile", side_effect=Exception("corrupto"))
        assert track_from_tags(tmp_path / "song.mp3") is None


class TestProcessFile:
    def test_no_fingerprint_reports_error(self, tmp_path, mocker) -> None:
        source = tmp_path / "a.mp3"
        source.write_bytes(b"\x00" * 128)
        mocker.patch("gestor_listas.renamer.fingerprint_file", return_value=None)
        ok, renamed = _process_file(source, "KEY", 0.5, False, False)
        assert ok is False
        assert renamed is False

    def test_no_match_reports_error(self, tmp_path, mocker) -> None:
        source = tmp_path / "a.mp3"
        source.write_bytes(b"\x00" * 128)
        mocker.patch("gestor_listas.renamer.fingerprint_file", return_value=(10.0, "fp"))
        mocker.patch("gestor_listas.renamer.identify_track", return_value=None)
        mocker.patch("gestor_listas.renamer.track_from_tags", return_value=None)
        ok, renamed = _process_file(source, "KEY", 0.5, False, False)
        assert ok is False

    def test_falls_back_to_tags_when_no_match(self, tmp_path, mocker) -> None:
        source = tmp_path / "a.mp3"
        source.write_bytes(b"\x00" * 128)
        mocker.patch("gestor_listas.renamer.fingerprint_file", return_value=(10.0, "fp"))
        mocker.patch("gestor_listas.renamer.identify_track", return_value=None)
        mocker.patch(
            "gestor_listas.renamer.track_from_tags",
            return_value=TrackInfo(title="Canción", artist="Artista"),
        )
        ok, renamed = _process_file(source, "KEY", 0.5, False, apply=True)
        assert ok is True
        assert renamed is True
        assert (tmp_path / "Artista - Canción.mp3").exists()

    def test_preview_does_not_rename(self, tmp_path, mocker) -> None:
        source = tmp_path / "a.mp3"
        source.write_bytes(b"\x00" * 128)
        mocker.patch("gestor_listas.renamer.fingerprint_file", return_value=(10.0, "fp"))
        mocker.patch(
            "gestor_listas.renamer.identify_track",
            return_value=TrackInfo(title="Song", artist="Artist", score=0.9),
        )
        ok, renamed = _process_file(source, "KEY", 0.5, False, apply=False)
        assert ok is True
        assert renamed is False
        assert source.exists()

    def test_apply_renames_and_writes_rating(self, tmp_path, mocker) -> None:
        source = tmp_path / "a.mp3"
        source.write_bytes(b"\x00" * 128)
        mocker.patch("gestor_listas.renamer.fingerprint_file", return_value=(10.0, "fp"))
        track = TrackInfo(title="Song", artist="Artist", score=0.9, rating=4.5)
        mocker.patch("gestor_listas.renamer.identify_track", return_value=track)
        rating = mocker.patch("gestor_listas.renamer.write_rating", return_value=True)

        ok, renamed = _process_file(source, "KEY", 0.5, False, apply=True)
        assert ok is True
        assert renamed is True
        target = tmp_path / "Artist - Song.mp3"
        assert target.exists()
        rating.assert_called_once_with(target, 4.5)


class TestEnsureFfmpegOnPath:
    def test_system_ffmpeg_keeps_path(self, mocker) -> None:
        mocker.patch("gestor_listas.renamer.shutil.which", return_value="/usr/bin/ffmpeg")
        mocker.patch("gestor_listas.renamer.resolve_ffmpeg")
        before = "PATH_VALUE"
        mocker.patch.dict("os.environ", {"PATH": before})
        _ensure_ffmpeg_on_path()
        assert os.environ["PATH"] == before

    def test_bundled_ffmpeg_added_to_path(self, mocker) -> None:
        mocker.patch("gestor_listas.renamer.shutil.which", return_value=None)
        mocker.patch(
            "gestor_listas.renamer.resolve_ffmpeg",
            return_value="/x/y/ffmpeg-linux-x86_64-v6.0/ffmpeg",
        )
        mocker.patch.dict("os.environ", {"PATH": "/usr/bin"})
        _ensure_ffmpeg_on_path()
        assert "/x/y/ffmpeg-linux-x86_64-v6.0" in os.environ["PATH"].split(os.pathsep)
        assert os.environ["PATH"].endswith(os.pathsep + "/usr/bin")

    def test_versioned_binary_creates_symlink(self, mocker, tmp_path) -> None:
        mocker.patch("gestor_listas.renamer.shutil.which", return_value=None)
        mocker.patch(
            "gestor_listas.renamer.resolve_ffmpeg",
            return_value="/x/y/ffmpeg-linux-x86_64-v7.0.2",
        )
        mocker.patch("gestor_listas.renamer.Path.home", return_value=tmp_path)
        mocker.patch.dict("os.environ", {"PATH": "/usr/bin"})
        _ensure_ffmpeg_on_path()
        link = tmp_path / ".cache" / "gestor-listas" / "bin" / "ffmpeg"
        assert link.is_symlink()
        assert os.readlink(link) == "/x/y/ffmpeg-linux-x86_64-v7.0.2"
        assert str(link.parent) in os.environ["PATH"].split(os.pathsep)

    def test_symlink_failure_keeps_path(self, mocker, tmp_path) -> None:
        mocker.patch("gestor_listas.renamer.shutil.which", return_value=None)
        mocker.patch(
            "gestor_listas.renamer.resolve_ffmpeg",
            return_value="/x/y/ffmpeg-linux-x86_64-v7.0.2",
        )
        mocker.patch("gestor_listas.renamer.Path.home", return_value=tmp_path)
        mocker.patch("gestor_listas.renamer.Path.symlink_to", side_effect=OSError("permiso denegado"))
        before = "PATH_VALUE"
        mocker.patch.dict("os.environ", {"PATH": before})
        _ensure_ffmpeg_on_path()
        assert os.environ["PATH"] == before

    def test_resolve_failure_keeps_path(self, mocker) -> None:
        mocker.patch("gestor_listas.renamer.shutil.which", return_value=None)
        mocker.patch("gestor_listas.renamer.resolve_ffmpeg", side_effect=Exception("no ffmpeg"))
        before = "PATH_VALUE"
        mocker.patch.dict("os.environ", {"PATH": before})
        _ensure_ffmpeg_on_path()
        assert os.environ["PATH"] == before


class TestRunRename:
    def test_missing_api_key_exits(self, tmp_path, mocker) -> None:
        mocker.patch("gestor_listas.renamer.acoustid_api_key", return_value=None)
        with pytest.raises(SystemExit) as exc:
            run_rename([str(tmp_path / "a.mp3")], api_key=None)
        assert exc.value.code == 2

    def test_no_audio_files_exits(self, tmp_path, mocker) -> None:
        mocker.patch("gestor_listas.renamer.acoustid_api_key", return_value="KEY")
        with pytest.raises(SystemExit) as exc:
            run_rename([str(tmp_path)])
        assert exc.value.code == 1

    def test_processes_files_and_counts_stats(self, tmp_path, mocker) -> None:
        (tmp_path / "a.mp3").write_bytes(b"\x00" * 128)
        mocker.patch("gestor_listas.renamer.acoustid_api_key", return_value="KEY")
        mocker.patch("gestor_listas.renamer._process_file", return_value=(True, True))
        stats = run_rename([str(tmp_path)])
        assert stats["scanned"] == 1
        assert stats["renamed"] == 1
        assert stats["errors"] == 0

    def test_pauses_between_files(self, tmp_path, mocker) -> None:
        (tmp_path / "a.mp3").write_bytes(b"\x00" * 128)
        (tmp_path / "b.mp3").write_bytes(b"\x00" * 128)
        mocker.patch("gestor_listas.renamer.acoustid_api_key", return_value="KEY")
        mocker.patch("gestor_listas.renamer._process_file", return_value=(True, False))
        sleep = mocker.patch("gestor_listas.renamer.time.sleep")
        run_rename([str(tmp_path)])
        # Con 2 archivos se espera una única pausa (entre el 1º y el 2º).
        sleep.assert_called_once_with(1.0)
