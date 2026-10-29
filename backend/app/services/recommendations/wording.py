"""From structured facts to plain Italian (CLAUDE.md section 24).

A recommendation is explained by `ExplanationFact`s - a code and numbers produced by the model.
The sentences are rendered here from those facts and from nothing else, so the text cannot say
what the calculation did not find. Numbers are rounded to what the estimate can support
(CLAUDE.md section 11: no "7.683,24 EUR"): to 50 EUR above 1,000, to 10 above 100, to 5 below.
"""

from collections.abc import Callable

from app.models import ExplanationFact

_STRENGTH_LEAD = {
    "KEEP_CURRENT": "Non conviene cambiare.",
    "SMALL_IMPROVEMENT": "È un piccolo miglioramento.",
    "CONSIDER_CHANGE": "Vale la pena valutarlo.",
    "STRONG_OPPORTUNITY": "È un'opportunità forte.",
}
_CONFIDENCE_WORDS = {"LOW": "bassa", "MEDIUM": "media", "HIGH": "alta"}


def _round_to(value: float, step: float) -> float:
    return round(value / step) * step


def _number(value: float) -> str:
    """12345 -> "12.345"."""
    return f"{value:,.0f}".replace(",", ".")


def _rounded_eur(value: float) -> float:
    magnitude = abs(value)
    step = 50 if magnitude >= 1000 else 10 if magnitude >= 100 else 5 if magnitude >= 20 else 1
    return _round_to(value, step)


def eur(value: float) -> str:
    """An amount of money, rounded to what is worth saying: 3,537 -> "3.550 €". No sign: the
    sentence says whether it is a saving or a cost."""
    return f"{_number(abs(_rounded_eur(value)))} €"


def _signed(value: float) -> str:
    rounded = _rounded_eur(value)
    return f"{'-' if rounded < 0 else ''}{_number(abs(rounded))}"


def eur_per_hour(value: float) -> str:
    """An hourly amount: "58 €", but "1,9 €" where the decimal matters."""
    return f"{value:.0f} €" if value >= 10 else f"{value:.1f}".replace(".", ",") + " €"


def _km(value: float) -> str:
    """Kilometres, to the hundred above a thousand: nobody drove 10,389 km, about 10,400."""
    return _number(_round_to(value, 100 if value >= 1000 else 10))


def eur_range(low: float, high: float) -> str:
    """ "tra 2.900 e 4.500 €": the unit once, at the end, a minus sign where the range is
    negative."""
    return f"tra {_signed(low)} e {_signed(high)} €"


def hours(value: float) -> str:
    magnitude = abs(value)
    rounded = round(magnitude) if magnitude < 100 else _round_to(magnitude, 5)
    return f"{_number(rounded)} {'ora' if rounded == 1 else 'ore'}"


def lower_first(name: str) -> str:
    """ "Taxi" -> "taxi" for the middle of a sentence, but "BikeMi" stays as it is."""
    first, _, rest = name.partition(" ")
    return name if any(ch.isupper() for ch in first[1:]) else name[:1].lower() + name[1:]


def _score(value: float) -> str:
    return f"{value:.1f}".replace(".", ",")


def _verdict(values: dict) -> str:
    return _STRENGTH_LEAD[str(values["strength"])]


def _changes(values: dict) -> str:
    return f"Cosa cambia: {str(values['text']).rstrip('.')}."


def _saving(values: dict) -> str:
    amount, low, high = (float(values[k]) for k in ("eur", "low", "high"))
    wide = high - low >= 10
    if abs(amount) < 5:
        return "Il costo annuo resta praticamente lo stesso."
    if amount > 0:
        spread = f" ({eur_range(low, high)})" if wide else ""
        return f"Risparmi circa {eur(amount)} l'anno{spread}."
    spread = f" ({eur_range(-high, -low)})" if wide else ""
    return f"Spenderesti circa {eur(amount)} l'anno in più{spread}."


def _dropped(values: dict) -> str:
    return f"«{values['name']}» ti costa oggi circa {eur(float(values['eur']))} l'anno."


def _second_car(values: dict) -> str:
    days, low, high = (float(values[k]) for k in ("days", "low", "high"))
    spread = f" (tra {_number(low)} e {_number(high)})" if high - low >= 1 else ""
    return (
        "Una seconda auto serve insieme alla prima solo per circa "
        f"{_number(days)} giorni l'anno{spread}."
    )


def _services(values: dict) -> str:
    return (
        f"Per gli spostamenti che l'auto non copre più useresti {values['names']}, "
        f"per circa {eur(float(values['eur']))} l'anno."
    )


def _extra_time(values: dict) -> str:
    change = float(values["hours"])
    start, end = _number(float(values["from_hours"])), _number(float(values["to_hours"]))
    if abs(change) < 1:
        return "Il tempo passato in viaggio resta lo stesso."
    low, high = float(values["low"]), float(values["high"])
    spread = ""
    if abs(high - low) >= 2:
        spread = f", con una differenza tra {_signed_hours(low)} e {_signed_hours(high)}"
    more = "in più" if change > 0 else "in meno"
    return (
        f"Passeresti circa {hours(change)} {more} l'anno in viaggio: "
        f"da {start} a {end} ore{spread}."
    )


