from __future__ import annotations

from pathlib import Path

from flask import Flask, jsonify, request, send_file

from retirement_model import (
    STRATEGY_LABELS,
    COMBINED_ON_2025_TAX_BRACKETS,
    DEFAULT_CAPITAL_GAINS_INCLUSION_RATE,
    RetirementInputs,
    available_strategies,
    project_retirement,
    tax_brackets_reference,
)


app = Flask(__name__)


def _to_float(value: object) -> float:
    return float(value or 0)


def _to_int(value: object) -> int:
    return int(float(value or 0))


def _to_bool(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)


def _parse_payload(payload: dict) -> tuple[RetirementInputs, dict[str, float | int | bool]]:
    current_age = _to_int(payload.get("currentAge"))
    retirement_age = _to_int(payload.get("retirementAge"))
    annual_income_post_tax = _to_float(payload.get("targetRetirementIncome"))
    arr = _to_float(payload.get("arr"))
    inflation = _to_float(payload.get("inflation"))
    annual_rrsp_contribution = _to_float(payload.get("annualRRSPContribution") or 0.0)
    annual_tfsa_contribution = _to_float(payload.get("annualTFSAContribution") or 0.0)
    annual_non_registered_contribution = _to_float(payload.get("annualNonRegisteredContribution") or 0.0)
    taxable_share_raw = payload.get("taxableNonRegisteredWithdrawalPercent")
    taxable_non_registered_withdrawal_percent = _to_float(100.0 if taxable_share_raw in (None, "") else taxable_share_raw)
    oas_clawback_raw = payload.get("applyOASClawback")
    apply_oas_clawback = _to_bool(True if oas_clawback_raw in (None, "") else oas_clawback_raw)
    minimum_rrif_raw = payload.get("applyMinimumRRIFWithdrawals")
    apply_minimum_rrif_withdrawals = _to_bool(True if minimum_rrif_raw in (None, "") else minimum_rrif_raw)
    apply_pension_income_tax_credit = _to_bool(payload.get("applyPensionIncomeTaxCredit"))
    annual_oas_income = _to_float(payload.get("annualOAS"))
    annual_cpp_income = _to_float(payload.get("annualCPP"))
    annual_pension_income = _to_float(payload.get("annualPension"))
    oas_start_age = _to_int(payload.get("oasStartAge") or 65)
    cpp_start_age = _to_int(payload.get("cppStartAge") or 65)
    pension_start_age = _to_int(payload.get("pensionStartAge") or 65)
    life_expectancy = _to_int(payload.get("lifeExpectancy") or 95)

    current_rrif_balance = _to_float(payload.get("rrif"))
    current_rrsp_balance = _to_float(payload.get("rrsp"))
    current_appreciating_assets = _to_float(payload.get("appreciatingAssets"))
    current_non_rrif_balance = (
        _to_float(payload.get("tfsa"))
        + _to_float(payload.get("fhsa"))
        + _to_float(payload.get("resp"))
        + _to_float(payload.get("individualTaxable"))
        + _to_float(payload.get("jointTaxable"))
        + _to_float(payload.get("corporateInvestment"))
    )

    if current_age <= 0 or annual_income_post_tax <= 0:
        raise ValueError("Current age and desired annual income must be positive.")

    inputs = RetirementInputs(
        current_age=current_age,
        retirement_age=retirement_age,
        life_expectancy=life_expectancy,
        current_rrif_balance=current_rrif_balance,
        current_rrsp_balance=current_rrsp_balance,
        current_non_rrif_balance=current_non_rrif_balance,
        current_tfsa_balance=_to_float(payload.get("tfsa")),
        current_appreciating_assets=current_appreciating_assets,
        annual_income_post_tax_today=annual_income_post_tax,
        annual_rate_of_return=arr,
        inflation_rate=inflation,
        annual_oas_income=annual_oas_income,
        annual_cpp_income=annual_cpp_income,
        annual_pension_income=annual_pension_income,
        oas_start_age=oas_start_age,
        cpp_start_age=cpp_start_age,
        pension_start_age=pension_start_age,
        annual_rrsp_contribution=annual_rrsp_contribution,
        annual_tfsa_contribution=annual_tfsa_contribution,
        annual_non_registered_contribution=annual_non_registered_contribution,
        taxable_non_registered_withdrawal_percent=taxable_non_registered_withdrawal_percent,
        apply_oas_clawback=apply_oas_clawback,
        apply_minimum_rrif_withdrawals=apply_minimum_rrif_withdrawals,
        apply_pension_income_tax_credit=apply_pension_income_tax_credit,
    )

    metadata: dict[str, float | int | bool] = {
        "currentAge": current_age,
        "retirementAge": retirement_age,
        "lifeExpectancy": life_expectancy,
        "currentRRIF": current_rrif_balance,
        "currentRRSP": current_rrsp_balance,
        "currentNonRRIF": current_non_rrif_balance,
        "currentAppreciatingAssets": current_appreciating_assets,
        "annualIncomePostTax": annual_income_post_tax,
        "arr": arr,
        "inflation": inflation,
        "annualOAS": annual_oas_income,
        "annualCPP": annual_cpp_income,
        "annualPension": annual_pension_income,
        "oasStartAge": oas_start_age,
        "cppStartAge": cpp_start_age,
        "pensionStartAge": pension_start_age,
        "annualRRSPContribution": annual_rrsp_contribution,
        "annualTFSAContribution": annual_tfsa_contribution,
        "annualNonRegisteredContribution": annual_non_registered_contribution,
        "taxableNonRegisteredWithdrawalPercent": taxable_non_registered_withdrawal_percent,
        "applyOASClawback": apply_oas_clawback,
        "applyMinimumRRIFWithdrawals": apply_minimum_rrif_withdrawals,
        "applyPensionIncomeTaxCredit": apply_pension_income_tax_credit,
    }
    return inputs, metadata


