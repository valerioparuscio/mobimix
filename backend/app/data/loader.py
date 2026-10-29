"""Loads the editable reference data from `data/` into validated models.

Files (CLAUDE.md section 17):

    sources.yaml           bibliographic sources referenced by every value
    model_parameters.yaml  global parameters (energy prices, statistics, calendar, valuation)
    mobility_options.yaml  owned assets + walking
    tariffs.yaml           subscriptions and pay-per-use services
    comfort_scores.yaml    comfort / flexibility / reliability per option (merged into options)
    default_profiles.yaml  statistical defaults per residential context
    portfolio_rules.yaml   which candidate portfolios are generated
    feasibility_rules.yaml categorical rules of the feasibility check
    assignment_rules.yaml  tables of the mode assignment (stay hours, weather weight)
    demo_households/       fixed demo profiles (UserProfile), see `load_demo_households`

A `Catalog` is immutable and built explicitly by `load_catalog`; nothing is read from disk
at import time. Cross references (sources, option ids, required parameters) are validated
here, so a typo in a YAML file fails at load time with a precise message.
"""

import hashlib
from collections.abc import Iterator
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel

from app import config
from app.models import (
    AreaDefaults,
    AreaType,
    AssignmentRules,
    DataSourceMetadata,
    FeasibilityRules,
    MissionTemplate,
    MobilityOption,
    Mode,
    ModelParameter,
    OptionScores,
    OptionType,
    Ownership,
    ParameterValue,
    PortfolioRules,
    Purpose,
    QuestionnaireConfig,
    ServiceKind,
    TripBand,
    UserProfile,
)

REQUIRED_PARAMETER_IDS: tuple[str, ...] = (
    "bands.urban_max_km",
    "bands.regional_max_km",
    "energy.petrol_eur_per_l",
    "energy.diesel_eur_per_l",
    "energy.electricity_home_eur_per_kwh",
    "energy.electricity_public_ac_eur_per_kwh",
    "energy.electricity_public_dc_eur_per_kwh",
    "energy.ev_home_charging_share",
    "energy.ev_public_dc_share",
    "emissions.petrol_kg_co2_per_l",
    "emissions.diesel_kg_co2_per_l",
    "emissions.electricity_g_co2_per_kwh",
    "calendar.working_days_per_year",
    "calendar.school_days_per_year",
    "simultaneity.days_per_year.never",
    "simultaneity.days_per_year.rarely",
    "simultaneity.days_per_year.sometimes",
    "simultaneity.days_per_year.often",
    "simultaneity.days_per_year.almost_daily",
    "valuation.value_of_time_eur_per_hour",
    "calendar.local_trip_weeks_per_year",
    "demand.local_trips_shopping_share",
    "demand.school_escort_default_share",
    "usage.taxi_ride_km",
    "usage.car_sharing_minutes_per_rental",
    "usage.car_rental_km_per_day",
    "usage.rail_trip_km",
    "usage.micro_sharing_minutes_per_trip",
    "calibration.car_km_min_ratio",
    "calibration.car_km_max_ratio",
    "costing.material_share",
    "statistics.car_fleet_avg_age_years",
    "feasibility.regular_min_occurrences_per_year",
    "feasibility.rare_max_occurrences_per_year",
    "feasibility.luggage_tolerance_levels",
    "assignment.logit_scale_per_eur",
    "assignment.min_share",
    "assignment.perceived_time_multiplier_at_zero_comfort",
    "assignment.bad_weather_share",
    "assignment.peak_speed_factor.urban",
    "assignment.peak_speed_factor.regional",
    "usage.motorway_toll_eur_per_km",
    "usage.motorway_share.regional",
    "usage.motorway_share.long",
    "usage.destination_mobility_eur_per_day",
    "recommendation.penalty.sell_vehicle",
    "recommendation.penalty.buy_vehicle",
    "recommendation.penalty.cancel_subscription",
    "recommendation.penalty.start_subscription",
    "recommendation.penalty.car_sharing_dependence",
    "recommendation.car_sharing_dependence_min_uses_per_year",
    "recommendation.net_benefit.keep_below",
    "recommendation.net_benefit.consider_from",
    "recommendation.net_benefit.strong_from",
)

