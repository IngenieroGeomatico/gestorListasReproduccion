"""Tests de la infraestructura nueva: config, errors y http."""

import pytest

from gestor_listas import errors
from gestor_listas.config import DeezerConfig, SpotifyConfig
from gestor_listas.http import make_session


class TestErrorsHierarchy:
    def test_all_inherit_base(self) -> None:
        assert issubclass(errors.ConfigError, errors.GestorListasError)
        assert issubclass(errors.ProviderError, errors.GestorListasError)
        assert issubclass(errors.DownloadError, errors.GestorListasError)

    def test_auth_is_provider_error(self) -> None:
        assert issubclass(errors.AuthError, errors.ProviderError)

    def test_playlist_not_found_is_value_error(self) -> None:
        # Compatibilidad hacia atrás: se puede capturar como ValueError.
        assert issubclass(errors.PlaylistNotFoundError, ValueError)
        assert issubclass(errors.PlaylistNotFoundError, errors.ProviderError)

    def test_can_catch_specific_as_base(self) -> None:
        with pytest.raises(errors.GestorListasError):
            raise errors.AuthError("boom")


class TestSpotifyConfig:
    def test_from_env_reads_values(self, monkeypatch) -> None:
        monkeypatch.setenv("SPOTIFY_CLIENT_ID", "cid")
        monkeypatch.setenv("SPOTIFY_CLIENT_SECRET", "csec")
        monkeypatch.setenv("SPOTIFY_BEARER_TOKEN", "bearer")
        cfg = SpotifyConfig.from_env()
        assert cfg.client_id == "cid"
        assert cfg.client_secret == "csec"
        assert cfg.bearer_token == "bearer"

    def test_defaults_when_unset(self, monkeypatch) -> None:
        for var in ("SPOTIFY_CLIENT_ID", "SPOTIFY_BEARER_TOKEN", "SPOTIFY_REFRESH_TOKEN"):
            monkeypatch.delenv(var, raising=False)
        cfg = SpotifyConfig.from_env()
        assert cfg.client_id == ""
        assert cfg.bearer_token is None
        # Las credenciales spotDL tienen valor por defecto no vacío.
        assert cfg.spotdl_client_id

    def test_spotdl_override(self, monkeypatch) -> None:
        monkeypatch.setenv("SPOTDL_CLIENT_ID", "mine")
        monkeypatch.setenv("SPOTDL_CLIENT_SECRET", "secret")
        cfg = SpotifyConfig.from_env()
        assert cfg.spotdl_client_id == "mine"
        assert cfg.spotdl_client_secret == "secret"


class TestDeezerConfig:
    def test_from_env_reads_values(self, monkeypatch) -> None:
        monkeypatch.setenv("DEEZER_ARL", "arlvalue")
        monkeypatch.setenv("DEEZER_EMAIL", "a@b.com")
        monkeypatch.setenv("DEEZER_PASSWORD", "pw")
        cfg = DeezerConfig.from_env()
        assert cfg.arl == "arlvalue"
        assert cfg.email == "a@b.com"
        assert cfg.password == "pw"

    def test_defaults_when_unset(self, monkeypatch) -> None:
        for var in ("DEEZER_ARL", "DEEZER_ACCESS_TOKEN", "DEEZER_EMAIL", "DEEZER_PASSWORD"):
            monkeypatch.delenv(var, raising=False)
        cfg = DeezerConfig.from_env()
        assert cfg.arl is None
        assert cfg.access_token is None


class TestHttpSession:
    def test_make_session_has_adapters(self) -> None:
        session = make_session()
        assert session.get_adapter("https://x") is not None
        assert session.get_adapter("http://x") is not None
        session.close()

    def test_retry_configured(self) -> None:
        session = make_session(total_retries=5, backoff_factor=1.0)
        adapter = session.get_adapter("https://api.spotify.com")
        retries = adapter.max_retries
        assert retries.total == 5
        assert retries.backoff_factor == 1.0
        assert 429 in retries.status_forcelist
        session.close()

    def test_custom_user_agent(self) -> None:
        session = make_session(user_agent="MiApp/1.0")
        assert session.headers["User-Agent"] == "MiApp/1.0"
        session.close()

    def test_default_user_agent(self) -> None:
        session = make_session()
        assert session.headers["User-Agent"]
        session.close()
