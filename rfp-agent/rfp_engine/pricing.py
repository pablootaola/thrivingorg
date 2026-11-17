"""Price construction. The numbers here are defaults; the private config overrides them
from the governing pricing rubric at run time, so a ruling change never needs a code change.

Tests in order: (1) stay inside a published budget by cutting scope, never by shaving
price silently; (2) come in under a known competitor benchmark; (3) the floor beats
tests 1 and 2; (4) weigh price points: at heavy price weighting where the firm will
not be lowest, price to the floor.
"""
from __future__ import annotations

from dataclasses import dataclass, field

DEFAULT_RATES = {"principal": 250.0, "senior": 150.0, "delivery": 110.0, "analyst": 75.0}
DEFAULT_FLOOR = 95.0  # blended $/h
DEFAULT_WALKAWAY = 75.0  # blended $/h, below this the code is PRICE
DEFAULT_MIN_ENGAGEMENT = 7500.0  # RFIs, sources sought, capability statements, prequals exempt


@dataclass
class Plan:
    hours: dict[str, float]  # seat -> hours
    rates: dict[str, float] = field(default_factory=lambda: dict(DEFAULT_RATES))
    expenses: float = 0.0

    @property
    def total_hours(self) -> float:
        return sum(self.hours.values())

    @property
    def card_price(self) -> float:
        return sum(h * self.rates[s] for s, h in self.hours.items()) + self.expenses


@dataclass
class PriceDecision:
    price: float
    blended: float
    basis: list[str]
    code: str = ""  # "PRICE" when below walk-away
    scope_cut_needed: bool = False


def decide(plan: Plan, *, budget: float | None = None, competitor_benchmark: float | None = None,
           price_weight: float | None = None, floor: float = DEFAULT_FLOOR, walkaway: float = DEFAULT_WALKAWAY,
           min_engagement: float = DEFAULT_MIN_ENGAGEMENT, exempt_minimum: bool = False,
           undercut: float = 0.05) -> PriceDecision:
    hrs = plan.total_hours or 1.0
    price = plan.card_price
    basis = [f"card {price:,.0f} over {hrs:,.0f} h"]
    floor_price = floor * hrs + plan.expenses
    scope_cut = False
    if budget is not None and price > budget:
        scope_cut = True
        basis.append(f"published budget {budget:,.0f}: cut scope to fit, do not shave rate")
    if competitor_benchmark is not None and price >= competitor_benchmark:
        target = competitor_benchmark * (1 - undercut)
        basis.append(f"competitor benchmark {competitor_benchmark:,.0f}, target {target:,.0f}")
        price = target
    if price_weight is not None and price_weight >= 0.40 and competitor_benchmark is not None:
        basis.append(f"price weight {price_weight:.0%}: price to floor")
        price = floor_price
    if price < floor_price:
        basis.append(f"floor {floor:,.0f}/h holds at {floor_price:,.0f}")
        price = floor_price
    if not exempt_minimum and price < min_engagement:
        basis.append(f"minimum engagement {min_engagement:,.0f}")
        price = min_engagement
    blended = (price - plan.expenses) / hrs
    code = "PRICE" if budget is not None and (budget - plan.expenses) / hrs < walkaway else ""
    if code:
        basis.append(f"budget implies {(budget - plan.expenses) / hrs:,.0f}/h, below walk-away {walkaway:,.0f}/h")
    return PriceDecision(price=round(price, 2), blended=round(blended, 2), basis=basis, code=code,
                         scope_cut_needed=scope_cut)


def value_estimate(budget: float | None = None, analog_awards: list[float] | None = None,
                   effort_hours: float | None = None, blended_rate: float = 150.0) -> tuple[float | None, float | None, float | None, str]:
    """value_low, value_mid, value_high, value_basis. Evidence order: published budget,
    then analog award prices, then an effort model. The basis names which was used."""
    if budget:
        return budget * 0.8, budget, budget, "published budget"
    if analog_awards:
        a = sorted(analog_awards)
        mid = a[len(a) // 2]
        return a[0], mid, a[-1], f"analog awards n={len(a)}"
    if effort_hours:
        mid = effort_hours * blended_rate
        return mid * 0.7, mid, mid * 1.4, f"effort model {effort_hours:.0f} h at {blended_rate:.0f}/h"
    return None, None, None, "not estimable from evidence held"
