from fastapi import APIRouter, Depends, UploadFile, File
from ..utils.payslip_parser import parse_payslip

router = APIRouter(prefix="/payslips", tags=["payslips"])

@router.post("/parse")
async def parse_payslip_file(file: UploadFile = File(...)):
    content = await file.read()
    # We need to save the file temporarily to use pytesseract
    import tempfile
    with tempfile.NamedTemporaryFile(delete=False) as temp:
        temp.write(content)
        temp_path = temp.name
    
    from PIL import Image
    import pytesseract
    img = Image.open(temp_path)
    text = pytesseract.image_to_string(img, config="--psm 6")

    import os
    os.remove(temp_path)

    return parse_payslip(text)
