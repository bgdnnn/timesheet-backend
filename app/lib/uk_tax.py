from __future__ import annotations
import re
from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP

D = Decimal

def q(x) -> Decimal:
    return (D(str(x))).quantize(D("0.01"), rounding=ROUND_HALF_UP)

@dataclass
class UkTaxConfig:
    tax_code: str | None = None
    # 2024/25-ish rUK (update as needed)
    personal_allowance: Decimal = D("12570")
    pa_taper_start: Decimal = D("100000")
    pa_taper_end:   Decimal = D("125140")

    basic_rate_limit: Decimal   = D("37700")
    higher_rate_limit: Decimal  = D("125140")
    basic_rate: Decimal         = D("0.20")
    higher_rate: Decimal        = D("0.40")
    additional_rate: Decimal    = D("0.45")

    # NI thresholds
    weekly_PT: Decimal   = D("242")
    weekly_UEL: Decimal  = D("967")
    monthly_PT: Decimal  = D("1048")
    monthly_UEL: Decimal = D("4189")
    main_ni_rate: Decimal    = D("0.08")
    above_uel_rate: Decimal  = D("0.02")

    periods = {"weekly": D("52"), "monthly": D("12"), "annual": D("1")}

def annualize(gross: Decimal, period: str, cfg: UkTaxConfig) -> Decimal:
    return (gross * cfg.periods[period]).quantize(D("0.01"))

def deannualize(amount_annual: Decimal, period: str, cfg: UkTaxConfig) -> Decimal:
    return (amount_annual / cfg.periods[period]).quantize(D("0.01"), rounding=ROUND_HALF_UP)

def calc_income_tax_annual(annual_gross: Decimal, cfg: UkTaxConfig) -> Decimal:
    pa = cfg.personal_allowance
    
    if cfg.tax_code:
        if cfg.tax_code.upper() in ["BR", "0T"]:
            pa = D("0")
        else:
            numeric_match = re.match(r"(\d+)", cfg.tax_code)
            if numeric_match:
                pa = D(numeric_match.group(1)) * 10

    if annual_gross > cfg.pa_taper_start:
        reduction = ((annual_gross - cfg.pa_taper_start) / 2).quantize(D("0.01"))
        pa = max(D("0"), pa - reduction)
    
    taxable = max(D("0"), annual_gross - pa)

    basic_band = min(taxable, cfg.basic_rate_limit)
    higher_band = min(max(D("0"), taxable - cfg.basic_rate_limit), max(D("0"), cfg.higher_rate_limit - cfg.basic_rate_limit))
    additional_band = max(D("0"), taxable - cfg.higher_rate_limit)

    tax = basic_band * cfg.basic_rate + higher_band * cfg.higher_rate + additional_band * cfg.additional_rate
    return tax.quantize(D("0.01"), rounding=ROUND_HALF_UP)

def calc_employee_ni_period(period_gross: Decimal, period: str, cfg: UkTaxConfig) -> Decimal:
    if period == "weekly":
        PT, UEL = cfg.weekly_PT, cfg.weekly_UEL
    elif period == "monthly":
        PT, UEL = cfg.monthly_PT, cfg.monthly_UEL
    else:
        PT, UEL = cfg.monthly_PT, cfg.monthly_UEL  # safe fallback

    if period_gross <= PT:
        return D("0.00")

    main_band  = max(D("0"), min(period_gross, UEL) - PT)
    above_band = max(D("0"), period_gross - UEL)

    ni = main_band * cfg.main_ni_rate + above_band * cfg.above_uel_rate
    return ni.quantize(D("0.01"), rounding=ROUND_HALF_UP)

def calc_pay_period(
    gross: Decimal,
    period: str = "weekly",
    region: str = "rUK",
    pension_employee_percent: Decimal = D("0.00"),
    tax_offset: Decimal = D("0.00"),
    ni_offset: Decimal = D("0.00"),
) -> dict:
    cfg = UkTaxConfig()
    pension = (gross * pension_employee_percent).quantize(D("0.01"), rounding=ROUND_HALF_UP)
    taxable_pay = gross - pension

    annual_gross = annualize(taxable_pay, period, cfg)
    annual_tax   = calc_income_tax_annual(annual_gross, cfg)
    tax_period   = deannualize(annual_tax, period, cfg) + tax_offset

    ni = calc_employee_ni_period(taxable_pay, period, cfg) + ni_offset
    
    deductions = tax_period + ni + pension
    net_pay = gross - deductions

    return {
        "total_gross_pay": q(gross),
        "gross_for_tax": q(taxable_pay),
        "paye_tax": q(tax_period),
        "national_insurance": q(ni),
        "pension": q(pension),
        "earnings_for_ni": q(taxable_pay),
        "net_pay": q(net_pay),
        "deductions_total": q(deductions),
        "period": period,
        "region": region,
    }
