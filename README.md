# Ontario Retirement Planner

Web-based Ontario retirement planning tool with multi-strategy withdrawal analysis, tax projections, OAS clawback modeling, RRIF minimum withdrawal rules, and estate-oriented comparison metrics.

## Project Structure

- [app.py](app.py): Flask app and API endpoints
- [retirement_model.py](retirement_model.py): Core retirement/tax/strategy engine
- [financial_planner.html](financial_planner.html): Single-page UI (inputs, summary table, and plots)
- [requirements.txt](requirements.txt): Python dependencies
- [main.py](main.py): simple test script

## Quick Start (Windows / PowerShell)

1. Create and activate venv (if needed)
	- `python -m venv .venv`
	- `.\.venv\Scripts\Activate.ps1`
2. Install dependencies
	- `pip install -r requirements.txt`
3. Run Flask app
	- `python app.py`
4. Open
	- `http://127.0.0.1:5000/`

## What the App Does

- Projects retirement balances from current age to death age
- Models drawdown and taxes across multiple withdrawal strategies
- Produces three synchronized charts:
  - Investment portfolio curves
  - Income curves
  - Tax curves
	- Optional stress-test confidence bands (P10/P50/P90 overlays)
- Compares strategies in an interactive summary table with sortable columns
- Lets users switch active strategy by clicking a row in the summary table (plots refresh automatically)

## Inputs (High Level)

- Portfolio balances (Current Year, Current Age, RRSP/RRIF, TFSA, Non-Registered, Appreciating Assets)
- Retirement goals (retirement age, target post-tax income, death age)
- Pension/government income (OAS/CPP/pension + start ages)
- Assumptions (ARR, inflation, taxable share of non-registered withdrawals, tax assumptions toggles)
- Stress testing (ARR min/max/step and inflation min/max/step)

## Actions and Stress Workflow

- Main actions are shown above the Stress Testing section:
	- `Calculate & Plot`
	- `Download CSV`
	- `Save Inputs JSON`
	- `Load Inputs JSON`
- Stress Testing section includes:
	- `Run Stress Test`
	- `Clear Stress Results`
- Running stress test executes a grid of ARR/inflation scenarios and overlays confidence bands on all charts:
	- P10 lower bound (dashed)
	- P50 median (dotted)
	- P90 upper bound (dashed)
	- shaded P10-P90 region
- Clearing stress results removes overlays and redraws base charts using the latest non-stress analysis.

## Current Strategy Options

- `RRIF then Non-Reg then TFSA`
- `Non-Reg then TFSA then RRIF`
- `Bracket-fill`
- `Tax-smoothing`

Strategy selection is done by clicking rows in the summary table.

## Summary Table Metrics

Each strategy row includes:

- Retirement Funding (Withdrawal) Strategy
- Net CPP Income
- Net OAS Income
- Pension Income
- Lifetime Taxes
- Ending Balance
- Estate Taxes
- Ending Balance After Estate Taxes
- Depleted Age

## Tax / Rule Assumptions in Model

- Combined Ontario progressive bracket schedule (2025 base, inflation-indexed in model)
- OAS clawback modeled as a separate assumption (on/off)
- Minimum RRIF withdrawals modeled as a separate assumption (on/off)
- Pension income tax credit modeled as an assumption (on/off, simplified approximation)
- Non-registered withdrawal taxation controlled by user-defined taxable-share percentage

Default table ordering is by **maximum ending balance after estate taxes** (descending), and users can click any column header to sort ascending/descending.

## Notes / Modeling Scope

- This tool is a planning model, not tax or legal advice.
- Estate tax treatment is approximated for scenario comparison.
- Results depend heavily on assumptions (inflation, ARR, income targets, strategy selection).
