import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as test_client:  # runs the lifespan, i.e. loads the reference data
        yield test_client


def test_health(client):
    response = client.get("/api/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["n_options"] > 0
    assert len(body["parameters_version"]) == 12


def test_mobility_options_reference(client):
    options = client.get("/api/reference/mobility-options").json()
    ids = {option["id"] for option in options}
    assert {"car_small_petrol", "e_bike", "pt_annual_urban_milano", "taxi_milano"} <= ids


def test_assumptions_expose_sources_and_defaults(client):
    body = client.get("/api/reference/assumptions").json()
    assert body["sources"]
    assert len(body["area_defaults"]) == 4
    assert any(p["id"] == "energy.petrol_eur_per_l" for p in body["parameters"])


def test_demo_households_are_serialisable(client):
    households = client.get("/api/reference/demo-households").json()
    assert "family_two_cars" in households
    assert households["family_two_cars"]["household"]["n_children"] == 2


def test_analyze_returns_the_whole_analysis(client):
    profile = client.get("/api/reference/demo-households").json()["urban_single"]
    response = client.post("/api/analyze", json=profile)
    assert response.status_code == 200
    body = response.json()
    assert body["current"]["portfolio_id"] == "current"
    assert body["recommendations"]["headline_portfolio_id"]
    assert body["recommendations"]["recommendations"][0]["portfolio_id"] == "current"
    assert body["parameters_version"]


def test_analyze_validates_the_profile(client):
    response = client.post("/api/analyze", json={"household": {"adults": []}})
    assert response.status_code == 422


def test_cors_allows_the_vite_dev_server(client):
    response = client.options(
        "/api/health",
        headers={
            "Origin": "http://localhost:5173",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert response.headers.get("access-control-allow-origin") == "http://localhost:5173"
