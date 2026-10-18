import subprocess
import re
from pathlib import Path
from decimal import Decimal
from typing import Dict, Any, Optional

def parse_decimal(val_str: str) -> float:
    cleaned = val_str.replace(",", "").strip()
    return float(Decimal(cleaned))

from .security import read_decrypted_file

def extract_payslip_text(
    file_source: str | bytes | Path,
    password: Optional[str] = None,
    user_email: Optional[str] = None
) -> str:
    cmd = ["pdftotext", "-layout"]
    if password:
        cmd.extend(["-upw", password])
    cmd.extend(["-", "-"])
    
    if isinstance(file_source, bytes):
        pdf_bytes = file_source
    else:
        pdf_bytes = read_decrypted_file(file_source, user_email)

    res = subprocess.run(cmd, input=pdf_bytes, capture_output=True, check=True)
    return res.stdout.decode("utf-8", errors="replace")

def parse_payslip_text(text: str) -> Dict[str, Any]:
    data = {}
    
    # Process Date
    lines = text.split("\n")
    ref_idx = -1
    for idx, line in enumerate(lines):
        if "Ref." in line and "Employee Name" in line and "Process Date" in line:
            ref_idx = idx
            break
            
    if ref_idx != -1:
        val_line = ""
        for offset in range(1, 4):
            if ref_idx + offset < len(lines):
                test_line = lines[ref_idx + offset].strip()
                if test_line:
                    val_line = lines[ref_idx + offset]
                    break
        if val_line:
            date_match = re.search(r"(\d{2}/\d{2}/\d{4})", val_line)
            if date_match:
                data["process_date"] = date_match.group(1)

    if "process_date" not in data:
        fallback_date = re.search(r"Process\s*Date\D*?(\d{2}/\d{2}/\d{4})", text, re.IGNORECASE)
        if fallback_date:
            data["process_date"] = fallback_date.group(1)
                
    # Tax Code
    tc_match = re.search(r"Tax\s*Code\s*:?\s*(\w+)", text, re.IGNORECASE)
    if tc_match:
        data["tax_code"] = tc_match.group(1)
        
    # Tax Period
    tp_match = re.search(r"Tax\s*Period\s*:?\s*(\d+)", text, re.IGNORECASE)
    if tp_match:
        data["tax_period"] = int(tp_match.group(1))
        
    # Total Gross Pay
    gp_match = re.search(r"Total\s+Gross\s+Pay\s+([\d,.]+)", text, re.IGNORECASE)
    if gp_match:
        data["total_gross_pay"] = parse_decimal(gp_match.group(1))
        
    # Gross for Tax
    gft_match = re.search(r"Gross\s+for\s+Tax\s+([\d,.]+)", text, re.IGNORECASE)
    if gft_match:
        data["gross_for_tax"] = parse_decimal(gft_match.group(1))
        
    # PAYE Tax
    paye_match = re.search(r"PAYE\s+Tax\s+([\d,.]+)", text, re.IGNORECASE)
    if paye_match:
        data["paye_tax"] = parse_decimal(paye_match.group(1))
        
    # National Insurance
    ni_match = re.search(r"National\s+Insurance\s+([\d,.]+)", text, re.IGNORECASE)
    if ni_match:
        data["national_insurance"] = parse_decimal(ni_match.group(1))
        
    # Pension (match employee pension deduction, avoid employer/year-to-date pension)
    pension_match = re.search(r"(?<!(?:Er|Ee)\s)Pension\s+([\d,.]+)", text, re.IGNORECASE)
    if pension_match:
        data["pension"] = parse_decimal(pension_match.group(1))
        
    # Net Pay
    np_match = re.search(r"Net\s+Pay\s+([\d,.]+)", text, re.IGNORECASE)
    if np_match:
        data["calculated_net_pay"] = parse_decimal(np_match.group(1))
        
    # Year to Date values
    tgptd_match = re.search(r"Total\s+Gross\s+Pay\s+TD\s+([\d,.]+)", text, re.IGNORECASE)
    if tgptd_match:
        data["ytd_gross"] = parse_decimal(tgptd_match.group(1))
        
    # Tax paid TD (case-insensitive for 'Tax Paid TD' and 'Tax paid TD')
    tptd_match = re.search(r"Tax\s+[Pp]aid\s+TD\s+([\d,.]+)", text, re.IGNORECASE)
    if tptd_match:
        data["ytd_tax"] = parse_decimal(tptd_match.group(1))
        
    # National Insurance TD
    nitd_match = re.search(r"National\s+Insurance\s+TD\s+([\d,.]+)", text, re.IGNORECASE)
    if nitd_match:
        data["ytd_ni"] = parse_decimal(nitd_match.group(1))

    # Calculate deductions total
    data["deductions_total"] = float(
        Decimal(str(data.get("paye_tax", 0.0))) +
        Decimal(str(data.get("national_insurance", 0.0))) +
        Decimal(str(data.get("pension", 0.0)))
    )

    return data
