"""Writes JSON snapshots of the backend reference data for the frontend tests.

    python -m app.data.export_demo_fixture

The frontend mapper tests (frontend/src/form/mapping.test.ts) round-trip the demo households
through the questionnaire form, using the real answer bands and the option catalogue; the
tests of the results screen (frontend/src/results/view.test.ts) read the real analysis of each
demo household. A backend test fails when these files are out of date.
"""

import json
from pathlib import Path

from app import config
from app.data.loader import Catalog, load_catalog, load_demo_households
from app.services.pipeline import analyze

FIXTURE_DIR = config.REPO_ROOT / "frontend" / "src" / "form" / "fixtures"
OPTION_FIELDS = {"id", "name", "type", "mode", "ownership", "min_age", "max_age"}
# Parts of the analysis the results screen does not read, left out to keep the fixture small.
ANALYSIS_NOT_READ = {
    "demand": True,
    "current": {"cost_lines", "cost_by_category"},
    "evaluations": {"__all__": {"cost_lines", "cost_by_category"}},
}


def build(catalog: Catalog | None = None) -> dict[str, object]:
    """File name -> JSON-serialisable content."""
    catalog = catalog or load_catalog()
    households = load_demo_households(catalog)
    return {
        "demo_households.json": {
            name: profile.model_dump(mode="json") for name, profile in households.items()
        },
        # What /api/analyze returns for each demo household, for the tests of the results screen.
        # The demand and the cost lines are left out: the screen does not read them.
        "analyses.json": {
            name: analyze(catalog, profile).model_dump(mode="json", exclude=ANALYSIS_NOT_READ)
            for name, profile in households.items()
        },
        "questionnaire.json": catalog.questionnaire.model_dump(mode="json"),
        "mobility_options.json": [
            option.model_dump(mode="json", include=OPTION_FIELDS)
            for option in catalog.options.values()
        ],
    }


def render(content: object) -> str:
    return json.dumps(content, indent=2, ensure_ascii=False) + "\n"


def main(directory: Path = FIXTURE_DIR) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    for name, content in build().items():
        (directory / name).write_text(render(content), encoding="utf-8")
        print(f"wrote {directory / name}")


if __name__ == "__main__":
    main()
