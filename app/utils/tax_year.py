from datetime import date, timedelta

def get_tax_year_start(year: int) -> date:
    return date(year, 4, 6)

def get_tax_year_start_date(d: date) -> date:
    year = d.year
    tax_year_start_for_current_year = get_tax_year_start(year)
    if d < tax_year_start_for_current_year:
        return get_tax_year_start(year - 1)
    return tax_year_start_for_current_year

def tax_period_to_date(tax_year: int, tax_period: int) -> date:
    tax_year_start = get_tax_year_start(tax_year)
    return tax_year_start + timedelta(weeks=int(tax_period) - 1)