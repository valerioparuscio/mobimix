import pytest

from app.data.loader import Catalog, load_catalog
from app.models import EnergyCarrier


@pytest.fixture(scope="session")
def catalog() -> Catalog:
    return load_catalog()


def _naive_annual_cost(catalog: Catalog, option_id: str, annual_km: float) -> float:
    """Independent TCO formula for a NEW vehicle (brief section 12), used to sanity-check the
    data and to cross-check the real cost model, which must agree with it."""
    option = catalog.option(option_id)
    assert option.purchase_price and option.residual_value and option.expected_lifetime_years
    depreciation = (
        option.purchase_price.value - option.residual_value.value
    ) / option.expected_lifetime_years.value
    fixed = sum(
        item.value
        for item in (option.maintenance_cost_year, option.insurance_cost_year, option.tax_cost_year)
        if item is not None
    )
    variable = (option.cost_per_km.value if option.cost_per_km else 0) * annual_km
    assert option.energy is not None
    units = option.energy.consumption_per_100km.value / 100 * annual_km
    if option.energy.carrier is EnergyCarrier.PETROL:
        price = catalog.value("energy.petrol_eur_per_l")
    elif option.energy.carrier is EnergyCarrier.DIESEL:
        price = catalog.value("energy.diesel_eur_per_l")
    else:
        home_share = catalog.value("energy.ev_home_charging_share")
        dc_share = catalog.value("energy.ev_public_dc_share")
        public = dc_share * catalog.value("energy.electricity_public_dc_eur_per_kwh") + (
            1 - dc_share
        ) * catalog.value("energy.electricity_public_ac_eur_per_kwh")
        price = (
            home_share * catalog.value("energy.electricity_home_eur_per_kwh")
            + (1 - home_share) * public
        )
    return depreciation + fixed + variable + units * price


@pytest.fixture(scope="session")
def naive_annual_cost():
    """Independent, from-scratch TCO of a NEW vehicle, to cross-check the cost model."""
    return _naive_annual_cost
