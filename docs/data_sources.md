# Data sources

All sources were retrieved on 2026-10-28 through web search. The machine-readable registry is
[data/sources.yaml](../data/sources.yaml); every value in the data files points to an entry of
that registry through its `source` field.

Many entries are **press articles reporting a primary source** (ATM, IVASS, ISTAT...). Before
using a number for anything beyond the MVP, check it against the primary source.

## Sources used

| Id | What it provides | Reliability note |
|---|---|---|
| `mimit_carburanti_2026_10` | petrol 2.022 and diesel 2.260 EUR/l (self, road network, 23/10/2026) | official MIMIT data, spot and volatile |
| `ev_ricarica_2026` | EV charging: home ~0.25, public AC 0.63, DC 0.74 EUR/kWh; 16 kWh/100 km | secondary (press), sources disagree on home price |
| `ivass_rc_auto_2025` | average RC auto premium 438 EUR | secondary; varies strongly by province and class |
| `sum_money_costo_auto` | TCO of a small car, sedan and EV; ~10%/year depreciation | online simulator, not official |
| `isfort_costo_auto_2026` | 334 EUR/month average, range 2,329-4,486 EUR/year | secondary; used only as a sanity check |
| `alvolante_costi_2026` | EV vs diesel maintenance and depreciation | magazine estimate |
| `atm_tariffe_milano` | ATM passes (330 annual, 39 monthly, under-27 200, senior 300, Mi1-Mi3 460) and ticket 2.20 | press; the annual pass and the ticket were confirmed by the product owner on 2026-10-30 |
| `trenord_tariffe_2026` | Lombardy-wide annual pass ~1,137 EUR; ticket 21-50 km 5.40 EUR | press; official PDF has the per-distance tables (not yet modelled) |
| `taxi_milano_2026` | 1.32 EUR/km, 34.48 EUR/h, base fare 4.10 EUR | other sources report 1.20 / 31.30: verify with the Comune |
| `free2move_milano` | ~0.21 EUR/min, 9.99 EUR/h, 43.33 EUR/day | official page, undated |
| `bikemi` | annual 36 EUR (24 with ATM annual), day pass 4.50 EUR | secondary |
| `noleggio_auto_2026` | ~37-45 EUR/day small car | commercial comparison sites |
| `ebike_prezzi_italia` | e-city reference ~2,200 EUR; sample 1,350-3,500 EUR | model-level, not a market average |
| `treno_av_prezzi` | Milan-Rome 20-120 EUR over ~570 km (per-km value is own derivation) | commercial blogs |
| `istat_percorrenze_2023` | ~10,950 km/vehicle/year (UNRAE 10,712; ACI 10,647) | official |
| `aci_annuario_2025` | average fleet age 13 years | official, via press |
| `audimob_2025` | trips per day, 80% within 10 km; average trip ~9 km (own derivation) | official, via press |
| `ispra_fattori_emissione` | electricity mix ~280 gCO2/kWh | 2021 value, to be updated |

## Gaps (searched, not found)

These values are placeholders or unsourced estimates until a real source is found:

- ISPRA emission factors per passenger-km for PT, rail and air.
- Official Comune di Milano taxi tariff (scatto, minimum fare, time component).
- Ride-hailing / NCC tariffs in Milan.
- Kick-scooter and moped sharing tariffs in Milan.
- Car-sharing subscription products and the per-km rate beyond the included kilometres.
- E-bike maintenance and battery replacement cost; bicycle, scooter and motorcycle prices.
- Trenord annual passes by distance band (only the Lombardy-wide pass is modelled).
- Garage / parking cost by area; flight prices.
- Any statistical default by area type (`default_profiles.yaml`): all are reasoned placeholders.