@app.get("/")
def home():
    return send_file(Path(__file__).with_name("financial_planner.html"))


@app.post("/api/analyze")
def analyze():
    payload = request.get_json(silent=True) or {}

    try:
        inputs, metadata = _parse_payload(payload)
        selected_strategy = str(payload.get("withdrawalStrategy") or "rrif_first")
        nest_egg = float(metadata["currentRRIF"]) + float(metadata["currentRRSP"]) + float(metadata["currentNonRRIF"])

        projection = project_retirement(inputs, strategy=selected_strategy)

        def progressive_tax_for_year(taxable_income: float, years_from_retirement_start: int) -> float:
            income = max(0.0, taxable_income)
            inflation_factor = (1 + (inputs.inflation_rate / 100.0)) ** max(0, years_from_retirement_start)
            tax_value = 0.0
            lower = 0.0
            for upper, rate in COMBINED_ON_2025_TAX_BRACKETS:
                indexed_upper = float("inf") if upper == float("inf") else upper * inflation_factor
                if income <= lower:
                    break
                taxable_at_rate = min(income, indexed_upper) - lower
                tax_value += taxable_at_rate * rate
                lower = indexed_upper
            return tax_value

        def estimate_estate_taxes(candidate) -> tuple[float, float]:
            if not candidate.total_balances:
                return 0.0, 0.0

            ending_rrif = candidate.rrif_balances[-1] if candidate.rrif_balances else 0.0
            ending_tfsa = candidate.tfsa_balances[-1] if candidate.tfsa_balances else 0.0
            ending_taxable_non_registered = candidate.taxable_non_rrif_balances[-1] if candidate.taxable_non_rrif_balances else 0.0
            ending_appreciating_assets = candidate.appreciating_assets[-1] if candidate.appreciating_assets else 0.0

            taxable_non_registered_share = min(1.0, max(0.0, inputs.taxable_non_registered_withdrawal_percent / 100.0))
            taxable_capital_gains = ending_taxable_non_registered * taxable_non_registered_share * DEFAULT_CAPITAL_GAINS_INCLUSION_RATE
            taxable_capital_gains += ending_appreciating_assets * DEFAULT_CAPITAL_GAINS_INCLUSION_RATE

            final_offset = max(0, len(candidate.years) - 1)
            tax_on_total = progressive_tax_for_year(ending_rrif + taxable_capital_gains, final_offset)
            estate_taxes = max(0.0, tax_on_total)
            ending_balance = ending_rrif + ending_tfsa + ending_taxable_non_registered + ending_appreciating_assets
            ending_balance_after_estate_taxes = max(0.0, ending_balance - estate_taxes)
            return estate_taxes, ending_balance_after_estate_taxes

        def max_or_zero(values: list[float]) -> float:
            return max(values) if values else 0.0

        strategy_comparison = []
        chart_range_max = {
            "portfolio": 0.0,
            "income": 0.0,
            "taxAmount": 0.0,
            "taxRate": 0.0,
        }
        for strategy_id, strategy_label in STRATEGY_LABELS.items():
            candidate = project_retirement(inputs, strategy=strategy_id)
            estate_taxes, ending_balance_after_estate_taxes = estimate_estate_taxes(candidate)
            strategy_comparison.append(
                {
                    "id": strategy_id,
                    "label": strategy_label,
                    "lifetimeTaxes": sum(candidate.total_taxes),
                    "depletedAge": candidate.depleted_age,
                    "endingBalance": candidate.total_balances[-1] if candidate.total_balances else 0.0,
                    "estateTaxes": estate_taxes,
                    "endingBalanceAfterEstateTaxes": ending_balance_after_estate_taxes,
                }
            )

            chart_range_max["portfolio"] = max(
                chart_range_max["portfolio"],
                max_or_zero(candidate.total_balances),
                max_or_zero(candidate.rrif_balances),
                max_or_zero(candidate.tfsa_balances),
                max_or_zero(candidate.taxable_non_rrif_balances),
                max_or_zero(candidate.appreciating_assets),
            )
            chart_range_max["income"] = max(
                chart_range_max["income"],
                max_or_zero(candidate.rrif_withdrawals),
                max_or_zero(candidate.tfsa_withdrawals),
                max_or_zero(candidate.taxable_non_rrif_withdrawals),
                max_or_zero(candidate.government_benefits),
                max_or_zero(candidate.net_retirement_incomes),
            )
            chart_range_max["taxAmount"] = max(
                chart_range_max["taxAmount"],
                max_or_zero(candidate.income_taxes),
                max_or_zero(candidate.capital_gains_taxes),
                max_or_zero(candidate.oas_clawbacks),
                max_or_zero(candidate.total_taxes),
            )
            chart_range_max["taxRate"] = max(
                chart_range_max["taxRate"],
                max_or_zero(candidate.average_tax_rates),
                max_or_zero(candidate.marginal_tax_rates),
            )

        strategy_comparison.sort(
            key=lambda item: (-item["endingBalanceAfterEstateTaxes"], item["lifetimeTaxes"])
        )

        return jsonify(
            {
                "selectedStrategy": selected_strategy,
                "selectedStrategyLabel": STRATEGY_LABELS.get(selected_strategy, selected_strategy),
                "strategyOptions": available_strategies(),
                "strategyComparison": strategy_comparison,
                "chartRanges": {
                    "portfolioMax": max(1.0, chart_range_max["portfolio"]) * 1.10,
                    "incomeMax": max(1.0, chart_range_max["income"]) * 1.10,
                    "taxAmountMax": max(1.0, chart_range_max["taxAmount"]) * 1.10,
                    "taxRateMax": max(1.0, chart_range_max["taxRate"]) * 1.15,
                },
                "yearsToRetirement": projection.years_to_retirement,
                "retirementStartAge": projection.retirement_start_age,
                "balanceAtRetirement": projection.balance_at_retirement,
                "depletedAge": projection.depleted_age,
                "lifeExpectancy": int(metadata["lifeExpectancy"]),
                "nestEgg": nest_egg,
                "rrifAtStart": float(metadata["currentRRIF"]),
                "nonRrifAtStart": float(metadata["currentNonRRIF"]),
                "years": projection.years,
                "totalBalances": projection.total_balances,
                "rrifBalances": projection.rrif_balances,
                "nonRrifBalances": projection.non_rrif_balances,
                "tfsaRetirementBalances": projection.tfsa_balances,
                "taxableNonRegisteredRetirementBalances": projection.taxable_non_rrif_balances,
                "appreciatingAssets": projection.appreciating_assets,
                "portfolioWithdrawals": projection.portfolio_withdrawals,
                "rrifWithdrawals": projection.rrif_withdrawals,
                "tfsaWithdrawals": projection.tfsa_withdrawals,
                "taxableNonRegisteredWithdrawals": projection.taxable_non_rrif_withdrawals,
                "grossIncomeTargets": projection.gross_income_targets,
                "governmentBenefits": projection.government_benefits,
                "netRetirementIncomes": projection.net_retirement_incomes,
                "incomeTaxes": projection.income_taxes,
                "capitalGainsTaxes": projection.capital_gains_taxes,
                "oasClawbacks": projection.oas_clawbacks,
                "totalTaxes": projection.total_taxes,
                "averageTaxRates": projection.average_tax_rates,
                "marginalTaxRates": projection.marginal_tax_rates,
                "postTaxIncomeTargets": projection.post_tax_income_targets,
                "taxBrackets": tax_brackets_reference(),
            }
        )
    except ValueError as error:
        return jsonify({"error": str(error)}), 400


if __name__ == "__main__":
    app.run(debug=True)