def _signed_hours(value: float) -> str:
    return f"{'+' if value > 0 else '-'}{hours(value)}" if round(value) else "0 ore"


def _comfort(values: dict) -> str:
    start, end = float(values["from_score"]), float(values["to_score"])
    if abs(end - start) < 0.1:
        return f"Il comfort resta intorno a {_score(end)} su 10."
    return f"Il comfort passa da {_score(start)} a {_score(end)} su 10."


def _per_hour(values: dict) -> str:
    amount = eur_per_hour(float(values["eur_per_hour"]))
    return f"Ogni ora di viaggio in più ti fa risparmiare circa {amount}."


def _not_worth_the_time(values: dict) -> str:
    return (
        f"Il risparmio non compensa il tempo che perderesti: circa "
        f"{eur_per_hour(float(values['eur_per_hour']))} per ogni ora in più, "
        f"meno di quanto vale per te ({eur_per_hour(float(values['value_of_time']))} l'ora)."
    )


def _net_benefit(values: dict) -> str:
    net = float(values["eur"])
    parts = []
    if abs(float(values["time_eur"])) >= 10:
        word = "il tempo guadagnato" if float(values["time_eur"]) > 0 else "il tempo in più"
        parts.append(f"{word} ({eur(float(values['time_eur']))})")
    if abs(float(values["comfort_eur"])) >= 10:
        word = "il comfort" if float(values["comfort_eur"]) > 0 else "il minor comfort"
        parts.append(f"{word} ({eur(float(values['comfort_eur']))})")
    if float(values["penalty_eur"]) > 0:
        parts.append(f"lo sforzo del cambiamento ({eur(float(values['penalty_eur']))})")
    counting = (
        f"Contando anche {', '.join(parts[:-1])} e {parts[-1]}"
        if len(parts) > 1
        else f"Contando anche {parts[0]}"
        if parts
        else "Al netto di tutto"
    )
    low, high = float(values["low"]), float(values["high"])
    spread = f" ({eur_range(low, high)})" if abs(high - low) >= 10 else ""
    if net >= 0:
        return f"{counting}, il vantaggio netto è di circa {eur(net)} l'anno{spread}."
    return f"{counting}, il saldo è negativo: circa {eur(net)} l'anno{spread}."


def _tiny_gain(values: dict) -> str:
    return (
        f"Il vantaggio netto (circa {eur(float(values['eur']))} l'anno) è sotto "
        f"i {eur(float(values['threshold']))} che servono a giustificare un cambiamento."
    )


def _environment(values: dict) -> str:
    co2_from, co2_to = float(values["co2_from"]), float(values["co2_to"])
    return (
        f"Km in auto: da {_km(float(values['car_km_from']))} a {_km(float(values['car_km_to']))} "
        f"l'anno. CO2: da {_number(_round_to(co2_from, 10))} a "
        f"{_number(_round_to(co2_to, 10))} kg l'anno."
    )


def _confidence(values: dict) -> str:
    return f"Affidabilità della stima: {_CONFIDENCE_WORDS[str(values['level'])]}."


def _verdict_current(values: dict) -> str:
    return "Tenere la configurazione attuale è la scelta migliore."


def _current_cost(values: dict) -> str:
    return (
        f"La configurazione attuale costa circa {eur(float(values['eur']))} l'anno "
        f"({eur_range(float(values['low']), float(values['high']))}) "
        f"e ti porta a passare circa {hours(float(values['hours']))} l'anno in viaggio."
    )


def _already(values: dict) -> str:
    return f"È già {values['what']} tra quelle realistiche."


def _headline(values: dict) -> str:
    what = lower_first(str(values["text"]).rstrip("."))
    return (
        f"Esiste un'alternativa che conviene valutare ({what}), "
        f"con un vantaggio netto di circa {eur(float(values['net_eur']))} l'anno."
    )


def _best_alternative(values: dict) -> str:
    return (
        f"La migliore alternativa («{values['name']}») darebbe un vantaggio netto di circa "
        f"{eur(float(values['net_eur']))} l'anno: non basta a giustificare il cambiamento."
    )


_RENDERERS: dict[str, Callable[[dict], str]] = {
    "verdict": _verdict,
    "verdict_current": _verdict_current,
    "changes": _changes,
    "saving": _saving,
    "dropped_item_cost": _dropped,
    "second_car_needed": _second_car,
    "services_cost": _services,
    "extra_time": _extra_time,
    "comfort": _comfort,
    "saving_per_extra_hour": _per_hour,
    "not_worth_the_time": _not_worth_the_time,
    "net_benefit": _net_benefit,
    "tiny_gain": _tiny_gain,
    "environment": _environment,
    "confidence": _confidence,
    "current_cost": _current_cost,
    "already": _already,
    "best_alternative": _best_alternative,
    "headline": _headline,
}


def render(facts: list[ExplanationFact]) -> list[str]:
    """One sentence per fact, in the order of the facts. An unknown code is an error: a fact
    nobody can word is a fact nobody can show."""
    try:
        return [_RENDERERS[fact.code](dict(fact.values)) for fact in facts]
    except KeyError as error:
        raise ValueError(f"no wording for the fact or value {error}") from error