REQUIRED_DEFAULT_KEYS: tuple[str, ...] = (
    "car_annual_km_first",
    "car_annual_km_second",
    "parking_cost_year_per_car",
    "workplace_car_cost_per_day",
    "local_trip_car_cost",
    "commute_distance_km_one_way",
    "work_days_per_week",
    "local_trips_per_week_per_adult",
    "local_trip_distance_km_one_way",
    "school_escort_distance_km_one_way",
    "weekend_trips_per_year",
    "weekend_trip_distance_km_one_way",
    "long_weekends_per_year",
    "long_weekend_distance_km_one_way",
    "holiday_trips_per_year",
    "holiday_distance_km_one_way",
    "taxi_trips_per_year",
    "car_sharing_trips_per_year",
    "car_rental_days_per_year",
    "rail_trips_per_year",
    "flights_per_year",
    "bike_scooter_sharing_trips_per_year",
)

REQUIRED_TEMPLATE_PURPOSES: tuple[Purpose, ...] = (
    Purpose.COMMUTE,
    Purpose.STUDY,
    Purpose.SCHOOL_ESCORT,
    Purpose.SHOPPING,
    Purpose.LOCAL_LEISURE,
    Purpose.WEEKEND,
    Purpose.LONG_DISTANCE,
    Purpose.HOLIDAY,
)

REQUIRED_BAND_GROUPS: tuple[str, ...] = (
    "commute_distance_km",
    "annual_km_per_car",
    "parking_cost_year",
    "weekend_trips_per_year",
    "weekend_trip_distance_km",
    "holiday_trips_per_year",
    "holiday_distance_km",
    "taxi_trips_per_year",
    "car_sharing_trips_per_year",
    "car_rental_days_per_year",
)

_DATA_FILES = (
    "sources.yaml",
    "model_parameters.yaml",
    "mobility_options.yaml",
    "tariffs.yaml",
    "comfort_scores.yaml",
    "default_profiles.yaml",
    "questionnaire.yaml",
    "mission_templates.yaml",
    "portfolio_rules.yaml",
    "feasibility_rules.yaml",
    "assignment_rules.yaml",
)


class CatalogError(ValueError):
    """The reference data is inconsistent. The message names the offending file/id."""


@dataclass(frozen=True)
class Catalog:
    data_dir: Path
    version: str
    sources: dict[str, DataSourceMetadata]
    parameters: dict[str, ModelParameter]
    options: dict[str, MobilityOption]
    area_defaults: dict[AreaType, AreaDefaults]
    questionnaire: QuestionnaireConfig
    mission_templates: dict[Purpose, MissionTemplate]
    portfolio_rules: PortfolioRules
    feasibility_rules: FeasibilityRules
    assignment_rules: AssignmentRules

    def parameter(self, parameter_id: str) -> ModelParameter:
        try:
            return self.parameters[parameter_id]
        except KeyError:
            raise KeyError(f"unknown model parameter {parameter_id!r}") from None

    def value(self, parameter_id: str) -> float:
        return self.parameter(parameter_id).value

    def option(self, option_id: str) -> MobilityOption:
        try:
            return self.options[option_id]
        except KeyError:
            raise KeyError(f"unknown mobility option {option_id!r}") from None

    def options_of_mode(self, mode: Mode) -> list[MobilityOption]:
        return [option for option in self.options.values() if option.mode is mode]

    def service_option(self, kind: ServiceKind) -> MobilityOption | None:
        """The option used to price a declared kind of service (taxi trips, rental days...)."""
        return next(
            (option for option in self.options.values() if option.service_kind is kind), None
        )

    def defaults_for(self, area_type: AreaType) -> AreaDefaults:
        return self.area_defaults[area_type]

    def trip_band(self, distance_km: float) -> TripBand:
        """Classify a one-way leg length. Thresholds are model parameters."""
        if distance_km <= self.value("bands.urban_max_km"):
            return TripBand.URBAN
        if distance_km <= self.value("bands.regional_max_km"):
            return TripBand.REGIONAL
        return TripBand.LONG


