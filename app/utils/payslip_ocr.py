import subprocess
import re
from pathlib import Path
from decimal import Decimal
from typing import Dict, Any, Optional

def parse_decimal(val_str: str) -> float:
    cleaned = val_str.replace(",", "").strip()
    return float(Decimal(cleaned))

def extract_payslip_text(file_path: str, password: Optional[str] = None) -> str:
    cmd = ["pdftotext", "-layout"]
    if password:
        cmd.extend(["-upw", password])
    cmd.extend([file_path, "-"])
    
    res = subprocess.run(cmd, capture_output=True, text=True, check=True)
    return res.stdout

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
                
    # Tax Code
    tc_match = re.search(r"Tax Code:\s*(\w+)", text)
    if tc_match:
        data["tax_code"] = tc_match.group(1)
        
    # Tax Period
    tp_match = re.search(r"Tax Period:\s*(\d+)", text)
    if tp_match:
        data["tax_period"] = int(tp_match.group(1))
        
    # Total Gross Pay
    gp_match = re.search(r"Total Gross Pay\s+([\d,.]+)", text)
    if gp_match:
        data["total_gross_pay"] = parse_decimal(gp_match.group(1))
        
    # Gross for Tax
    gft_match = re.search(r"Gross for Tax\s+([\d,.]+)", text)
    if gft_match:
        data["gross_for_tax"] = parse_decimal(gft_match.group(1))
        
    # PAYE Tax
    paye_match = re.search(r"PAYE Tax\s+([\d,.]+)", text)
    if paye_match:
        data["paye_tax"] = parse_decimal(paye_match.group(1))
        
    # National Insurance
    ni_match = re.search(r"National Insurance\s+([\d,.]+)", text)
    if ni_match:
        data["national_insurance"] = parse_decimal(ni_match.group(1))
        
    # Pension
    pension_match = re.search(r"Pension\s+([\d,.]+)", text)
    if pension_match:
        data["pension"] = parse_decimal(pension_match.group(1))
        
    # Net Pay
    np_match = re.search(r"Net Pay\s+([\d,.]+)", text)
    if np_match:
        data["calculated_net_pay"] = parse_decimal(np_match.group(1))
        
    # Year to Date values
    tgptd_match = re.search(r"Total Gross Pay TD\s+([\d,.]+)", text)
    if tgptd_match:
        data["ytd_gross"] = parse_decimal(tgptd_match.group(1))
        
    # Tax paid TD
    tptd_match = re.search(r"Tax paid TD\s+([\d,.]+)", text)
    if tptd_match:
        data["ytd_tax"] = parse_decimal(tptd_match.group(1))
        
    # National Insurance TD
    nitd_match = re.search(r"National Insurance TD\s+([\d,.]+)", text)
    if nitd_match:
        data["ytd_ni"] = parse_decimal(nitd_match.group(1))

    # Calculate deductions total
    data["deductions_total"] = float(
        Decimal(str(data.get("paye_tax", 0.0))) +
        Decimal(str(data.get("national_insurance", 0.0))) +
        Decimal(str(data.get("pension", 0.0)))
    )

    return data
