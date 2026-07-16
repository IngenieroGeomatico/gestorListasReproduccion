from unittest.mock import MagicMock

import pytest

from gestor_listas.errors import AuthError, ProviderError
from gestor_listas.importers.youtube import YouTubeImporter
from gestor_listas.model import Playlist, Track


@pytest.fixture
def importer(mocker) -> YouTubeImporter:
    """YouTubeImporter con credenciales fijadas y token de acceso simulado."""
    imp = YouTubeImporter(
        client_id="cid",
        client_secret="csec",
        refresh_token="rtok",
    )
    # Evita cualquier llamada real de OAuth.
    mocker.patch.object(imp, "_ensure_access_token", return_value="access-token")
    return imp


def _resp(mocker, status=200, payload=None, text=""):
    r = mocker.Mock()
    r.status_code = status
    r.json.return_value = payload or {}
    r.text = text
    return r


class TestConstruction:
    def test_missing_credentials_raises(self, monkeypatch) -> None:
        for var in ("YOUTUBE_CLIENT_ID", "YOUTUBE_CLIENT_SECRET", "YOUTUBE_REFRESH_TOKEN"):
            monkeypatch.delenv(var, raising=False)
        with pytest.raises(AuthError, match="credenciales OAuth"):
            YouTubeImporter()

    def test_missing_refresh_token_raises(self, monkeypatch) -> None:
        monkeypatch.delenv("YOUTUBE_REFRESH_TOKEN", raising=False)
        with pytest.raises(AuthError, match="REFRESH_TOKEN"):
            YouTubeImporter(client_id="a", client_secret="b")


class TestCreatePlaylist:
    def test_creates_private_playlist(self, importer, mocker) -> None:
        importer._session.post = MagicMock(return_value=_resp(mocker, payload={
            "id": "PL123",
            "snippet": {"title": "Mi Lista", "description": "desc"},
            "status": {"privacyStatus": "private"},
        }))
        pl = importer.create_playlist("Mi Lista", "desc", public=False)
        assert pl.id == "PL123"
        assert pl.name == "Mi Lista"
        assert pl.public is False
        assert pl.source == "youtube"
        assert "PL123" in pl.source_url


class TestAddVideo:
    def test_add_video(self, importer, mocker) -> None:
        importer._session.post = MagicMock(return_value=_resp(mocker, payload={"id": "item1"}))
        importer.add_video_to_playlist("PL123", "vid1")
        _, kwargs = importer._session.post.call_args
        body = kwargs["json"]
        assert body["snippet"]["playlistId"] == "PL123"
        assert body["snippet"]["resourceId"]["videoId"] == "vid1"


class TestSearchVideo:
    def test_search_found(self, importer, mocker) -> None:
        importer._session.get = MagicMock(return_value=_resp(mocker, payload={
            "items": [{"id": {"videoId": "foundVid"}}]
        }))
        assert importer.search_video_id("Song", "Artist") == "foundVid"

    def test_search_not_found(self, importer, mocker) -> None:
        importer._session.get = MagicMock(return_value=_resp(mocker, payload={"items": []}))
        assert importer.search_video_id("Song", "Artist") is None


class TestVideoIdFromTrack:
    def test_watch_url(self) -> None:
        t = Track(id="x", title="T", artist="A", uri="https://www.youtube.com/watch?v=abc123&t=5")
        assert YouTubeImporter._video_id_from_track(t) == "abc123"

    def test_short_url(self) -> None:
        t = Track(id="x", title="T", artist="A", uri="https://youtu.be/xyz789?si=1")
        assert YouTubeImporter._video_id_from_track(t) == "xyz789"

    def test_non_youtube_uri(self) -> None:
        t = Track(id="x", title="T", artist="A", uri="spotify:track:abc")
        assert YouTubeImporter._video_id_from_track(t) is None


class TestQuotaAndErrors:
    def test_quota_exhausted_raises_provider_error(self, importer, mocker) -> None:
        importer._session.post = MagicMock(return_value=_resp(
            mocker, status=403, text="quotaExceeded: daily limit"
        ))
        with pytest.raises(ProviderError, match="[Cc]uota"):
            importer.create_playlist("x")

    def test_auth_error_on_401(self, importer, mocker) -> None:
        importer._session.get = MagicMock(return_value=_resp(mocker, status=401, text="unauthorized"))
        with pytest.raises(AuthError):
            importer.search_video_id("s", "a")

    def test_generic_api_error(self, importer, mocker) -> None:
        importer._session.post = MagicMock(return_value=_resp(mocker, status=500, text="server error"))
        with pytest.raises(ProviderError, match="500"):
            importer.create_playlist("x")


class TestImportPlaylist:
    def test_import_uses_existing_video_ids_and_search(self, importer, mocker) -> None:
        created = Playlist(id="PLnew", name="Nueva", source="youtube")
        mocker.patch.object(importer, "create_playlist", return_value=created)
        add = mocker.patch.object(importer, "add_video_to_playlist")
        search = mocker.patch.object(importer, "search_video_id", return_value="searchedVid")

        tracks = [
            Track(id="1", title="A", artist="X", uri="https://www.youtube.com/watch?v=directVid"),
            Track(id="2", title="B", artist="Y"),  # sin uri -> se busca
        ]
        src = Playlist(id="src", name="Origen", tracks=tracks)

        result = importer.import_playlist(src)

        assert result.id == "PLnew"
        # El primero usa el id directo; el segundo el buscado.
        assert add.call_count == 2
        add.assert_any_call("PLnew", "directVid")
        add.assert_any_call("PLnew", "searchedVid")
        search.assert_called_once_with("B", "Y")

    def test_import_skips_untraceable_tracks(self, importer, mocker) -> None:
        created = Playlist(id="PLnew", name="Nueva", source="youtube")
        mocker.patch.object(importer, "create_playlist", return_value=created)
        add = mocker.patch.object(importer, "add_video_to_playlist")
        mocker.patch.object(importer, "search_video_id", return_value=None)

        src = Playlist(id="src", name="Origen", tracks=[Track(id="1", title="A", artist="X")])
        importer.import_playlist(src)
        add.assert_not_called()


class TestTokenRefresh:
    def test_ensure_access_token_refreshes(self, mocker) -> None:
        imp = YouTubeImporter(client_id="cid", client_secret="csec", refresh_token="rtok")
        imp._session.post = MagicMock(return_value=_resp(
            mocker, payload={"access_token": "new-token", "expires_in": 3600}
        ))
        token = imp._ensure_access_token()
        assert token == "new-token"

    def test_ensure_access_token_failure_raises(self, mocker) -> None:
        imp = YouTubeImporter(client_id="cid", client_secret="csec", refresh_token="rtok")
        imp._session.post = MagicMock(return_value=_resp(mocker, status=400, text="invalid_grant"))
        with pytest.raises(AuthError, match="refrescar"):
            imp._ensure_access_token()