def iter_parameter_values(obj: Any, path: str = "") -> Iterator[tuple[str, ParameterValue]]:
    """Yield every `ParameterValue` nested in a model, with a dotted path to it."""
    if isinstance(obj, ParameterValue):
        yield path, obj
    elif isinstance(obj, BaseModel):
        for name in type(obj).model_fields:
            child = f"{path}.{name}" if path else name
            yield from iter_parameter_values(getattr(obj, name), child)
    elif isinstance(obj, dict):
        for key, value in obj.items():
            yield from iter_parameter_values(value, f"{path}.{key}" if path else str(key))
    elif isinstance(obj, list | tuple):
        for index, value in enumerate(obj):
            yield from iter_parameter_values(value, f"{path}[{index}]")


def iter_catalog_values(catalog: Catalog) -> Iterator[tuple[str, str, ParameterValue]]:
    """Yield (owner, path, value) for every number in the catalogue."""
    for parameter in catalog.parameters.values():
        yield f"parameter:{parameter.id}", "", parameter
    for option in catalog.options.values():
        for path, value in iter_parameter_values(option):
            yield f"option:{option.id}", path, value
    for defaults in catalog.area_defaults.values():
        for path, value in iter_parameter_values(defaults.values):
            yield f"defaults:{defaults.id}", path, value
    for purpose, template in catalog.mission_templates.items():
        for path, value in iter_parameter_values(template):
            yield f"template:{purpose}", path, value


def _read_yaml(path: Path) -> dict[str, Any]:
    try:
        with path.open(encoding="utf-8") as handle:
            content = yaml.safe_load(handle)
    except FileNotFoundError:
        raise CatalogError(f"missing data file: {path}") from None
    if not isinstance(content, dict):
        raise CatalogError(f"{path.name}: expected a mapping at the top level")
    return content


def _with_meta(entry: dict[str, Any], meta: dict[str, Any], keys: tuple[str, ...]) -> dict:
    """Apply file-level defaults (geographic scope, validity) under entry-level values."""
    defaults = {key: meta[key] for key in keys if key in meta}
    return {**defaults, **entry}


def _unique(items: list[Any], what: str, file_name: str) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for item in items:
        if item.id in result:
            raise CatalogError(f"{file_name}: duplicate {what} id {item.id!r}")
        result[item.id] = item
    return result


def _version(data_dir: Path) -> str:
    """Identifies the content of the data files. Line endings are not content: a file checked out
    on Windows (CRLF) and on Linux (LF) is the same data, so it gets the same version."""
    digest = hashlib.sha256()
    for name in _DATA_FILES:
        digest.update(name.encode())
        digest.update((data_dir / name).read_bytes().replace(b"\r\n", b"\n"))
    return digest.hexdigest()[:12]


def _load_options(data_dir: Path) -> dict[str, MobilityOption]:
    options: dict[str, MobilityOption] = {}
    for file_name in ("mobility_options.yaml", "tariffs.yaml"):
        raw = _read_yaml(data_dir / file_name)
        meta = raw.get("meta", {})
        for entry in raw["options"]:
            option = MobilityOption.model_validate(
                _with_meta(entry, meta, ("geographic_scope", "valid_from", "valid_to"))
            )
            if option.id in options:
                raise CatalogError(f"{file_name}: duplicate option id {option.id!r}")
            options[option.id] = option
    return options


