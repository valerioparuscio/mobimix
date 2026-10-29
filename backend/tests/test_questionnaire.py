import json
import math

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.data.export_demo_fixture import FIXTURE_DIR, build
from app.data.loader import REQUIRED_BAND_GROUPS, Catalog
from app.main import app
from app.models import BandGroup, NumericAnswer, OtherMobility


class TestBands:
    def test_all_required_groups_are_present(self, catalog: Catalog):
        assert set(REQUIRED_BAND_GROUPS) <= catalog.questionnaire.groups.keys()

    def test_every_group_offers_a_no_usage_or_smallest_band(self, catalog: Catalog):
        for name, group in catalog.questionnaire.groups.items():
            assert len(group.bands) >= 2, name

    def test_zero_cost_and_never_are_exact_answers(self, catalog: Catalog):
        groups = catalog.questionnaire.groups
        for name, band_id in [
            ("parking_cost_year", "none"),
            ("taxi_trips_per_year", "never"),
            ("car_rental_days_per_year", "never"),
            ("holiday_trips_per_year", "one"),
        ]:
            band = next(b for b in groups[name].bands if b.id == band_id)
            assert band.low == band.high, (name, band_id)

    def test_word_to_number_groups_are_flagged_as_placeholders(self, catalog: Catalog):
        groups = catalog.questionnaire.groups
        for name in (
            "weekend_trips_per_year",
            "taxi_trips_per_year",
            "car_sharing_trips_per_year",
            "car_rental_days_per_year",
        ):
            assert groups[name].placeholder, name

    def test_every_band_is_a_valid_numeric_answer(self, catalog: Catalog):
        for group in catalog.questionnaire.groups.values():
            for band in group.bands:
                answer = (
                    NumericAnswer(exact=band.low)
                    if band.low == band.high
                    else NumericAnswer(low=band.low, high=band.high)
                )
                assert answer.kind in ("exact", "range")

    def test_rental_days_is_part_of_other_mobility(self):
        assert OtherMobility().car_rental_days_per_year.kind == "unknown"


class TestBandValidation:
    BAND = {"label": "x", "low": 0, "high": 1}

    def test_bands_must_be_ascending(self):
        with pytest.raises(ValidationError, match="ascending"):
            BandGroup.model_validate(
                {"bands": [{"id": "a", **self.BAND, "low": 5, "high": 6}, {"id": "b", **self.BAND}]}
            )

    def test_band_ids_must_be_unique(self):
        with pytest.raises(ValidationError, match="unique"):
            BandGroup.model_validate(
                {"bands": [{"id": "a", **self.BAND}, {"id": "a", **self.BAND}]}
            )

    def test_band_low_must_not_exceed_high(self):
        with pytest.raises(ValidationError, match="low must not exceed high"):
            BandGroup.model_validate(
                {"bands": [{"id": "a", **self.BAND, "low": 3, "high": 1}, {"id": "b", **self.BAND}]}
            )


def test_questionnaire_endpoint():
    with TestClient(app) as client:
        body = client.get("/api/reference/questionnaire").json()
    assert "annual_km_per_car" in body["groups"]
    first_band = body["groups"]["annual_km_per_car"]["bands"][0]
    assert {"id", "label", "low", "high"} <= first_band.keys()


def same_data(a, b) -> bool:
    """Equal JSON data, numbers compared to about nine digits: the last digit of a computed
    number can differ between operating systems (another maths library), which is not staleness."""
    if isinstance(a, dict) and isinstance(b, dict):
        return a.keys() == b.keys() and all(same_data(a[key], b[key]) for key in a)
    if isinstance(a, list) and isinstance(b, list):
        return len(a) == len(b) and all(same_data(x, y) for x, y in zip(a, b, strict=True))
    if isinstance(a, float) or isinstance(b, float):
        return (
            isinstance(a, int | float)
            and isinstance(b, int | float)
            and math.isclose(a, b, rel_tol=1e-9, abs_tol=1e-9)
        )
    return a == b


def test_frontend_fixtures_are_up_to_date():
    """The frontend mapper tests use JSON snapshots of the backend reference data."""
    for name, content in build().items():
        snapshot = json.loads((FIXTURE_DIR / name).read_text(encoding="utf-8"))
        assert same_data(snapshot, content), (
            f"frontend/src/form/fixtures/{name} is stale: "
            "run `python -m app.data.export_demo_fixture` from backend/"
        )
