"""The server that also serves the web app (how it runs when published): MOBIMIX_STATIC_DIR."""

import pytest
from fastapi.testclient import TestClient

from app.main import create_app


@pytest.fixture
def web(tmp_path):
    (tmp_path / "assets").mkdir()
    (tmp_path / "index.html").write_text("<!doctype html><title>MobiMix</title>", encoding="utf-8")
    (tmp_path / "assets" / "app.js").write_text("console.log('x')", encoding="utf-8")
    return tmp_path


def client_for(monkeypatch, folder) -> TestClient:
    monkeypatch.setenv("MOBIMIX_STATIC_DIR", str(folder))
    return TestClient(create_app())


def test_the_web_app_is_served_from_the_same_address_as_the_api(monkeypatch, web):
    with client_for(monkeypatch, web) as client:
        page = client.get("/")
        assert page.status_code == 200
        assert "text/html" in page.headers["content-type"]
        assert "<title>MobiMix</title>" in page.text
        assert client.get("/assets/app.js").status_code == 200


def test_the_api_and_its_documentation_come_first(monkeypatch, web):
    with client_for(monkeypatch, web) as client:
        assert client.get("/api/health").json()["status"] == "ok"
        assert client.get("/openapi.json").json()["info"]["title"] == "MobiMix Personal API"
        assert "text/html" in client.get("/docs").headers["content-type"]


def test_an_unknown_path_is_not_found_not_the_home_page(monkeypatch, web):
    with client_for(monkeypatch, web) as client:
        assert client.get("/api/nothing-here").status_code == 404
        assert client.get("/nothing-here").status_code == 404


def test_without_the_setting_the_server_is_the_api_alone(monkeypatch):
    monkeypatch.delenv("MOBIMIX_STATIC_DIR", raising=False)
    with TestClient(create_app()) as client:
        assert client.get("/").status_code == 404
        assert client.get("/api/health").status_code == 200


def test_a_setting_that_is_not_a_folder_stops_the_server(monkeypatch, tmp_path):
    monkeypatch.setenv("MOBIMIX_STATIC_DIR", str(tmp_path / "missing"))
    with pytest.raises(RuntimeError, match="MOBIMIX_STATIC_DIR"):
        create_app()
