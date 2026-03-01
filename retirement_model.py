from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path


COMBINED_ON_2025_TAX_BRACKETS: list[tuple[float, float]] = [
    (16258.0, 0.00),
    (52886.0, 0.2005),
    (57375.0, 0.2415),
    (105775.0, 0.2965),
    (109727.0, 0.3148),
    (114750.0, 0.3389),
    (150000.0, 0.3791),
    (177882.0, 0.4341),
    (220000.0, 0.4497),
    (253414.0, 0.4829),
    (float("inf"), 0.5353),
]

DEFAULT_CAPITAL_GAINS_INCLUSION_RATE = 0.50
OAS_CLAWBACK_BASE_THRESHOLD_2025 = 90997.0
OAS_CLAWBACK_RECOVERY_RATE = 0.15
PENSION_INCOME_CREDIT_ELIGIBLE_AMOUNT = 2000.0
PENSION_INCOME_CREDIT_COMBINED_RATE = 0.2005
RRIF_MIN_WITHDRAWAL_RATES_BY_AGE: dict[int, float] = {
    71: 0.0528,
    72: 0.0540,
    73: 0.0553,
    74: 0.0567,
    75: 0.0582,
    76: 0.0598,
    77: 0.0617,
    78: 0.0636,
    79: 0.0658,
    80: 0.0682,
    81: 0.0708,
    82: 0.0738,
    83: 0.0771,
    84: 0.0808,
    85: 0.0851,
    86: 0.0899,
    87: 0.0955,
    88: 0.1021,
    89: 0.1099,
    90: 0.1192,
    91: 0.1306,
    92: 0.1449,
    93: 0.1634,
    94: 0.1879,
    95: 0.2000,
}

STRATEGY_LABELS: dict[str, str] = {
    "rrif_first": "RRIF then Non-Reg then TFSA",
    "non_registered_first": "Non-Reg then TFSA then RRIF",
    "bracket_fill": "Bracket-fill",
    "tax_smoothing": "Tax-smoothing",
}


@dataclass
class RetirementInputs:
    current_age: int
    retirement_age: int
    life_expectancy: int
    current_rrif_balance: float
    current_rrsp_balance: float
    current_non_rrif_balance: float
    current_tfsa_balance: float
    annual_income_post_tax_today: float
    annual_rate_of_return: float
    inflation_rate: float
    annual_oas_income: float
    annual_cpp_income: float
    annual_pension_income: float
    oas_start_age: int
    cpp_start_age: int
    pension_start_age: int
    annual_rrsp_contribution: float
    annual_tfsa_contribution: float
    annual_non_registered_contribution: float
    current_appreciating_assets: float = 0.0
    taxable_non_registered_withdrawal_percent: float = 100.0
    apply_oas_clawback: bool = True
    apply_minimum_rrif_withdrawals: bool = True
    apply_pension_income_tax_credit: bool = False


@dataclass
class RetirementProjection:
    years: list[int]
    total_balances: list[float]
    rrif_balances: list[float]
    non_rrif_balances: list[float]
    tfsa_balances: list[float]
    taxable_non_rrif_balances: list[float]
    appreciating_assets: list[float]
    portfolio_withdrawals: list[float]
    rrif_withdrawals: list[float]
    tfsa_withdrawals: list[float]
    taxable_non_rrif_withdrawals: list[float]
    gross_income_targets: list[float]
    government_benefits: list[float]
    net_retirement_incomes: list[float]
    income_taxes: list[float]
    capital_gains_taxes: list[float]
    oas_clawbacks: list[float]
    total_taxes: list[float]
    average_tax_rates: list[float]
    marginal_tax_rates: list[float]
    post_tax_income_targets: list[float]
    depleted_age: int | None
    years_to_retirement: int
    retirement_start_age: int
    balance_at_retirement: float


def available_strategies() -> list[dict[str, str]]:
    return [{"id": strategy_id, "label": label} for strategy_id, label in STRATEGY_LABELS.items()]


