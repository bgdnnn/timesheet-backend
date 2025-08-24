import re
from decimal import Decimal, InvalidOperation

D = Decimal

def parse_payslip(text: str) -> dict:
    """
    Parses the raw text of a payslip to extract key financial figures.
    """
    # Helper to find a value, can return Decimal or string
    def find_value(pattern, text_block, value_type=Decimal):
        match = re.search(pattern, text_block, re.IGNORECASE)
        if not match:
            return None
        try:
            value_str = match.group(1).replace(',', '')
            if value_type == Decimal:
                return Decimal(value_str)
            return value_str # Return as string for dates, tax codes etc.
        except (IndexError, InvalidOperation):
            return None

    patterns = {
        "process_date": (r"Process Date\s+(\d{2}/\d{2}/\d{4})", str),
        "tax_code": (r"Tax Code:\s*([a-zA-Z0-9]+)", str),
        "total_gross_pay": (r"Total Gross Pay\s+([\d,]+\.\d{2})", Decimal),
        "gross_for_tax": (r"Gross for Tax\s+([\d,]+\.\d{2})", Decimal),
        "paye_tax": (r"PAYE Tax\s+([\d,]+\.\d{2})", Decimal),
        "national_insurance": (r"National Insurance\s+([\d,]+\.\d{2})", Decimal),
        "pension": (r"Pension\s+([\d,]+\.\d{2})", Decimal),
        "tax_period": (r"Tax Period:(\d+)", Decimal),
        "ytd_gross": (r"Total Gross Pay TD\s+([\d,]+\.\d{2})", Decimal),
        "ytd_tax": (r"Tax paid TD\s+([\d,]+\.\d{2})", Decimal),
        "ytd_ni": (r"National Insurance TD\s+([\d,]+\.\d{2})", Decimal),
        "ytd_pension": (r"Pension TD \(Inc AVC\)\s+([\d,]+\.\d{2})", Decimal),
    }

    data = {}
    for key, (pattern, value_type) in patterns.items():
        data[key] = find_value(pattern, text, value_type)

    # --- Manual Calculation for Net Pay ---
    if data.get("total_gross_pay") is not None:
        total_deductions = D('0.00')
        deductions = [data.get("paye_tax"), data.get("national_insurance"), data.get("pension")]
        for deduction in deductions:
            if deduction is not None:
                total_deductions += D(deduction)
        
        data["calculated_net_pay"] = D(data["total_gross_pay"]) - total_deductions
        data["deductions_total"] = total_deductions

    return {k: v for k, v in data.items() if v is not None}