def _merge_scores(options: dict[str, MobilityOption], data_dir: Path) -> dict[str, MobilityOption]:
    raw = _read_yaml(data_dir / "comfort_scores.yaml")
    meta = raw.get("meta", {})
    scores = {key: OptionScores.model_validate(value) for key, value in raw["scores"].items()}

    unknown = scores.keys() - options.keys()
    if unknown:
        raise CatalogError(f"comfort_scores.yaml: unknown option ids {sorted(unknown)}")
    missing = options.keys() - scores.keys()
    if missing:
        raise CatalogError(f"comfort_scores.yaml: no scores for options {sorted(missing)}")

    def as_value(value: float, notes: str | None) -> ParameterValue:
        return ParameterValue(
            value=value, placeholder=bool(meta.get("placeholder", False)), notes=notes
        )

    merged = {}
    for option_id, option in options.items():
        entry = scores[option_id]
        notes = entry.notes or meta.get("notes")
        merged[option_id] = option.model_copy(
            update={
                "comfort_score": as_value(entry.comfort, notes),
                "flexibility_score": as_value(entry.flexibility, notes),
                "reliability_score": as_value(entry.reliability, notes),
            }
        )
    return merged


def _load_area_defaults(data_dir: Path) -> dict[AreaType, AreaDefaults]:
    raw = _read_yaml(data_dir / "default_profiles.yaml")
    defaults = [AreaDefaults.model_validate(entry) for entry in raw["defaults"]]
    by_area: dict[AreaType, AreaDefaults] = {}
    for entry in defaults:
        if entry.area_type in by_area:
            raise CatalogError(f"default_profiles.yaml: duplicate area_type {entry.area_type}")
        by_area[entry.area_type] = entry
    for area_type in AreaType:
        if area_type not in by_area:
            raise CatalogError(f"default_profiles.yaml: missing defaults for {area_type}")
        missing = set(REQUIRED_DEFAULT_KEYS) - by_area[area_type].values.keys()
        if missing:
            raise CatalogError(f"default_profiles.yaml/{area_type}: missing keys {sorted(missing)}")
    return by_area


def _load_questionnaire(data_dir: Path) -> QuestionnaireConfig:
    config = QuestionnaireConfig.model_validate(_read_yaml(data_dir / "questionnaire.yaml"))
    missing = set(REQUIRED_BAND_GROUPS) - config.groups.keys()
    if missing:
        raise CatalogError(f"questionnaire.yaml: missing band groups {sorted(missing)}")
    return config


def _load_mission_templates(data_dir: Path) -> dict[Purpose, MissionTemplate]:
    raw = _read_yaml(data_dir / "mission_templates.yaml")
    placeholder = bool(raw.get("meta", {}).get("placeholder", False))
    templates = {
        Purpose(name): MissionTemplate.model_validate({"placeholder": placeholder, **entry})
        for name, entry in raw["templates"].items()
    }
    missing = set(REQUIRED_TEMPLATE_PURPOSES) - templates.keys()
    if missing:
        raise CatalogError(
            f"mission_templates.yaml: missing templates {sorted(str(p) for p in missing)}"
        )
    return templates


def _load_portfolio_rules(data_dir: Path) -> PortfolioRules:
    raw = _read_yaml(data_dir / "portfolio_rules.yaml")
    placeholder = bool(raw.pop("meta", {}).get("placeholder", False))
    return PortfolioRules.model_validate({"placeholder": placeholder, **raw})


def _load_feasibility_rules(data_dir: Path) -> FeasibilityRules:
    raw = _read_yaml(data_dir / "feasibility_rules.yaml")
    placeholder = bool(raw.pop("meta", {}).get("placeholder", False))
    return FeasibilityRules.model_validate({"placeholder": placeholder, **raw})


def _load_assignment_rules(data_dir: Path) -> AssignmentRules:
    raw = _read_yaml(data_dir / "assignment_rules.yaml")
    placeholder = bool(raw.pop("meta", {}).get("placeholder", False))
    return AssignmentRules.model_validate({"placeholder": placeholder, **raw})