def tax_brackets_reference() -> dict[str, list[dict[str, float | None]]]:
    def serialize(brackets: list[tuple[float, float]]) -> list[dict[str, float | None]]:
        rows: list[dict[str, float | None]] = []
        for upper, rate in brackets:
            rows.append(
                {
                    "upTo": None if upper == float("inf") else upper,
                    "rate": rate,
                }
            )
        return rows

    return {
        "combinedOntario": serialize(COMBINED_ON_2025_TAX_BRACKETS),
    }


def project_retirement(inputs: RetirementInputs, strategy: str = "rrif_first") -> RetirementProjection:
    if strategy not in STRATEGY_LABELS:
        raise ValueError(f"Unsupported strategy: {strategy}")
    if inputs.current_age <= 0:
        raise ValueError("Current age must be positive.")
    retirement_start_age = max(inputs.current_age, inputs.retirement_age)
    if inputs.life_expectancy < retirement_start_age:
        raise ValueError("Life expectancy must be at or above the retirement simulation start age.")
    arr = inputs.annual_rate_of_return / 100.0
    inflation = inputs.inflation_rate / 100.0
    capital_gains_inclusion = DEFAULT_CAPITAL_GAINS_INCLUSION_RATE
    taxable_non_registered_withdrawal_share = min(1.0, max(0.0, inputs.taxable_non_registered_withdrawal_percent / 100.0))

    def progressive_tax(taxable_income: float, years_from_retirement_start: int) -> float:
        income = max(0.0, taxable_income)
        indexing_factor = (1 + inflation) ** max(0, years_from_retirement_start)

        def indexed_brackets(brackets: list[tuple[float, float]]) -> list[tuple[float, float]]:
            adjusted: list[tuple[float, float]] = []
            for upper, rate in brackets:
                adjusted_upper = float("inf") if upper == float("inf") else upper * indexing_factor
                adjusted.append((adjusted_upper, rate))
            return adjusted

        def bracket_tax(amount: float, brackets: list[tuple[float, float]]) -> float:
            tax_value = 0.0
            lower = 0.0
            for upper, rate in brackets:
                if amount <= lower:
                    break
                taxable_at_rate = min(amount, upper) - lower
                tax_value += taxable_at_rate * rate
                lower = upper
            return tax_value

        combined_indexed = indexed_brackets(COMBINED_ON_2025_TAX_BRACKETS)
        return bracket_tax(income, combined_indexed)

    def marginal_tax_rate(taxable_income: float, years_from_retirement_start: int) -> float:
        income = max(0.0, taxable_income)
        indexing_factor = (1 + inflation) ** max(0, years_from_retirement_start)

        def indexed_brackets(brackets: list[tuple[float, float]]) -> list[tuple[float, float]]:
            adjusted: list[tuple[float, float]] = []
            for upper, rate in brackets:
                adjusted_upper = float("inf") if upper == float("inf") else upper * indexing_factor
                adjusted.append((adjusted_upper, rate))
            return adjusted

        def bracket_marginal_rate(amount: float, brackets: list[tuple[float, float]]) -> float:
            lower = 0.0
            for upper, rate in brackets:
                if amount <= upper:
                    return rate
                lower = upper
            return brackets[-1][1]

        combined_rate = bracket_marginal_rate(income, indexed_brackets(COMBINED_ON_2025_TAX_BRACKETS))
        return combined_rate

    def oas_clawback_amount(net_income_for_oas: float, oas_received: float, years_from_retirement_start: int) -> float:
        if not inputs.apply_oas_clawback:
            return 0.0
        if oas_received <= 0:
            return 0.0
        threshold = OAS_CLAWBACK_BASE_THRESHOLD_2025 * ((1 + inflation) ** max(0, years_from_retirement_start))
        recovery_base = max(0.0, net_income_for_oas - threshold)
        return min(oas_received, recovery_base * OAS_CLAWBACK_RECOVERY_RATE)

    def rrif_min_withdrawal_rate(age: int) -> float:
        if age <= 70:
            denominator = max(1, 90 - age)
            return 1.0 / denominator
        if age >= 95:
            return RRIF_MIN_WITHDRAWAL_RATES_BY_AGE[95]
        return RRIF_MIN_WITHDRAWAL_RATES_BY_AGE.get(age, RRIF_MIN_WITHDRAWAL_RATES_BY_AGE[95])

    def pension_income_tax_credit(age: int, pension_income_amount: float, rrif_withdrawal_amount: float) -> float:
        if not inputs.apply_pension_income_tax_credit:
            return 0.0
        eligible_income = max(0.0, pension_income_amount)
        if age >= 65:
            eligible_income += max(0.0, rrif_withdrawal_amount)
        eligible_credit_base = min(PENSION_INCOME_CREDIT_ELIGIBLE_AMOUNT, eligible_income)
        return eligible_credit_base * PENSION_INCOME_CREDIT_COMBINED_RATE

    years_to_retirement = max(0, inputs.retirement_age - inputs.current_age)
    rrif_balance = inputs.current_rrif_balance
    rrsp_balance = inputs.current_rrsp_balance
    tfsa_balance = max(0.0, min(inputs.current_tfsa_balance, inputs.current_non_rrif_balance))
    taxable_non_rrif_balance = max(0.0, inputs.current_non_rrif_balance - tfsa_balance)
    appreciating_assets_balance = max(0.0, inputs.current_appreciating_assets)

    for _ in range(years_to_retirement):
        rrif_balance = rrif_balance * (1 + arr)
        rrsp_balance = rrsp_balance * (1 + arr) + inputs.annual_rrsp_contribution
        tfsa_balance = tfsa_balance * (1 + arr) + inputs.annual_tfsa_contribution
        taxable_non_rrif_balance = (
            taxable_non_rrif_balance * (1 + arr)
            + inputs.annual_non_registered_contribution
        )
        appreciating_assets_balance = appreciating_assets_balance * (1 + inflation)

    rrif_balance += rrsp_balance
    non_rrif_balance = tfsa_balance + taxable_non_rrif_balance
    balance_at_retirement = rrif_balance + non_rrif_balance + appreciating_assets_balance

    years: list[int] = []
    total_balances: list[float] = []
    rrif_balances: list[float] = []
    non_rrif_balances: list[float] = []
    tfsa_balances: list[float] = []
    taxable_non_rrif_balances: list[float] = []
    appreciating_assets: list[float] = []
    portfolio_withdrawals: list[float] = []
    rrif_withdrawals: list[float] = []
    tfsa_withdrawals: list[float] = []
    taxable_non_rrif_withdrawals: list[float] = []
    gross_income_targets: list[float] = []
    government_benefits: list[float] = []
    net_retirement_incomes: list[float] = []
    income_taxes: list[float] = []
    capital_gains_taxes: list[float] = []
    oas_clawbacks: list[float] = []
    total_taxes: list[float] = []
    average_tax_rates: list[float] = []
    marginal_tax_rates: list[float] = []
    post_tax_income_targets: list[float] = []
    depleted_age: int | None = None
    previous_taxable_income: float | None = None

    retirement_years = inputs.life_expectancy - retirement_start_age + 1
    inflation_to_retirement = (1 + inflation) ** years_to_retirement

    def split_evenly(remaining: float, first_balance: float, second_balance: float) -> tuple[float, float]:
        target_each = remaining / 2.0
        first_withdrawal = min(first_balance, target_each)
        second_withdrawal = min(second_balance, target_each)
        leftover = remaining - first_withdrawal - second_withdrawal

        if leftover > 0:
            first_extra = min(first_balance - first_withdrawal, leftover)
            first_withdrawal += first_extra
            leftover -= first_extra

        if leftover > 0:
            second_extra = min(second_balance - second_withdrawal, leftover)
            second_withdrawal += second_extra

        return first_withdrawal, second_withdrawal

    for offset in range(retirement_years):
        age = retirement_start_age + offset
        annual_index_factor = inflation_to_retirement * ((1 + inflation) ** offset)
        post_tax_income_target = inputs.annual_income_post_tax_today * annual_index_factor
        gross_income_target = 0.0
        oas_income = inputs.annual_oas_income * annual_index_factor if age >= inputs.oas_start_age else 0.0
        cpp_income = inputs.annual_cpp_income * annual_index_factor if age >= inputs.cpp_start_age else 0.0
        pension_income = inputs.annual_pension_income * annual_index_factor if age >= inputs.pension_start_age else 0.0
        planned_government_income = oas_income + cpp_income + pension_income

        rrif_balance = rrif_balance * (1 + arr)
        tfsa_balance = tfsa_balance * (1 + arr)
        taxable_non_rrif_balance = taxable_non_rrif_balance * (1 + arr)
        appreciating_assets_balance = appreciating_assets_balance * (1 + inflation)

        non_rrif_balance = tfsa_balance + taxable_non_rrif_balance

        available_portfolio = max(0.0, rrif_balance + non_rrif_balance)
        min_rrif_withdrawal = (
            min(rrif_balance, rrif_balance * rrif_min_withdrawal_rate(age))
            if inputs.apply_minimum_rrif_withdrawals
            else 0.0
        )

        if available_portfolio <= 0:
            government_income_gross = planned_government_income
            withdrawal_needed = 0.0
            rrif_withdrawal = 0.0
            tfsa_withdrawal = 0.0
            taxable_non_rrif_withdrawal = 0.0
            ordinary_taxable_income = government_income_gross
            income_tax_before_credit = progressive_tax(ordinary_taxable_income, offset)
            income_tax = max(0.0, income_tax_before_credit - pension_income_tax_credit(age, pension_income, rrif_withdrawal))
            capital_gains_tax = 0.0
            oas_clawback = oas_clawback_amount(ordinary_taxable_income, oas_income, offset)
            total_tax = income_tax + oas_clawback
            government_income = max(0.0, government_income_gross - oas_clawback)
            net_retirement_income = government_income_gross - total_tax
            gross_income_target = post_tax_income_target + total_tax
            taxable_income_total = ordinary_taxable_income
        else:
            government_income_gross = planned_government_income

            def evaluate_withdrawal(total_withdrawal: float) -> tuple[float, float, float, float, float, float, float, float, float]:
                requested_total_withdrawal = max(min_rrif_withdrawal, total_withdrawal)
                rrif_withdrawal = min_rrif_withdrawal
                tfsa_withdrawal = 0.0
                taxable_non_rrif_withdrawal = 0.0
                remaining_rrif_capacity = max(0.0, rrif_balance - rrif_withdrawal)
                remaining_withdrawal = max(0.0, requested_total_withdrawal - rrif_withdrawal)

                if strategy == "non_registered_first":
                    taxable_non_rrif_withdrawal = min(remaining_withdrawal, taxable_non_rrif_balance)
                    remaining = max(0.0, remaining_withdrawal - taxable_non_rrif_withdrawal)
                    tfsa_withdrawal = min(remaining, tfsa_balance)
                    remaining_after_tfsa = max(0.0, remaining - tfsa_withdrawal)
                    additional_rrif = min(remaining_after_tfsa, remaining_rrif_capacity)
                    rrif_withdrawal += additional_rrif
                elif strategy in {"bracket_fill", "tax_smoothing"}:
                    base_target_taxable = 52886.0 * ((1 + inflation) ** offset)
                    if strategy == "tax_smoothing" and previous_taxable_income is not None:
                        target_taxable = max(base_target_taxable * 0.85, previous_taxable_income * (1 + inflation))
                    else:
                        target_taxable = base_target_taxable
                    target_rrif = max(0.0, target_taxable - government_income_gross)
                    target_additional_rrif = max(0.0, target_rrif - rrif_withdrawal)
                    additional_rrif = min(remaining_withdrawal, remaining_rrif_capacity, target_additional_rrif)
                    rrif_withdrawal += additional_rrif
                    remaining = max(0.0, remaining_withdrawal - additional_rrif)
                    tfsa_withdrawal, taxable_non_rrif_withdrawal = split_evenly(remaining, tfsa_balance, taxable_non_rrif_balance)
                else:
                    additional_rrif = min(remaining_withdrawal, remaining_rrif_capacity)
                    rrif_withdrawal += additional_rrif
                    remaining = max(0.0, remaining_withdrawal - additional_rrif)
                    taxable_non_rrif_withdrawal = min(remaining, taxable_non_rrif_balance)
                    remaining_after_non_registered = max(0.0, remaining - taxable_non_rrif_withdrawal)
                    tfsa_withdrawal = min(remaining_after_non_registered, tfsa_balance)

                total_withdrawal_effective = rrif_withdrawal + tfsa_withdrawal + taxable_non_rrif_withdrawal

                ordinary_taxable_income = government_income_gross + rrif_withdrawal
                taxable_capital_gains = taxable_non_rrif_withdrawal * taxable_non_registered_withdrawal_share * capital_gains_inclusion
                tax_on_ordinary = progressive_tax(ordinary_taxable_income, offset)
                tax_on_total = progressive_tax(ordinary_taxable_income + taxable_capital_gains, offset)
                pension_credit_value = pension_income_tax_credit(age, pension_income, rrif_withdrawal)
                tax_on_ordinary_after_credit = max(0.0, tax_on_ordinary - pension_credit_value)
                tax_on_total_after_credit = max(0.0, tax_on_total - pension_credit_value)
                income_tax_value = tax_on_ordinary_after_credit
                capital_gains_tax_value = max(0.0, tax_on_total_after_credit - tax_on_ordinary_after_credit)
                taxable_income_total_value = ordinary_taxable_income + taxable_capital_gains
                oas_clawback_value = oas_clawback_amount(taxable_income_total_value, oas_income, offset)
                total_tax_value = income_tax_value + capital_gains_tax_value + oas_clawback_value
                net_government_income = max(0.0, government_income_gross - oas_clawback_value)
                net_income_value = net_government_income + total_withdrawal_effective - income_tax_value - capital_gains_tax_value
                return (
                    net_income_value,
                    income_tax_value,
                    capital_gains_tax_value,
                    oas_clawback_value,
                    total_tax_value,
                    rrif_withdrawal,
                    tfsa_withdrawal,
                    taxable_non_rrif_withdrawal,
                    taxable_income_total_value,
                )

            max_withdrawal_metrics = evaluate_withdrawal(available_portfolio)

            if max_withdrawal_metrics[0] >= post_tax_income_target:
                low = 0.0
                high = available_portfolio
                for _ in range(50):
                    mid = (low + high) / 2
                    mid_metrics = evaluate_withdrawal(mid)
                    if mid_metrics[0] >= post_tax_income_target:
                        high = mid
                    else:
                        low = mid
                withdrawal_needed = max(min_rrif_withdrawal, high)
                (
                    net_retirement_income,
                    income_tax,
                    capital_gains_tax,
                    oas_clawback,
                    total_tax,
                    rrif_withdrawal,
                    tfsa_withdrawal,
                    taxable_non_rrif_withdrawal,
                    taxable_income_total,
                ) = evaluate_withdrawal(withdrawal_needed)
            else:
                withdrawal_needed = available_portfolio
                (
                    net_retirement_income,
                    income_tax,
                    capital_gains_tax,
                    oas_clawback,
                    total_tax,
                    rrif_withdrawal,
                    tfsa_withdrawal,
                    taxable_non_rrif_withdrawal,
                    taxable_income_total,
                ) = max_withdrawal_metrics

            government_income = max(0.0, government_income_gross - oas_clawback)
            gross_income_target = post_tax_income_target + total_tax

        non_rrif_withdrawal = tfsa_withdrawal + taxable_non_rrif_withdrawal
        rrif_balance = max(0.0, rrif_balance - rrif_withdrawal)
        tfsa_balance = max(0.0, tfsa_balance - tfsa_withdrawal)
        taxable_non_rrif_balance = max(0.0, taxable_non_rrif_balance - taxable_non_rrif_withdrawal)
        non_rrif_balance = tfsa_balance + taxable_non_rrif_balance

        liquid_total_balance = rrif_balance + non_rrif_balance
        total_balance = liquid_total_balance + appreciating_assets_balance

        if liquid_total_balance <= 0 and depleted_age is None:
            depleted_age = age
            rrif_balance = 0.0
            tfsa_balance = 0.0
            taxable_non_rrif_balance = 0.0
            non_rrif_balance = 0.0
            liquid_total_balance = 0.0
            total_balance = appreciating_assets_balance

        years.append(age)
        total_balances.append(total_balance)
        rrif_balances.append(rrif_balance)
        non_rrif_balances.append(non_rrif_balance)
        tfsa_balances.append(tfsa_balance)
        taxable_non_rrif_balances.append(taxable_non_rrif_balance)
        appreciating_assets.append(appreciating_assets_balance)
        portfolio_withdrawals.append(withdrawal_needed)
        rrif_withdrawals.append(rrif_withdrawal)
        tfsa_withdrawals.append(tfsa_withdrawal)
        taxable_non_rrif_withdrawals.append(taxable_non_rrif_withdrawal)
        gross_income_targets.append(gross_income_target)
        government_benefits.append(government_income)
        net_retirement_incomes.append(net_retirement_income)
        income_taxes.append(income_tax)
        capital_gains_taxes.append(capital_gains_tax)
        oas_clawbacks.append(oas_clawback)
        total_taxes.append(total_tax)
        gross_income_for_rate = max(0.0, planned_government_income + withdrawal_needed)
        average_tax_rates.append((total_tax / gross_income_for_rate) * 100 if gross_income_for_rate > 0 else 0.0)
        marginal_tax_rates.append(marginal_tax_rate(taxable_income_total, offset) * 100)
        post_tax_income_targets.append(post_tax_income_target)
        previous_taxable_income = taxable_income_total

    return RetirementProjection(
        years=years,
        total_balances=total_balances,
        rrif_balances=rrif_balances,
        non_rrif_balances=non_rrif_balances,
        tfsa_balances=tfsa_balances,
        taxable_non_rrif_balances=taxable_non_rrif_balances,
        appreciating_assets=appreciating_assets,
        portfolio_withdrawals=portfolio_withdrawals,
        rrif_withdrawals=rrif_withdrawals,
        tfsa_withdrawals=tfsa_withdrawals,
        taxable_non_rrif_withdrawals=taxable_non_rrif_withdrawals,
        gross_income_targets=gross_income_targets,
        government_benefits=government_benefits,
        net_retirement_incomes=net_retirement_incomes,
        income_taxes=income_taxes,
        capital_gains_taxes=capital_gains_taxes,
        oas_clawbacks=oas_clawbacks,
        total_taxes=total_taxes,
        average_tax_rates=average_tax_rates,
        marginal_tax_rates=marginal_tax_rates,
        post_tax_income_targets=post_tax_income_targets,
        depleted_age=depleted_age,
        years_to_retirement=years_to_retirement,
        retirement_start_age=retirement_start_age,
        balance_at_retirement=balance_at_retirement,
    )