def _validate_portfolio_rules(catalog: Catalog) -> None:
    rules = catalog.portfolio_rules

    def check(option_id: str, what: str, *, ownership: Ownership, option_type=None, mode=None):
        option = catalog.options.get(option_id)
        if option is None:
            raise CatalogError(
                f"portfolio_rules.yaml: {what} refers to unknown option {option_id!r}"
            )
        if option.ownership is not ownership:
            raise CatalogError(f"portfolio_rules.yaml: {what} {option_id!r} must be {ownership}")
        if option_type is not None and option.type is not option_type:
            raise CatalogError(f"portfolio_rules.yaml: {what} {option_id!r} must be {option_type}")
        if mode is not None and option.mode is not mode:
            raise CatalogError(f"portfolio_rules.yaml: {what} {option_id!r} must be mode {mode}")

    vehicles = rules.new_vehicles
    check(
        vehicles.car_compact, "new_vehicles.car_compact", ownership=Ownership.OWNED, mode=Mode.CAR
    )
    check(vehicles.car_family, "new_vehicles.car_family", ownership=Ownership.OWNED, mode=Mode.CAR)
    check(
        vehicles.e_bike,
        "new_vehicles.e_bike",
        ownership=Ownership.OWNED,
        option_type=OptionType.E_BIKE,
    )
    check(
        vehicles.scooter,
        "new_vehicles.scooter",
        ownership=Ownership.OWNED,
        option_type=OptionType.SCOOTER,
    )
    for option_id in rules.service_layer:
        check(option_id, "service_layer", ownership=Ownership.PAY_PER_USE)


def _validate_references(catalog: Catalog) -> None:
    missing = set(REQUIRED_PARAMETER_IDS) - catalog.parameters.keys()
    if missing:
        raise CatalogError(f"model_parameters.yaml: missing required parameters {sorted(missing)}")
    for owner, path, value in iter_catalog_values(catalog):
        if value.source is not None and value.source not in catalog.sources:
            raise CatalogError(f"{owner} {path}: unknown source {value.source!r}")
    _validate_portfolio_rules(catalog)


def load_catalog(data_dir: Path | None = None) -> Catalog:
    """Read, validate and cross-check all reference data."""
    data_dir = Path(data_dir) if data_dir is not None else config.data_dir()

    sources_raw = _read_yaml(data_dir / "sources.yaml")
    sources = _unique(
        [DataSourceMetadata.model_validate(s) for s in sources_raw["sources"]],
        "source",
        "sources.yaml",
    )

    params_raw = _read_yaml(data_dir / "model_parameters.yaml")
    params_meta = params_raw.get("meta", {})
    parameters = _unique(
        [
            ModelParameter.model_validate(
                _with_meta(entry, params_meta, ("geographic_scope", "valid_from", "valid_to"))
            )
            for entry in params_raw["parameters"]
        ],
        "parameter",
        "model_parameters.yaml",
    )

    options = _merge_scores(_load_options(data_dir), data_dir)

    catalog = Catalog(
        data_dir=data_dir,
        version=_version(data_dir),
        sources=sources,
        parameters=parameters,
        options=options,
        area_defaults=_load_area_defaults(data_dir),
        questionnaire=_load_questionnaire(data_dir),
        mission_templates=_load_mission_templates(data_dir),
        portfolio_rules=_load_portfolio_rules(data_dir),
        feasibility_rules=_load_feasibility_rules(data_dir),
        assignment_rules=_load_assignment_rules(data_dir),
    )
    _validate_references(catalog)
    return catalog


@lru_cache(maxsize=1)
def get_catalog() -> Catalog:
    """Process-wide catalogue for the API. Tests and programmatic callers should prefer
    `load_catalog` so they control which data they use."""
    return load_catalog()


def load_demo_households(catalog: Catalog, data_dir: Path | None = None) -> dict[str, UserProfile]:
    """Load the fixed demo households (CLAUDE.md section 32), checking that every vehicle
    and subscription refers to a catalogue option."""
    folder = (Path(data_dir) if data_dir is not None else catalog.data_dir) / "demo_households"
    households: dict[str, UserProfile] = {}
    for path in sorted(folder.glob("*.yaml")):
        profile = UserProfile.model_validate(_read_yaml(path))
        for item in [*profile.vehicles, *profile.subscriptions]:
            if item.option_id not in catalog.options:
                raise CatalogError(f"{path.name}: unknown option_id {item.option_id!r}")
        households[path.stem] = profile
    return households