def plot_projection(projection: RetirementProjection, output_path: Path) -> None:
    import plotly.graph_objects as go

    primary_max = max(
        1.0,
        *projection.total_balances,
        *projection.rrif_balances,
        *projection.non_rrif_balances,
        *projection.appreciating_assets,
    )
    secondary_max = max(
        1.0,
        *projection.portfolio_withdrawals,
        *projection.government_benefits,
        *projection.net_retirement_incomes,
        *projection.income_taxes,
        *projection.capital_gains_taxes,
        *projection.oas_clawbacks,
        *projection.total_taxes,
    )
    primary_max_with_headroom = primary_max * 1.10
    secondary_max_with_headroom = secondary_max * 1.10

    fig = go.Figure()
    fig.add_trace(
        go.Scatter(
            x=projection.years,
            y=projection.total_balances,
            mode="lines",
            name="Total Portfolio Balance",
            line={"color": "#2563eb", "width": 3},
            yaxis="y1",
        )
    )
    fig.add_trace(
        go.Scatter(
            x=projection.years,
            y=projection.rrif_balances,
            mode="lines",
            name="RRIF Balance",
            line={"color": "#0ea5e9", "width": 2},
            yaxis="y1",
        )
    )
    fig.add_trace(
        go.Scatter(
            x=projection.years,
            y=projection.non_rrif_balances,
            mode="lines",
            name="Non-RRIF Balance",
            line={"color": "#16a34a", "width": 2},
            yaxis="y1",
        )
    )
    fig.add_trace(
        go.Scatter(
            x=projection.years,
            y=projection.appreciating_assets,
            mode="lines",
            name="Appreciating Assets",
            line={"color": "#7c3aed", "width": 2, "dash": "dot"},
            yaxis="y1",
        )
    )
    fig.add_trace(
        go.Scatter(
            x=projection.years,
            y=projection.portfolio_withdrawals,
            mode="lines",
            name="Portfolio Withdrawal (Gross)",
            line={"color": "#dc2626", "width": 3},
            yaxis="y2",
        )
    )
    fig.add_trace(
        go.Scatter(
            x=projection.years,
            y=projection.government_benefits,
            mode="lines",
            name="OAS + CPP (Gross)",
            line={"color": "#7c3aed", "width": 2, "dash": "dot"},
            yaxis="y2",
        )
    )
    fig.add_trace(
        go.Scatter(
            x=projection.years,
            y=projection.net_retirement_incomes,
            mode="lines",
            name="Net Retirement Income (Withdrawals + OAS/CPP)",
            line={"color": "#ea580c", "width": 3, "dash": "dash"},
            yaxis="y2",
        )
    )
    fig.add_trace(
        go.Scatter(
            x=projection.years,
            y=projection.income_taxes,
            mode="lines",
            name="Income Taxes",
            line={"color": "#a16207", "width": 2},
            yaxis="y2",
        )
    )
    fig.add_trace(
        go.Scatter(
            x=projection.years,
            y=projection.capital_gains_taxes,
            mode="lines",
            name="Capital Gains Taxes",
            line={"color": "#be185d", "width": 2, "dash": "dot"},
            yaxis="y2",
        )
    )
    fig.add_trace(
        go.Scatter(
            x=projection.years,
            y=projection.oas_clawbacks,
            mode="lines",
            name="OAS Recovery Tax",
            line={"color": "#7c2d12", "width": 2, "dash": "dashdot"},
            yaxis="y2",
        )
    )
    fig.add_trace(
        go.Scatter(
            x=projection.years,
            y=projection.total_taxes,
            mode="lines",
            name="Total Taxes Paid",
            line={"color": "#111827", "width": 3},
            yaxis="y2",
        )
    )

    if projection.depleted_age is not None:
        fig.add_vline(x=projection.depleted_age, line_dash="dash", line_color="#b91c1c")

    fig.update_layout(
        title="Retirement Drawdown with RRIF, OAS, and CPP",
        margin={"l": 70, "r": 70, "t": 50, "b": 120},
        xaxis_title="Age",
        yaxis={"title": "Portfolio Balance (CAD)", "tickprefix": "$", "separatethousands": True, "range": [0, primary_max_with_headroom]},
        yaxis2={
            "title": "Income / Withdrawals (CAD)",
            "tickprefix": "$",
            "separatethousands": True,
            "overlaying": "y",
            "side": "right",
            "range": [0, secondary_max_with_headroom],
        },
        legend={"orientation": "h", "x": 0.5, "xanchor": "center", "y": -0.2, "yanchor": "top"},
        template="plotly_white",
    )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.write_html(str(output_path), include_plotlyjs="cdn")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Retirement drawdown model for Ontario planning scenarios.")
    parser.add_argument("--current-age", type=int, required=True, help="Current age")
    parser.add_argument("--retirement-age", type=int, required=True, help="Expected retirement age")
    parser.add_argument("--life-expectancy", type=int, default=95, help="Assumed age through which planning runs")
    parser.add_argument("--current-rrif", type=float, required=True, help="Current RRIF account balance (CAD)")
    parser.add_argument("--current-rrsp", type=float, default=0.0, help="Current RRSP account balance (CAD), converted to RRIF at retirement")
    parser.add_argument("--current-non-rrif", type=float, required=True, help="Current non-RRIF account balance (CAD)")
    parser.add_argument("--current-appreciating-assets", type=float, default=0.0, help="Current appreciating assets value (CAD), indexed by inflation")
    parser.add_argument("--annual-income-post-tax", type=float, required=True, help="Desired annual retirement income in post-tax dollars (CAD)")
    parser.add_argument("--arr", type=float, required=True, help="Annual rate of return percentage")
    parser.add_argument("--inflation", type=float, required=True, help="Annual inflation percentage")
    parser.add_argument("--oas", type=float, default=0.0, help="Annual OAS benefit amount (gross CAD)")
    parser.add_argument("--cpp", type=float, default=0.0, help="Annual CPP benefit amount (gross CAD)")
    parser.add_argument("--pension", type=float, default=0.0, help="Annual pension benefit amount (gross CAD)")
    parser.add_argument("--oas-start-age", type=int, default=65, help="Age when OAS starts")
    parser.add_argument("--cpp-start-age", type=int, default=65, help="Age when CPP starts")
    parser.add_argument("--pension-start-age", type=int, default=65, help="Age when pension starts")
    parser.add_argument("--annual-rrsp-contribution", type=float, default=0.0, help="Annual RRSP contribution during pre-retirement years (CAD)")
    parser.add_argument("--annual-tfsa-contribution", type=float, default=0.0, help="Annual TFSA contribution during pre-retirement years (CAD)")
    parser.add_argument("--annual-non-registered-contribution", type=float, default=0.0, help="Annual non-registered contribution during pre-retirement years (CAD)")
    parser.add_argument(
        "--taxable-non-registered-withdrawal-percent",
        type=float,
        default=100.0,
        help="Percent of non-registered withdrawals treated as taxable gains before inclusion rate",
    )
    parser.add_argument(
        "--disable-oas-clawback",
        action="store_true",
        help="Disable OAS clawback recovery tax assumption",
    )
    parser.add_argument(
        "--disable-minimum-rrif-withdrawals",
        action="store_true",
        help="Disable mandatory minimum RRIF withdrawal assumption",
    )
    parser.add_argument(
        "--apply-pension-income-tax-credit",
        action="store_true",
        help="Apply an approximate pension income tax credit assumption to annual taxes",
    )
    parser.add_argument("--output", type=Path, default=Path("outputs/retirement_projection.html"), help="Output HTML path")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    inputs = RetirementInputs(
        current_age=args.current_age,
        retirement_age=args.retirement_age,
        life_expectancy=args.life_expectancy,
        current_rrif_balance=args.current_rrif,
        current_rrsp_balance=args.current_rrsp,
        current_non_rrif_balance=args.current_non_rrif,
        current_tfsa_balance=0.0,
        current_appreciating_assets=args.current_appreciating_assets,
        annual_income_post_tax_today=args.annual_income_post_tax,
        annual_rate_of_return=args.arr,
        inflation_rate=args.inflation,
        annual_oas_income=args.oas,
        annual_cpp_income=args.cpp,
        annual_pension_income=args.pension,
        oas_start_age=args.oas_start_age,
        cpp_start_age=args.cpp_start_age,
        pension_start_age=args.pension_start_age,
        annual_rrsp_contribution=args.annual_rrsp_contribution,
        annual_tfsa_contribution=args.annual_tfsa_contribution,
        annual_non_registered_contribution=args.annual_non_registered_contribution,
        taxable_non_registered_withdrawal_percent=args.taxable_non_registered_withdrawal_percent,
        apply_oas_clawback=not args.disable_oas_clawback,
        apply_minimum_rrif_withdrawals=not args.disable_minimum_rrif_withdrawals,
        apply_pension_income_tax_credit=args.apply_pension_income_tax_credit,
    )

    projection = project_retirement(inputs)
    plot_projection(projection, args.output)

    print(f"Years to retirement: {projection.years_to_retirement}")
    print(f"Projected nest egg at retirement: ${projection.balance_at_retirement:,.2f}")
    if projection.depleted_age is None:
        print("Result: Portfolio lasts through life expectancy assumption.")
    else:
        print(f"Result: Portfolio depletes at age {projection.depleted_age}.")
    print(f"Saved plot: {args.output}")


if __name__ == "__main__":
    main()