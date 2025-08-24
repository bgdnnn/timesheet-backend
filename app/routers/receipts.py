from fastapi import APIRouter, Depends, UploadFile, File, Form, HTTPException, Query
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from datetime import date, datetime
from pathlib import Path
import shutil, mimetypes, re
from decimal import Decimal
from PIL import Image
import pytesseract

from ..db import get_session
from ..models import Receipt, Expense
from ..schemas import ReceiptOut
from ..config import settings
from ..auth import get_current_user
from ..utils.users import user_slug_from_identity

router = APIRouter(prefix="/receipts", tags=["receipts"])

AMT = re.compile(r"([£$€])?\s*(\d{1,6}(?:[.,]\d{3})*(?:[.,]\d{2})?)")
BAD_WORDS = {"receipt","total","subtotal","vat","tax","change","cash","visa","mastercard"}
CUR_MAP = {"£":"GBP","$":"USD","€":"EUR"}

def _user_safe_path(user, entry_date: date) -> Path:
    name = user_slug_from_identity(user)
    d = entry_date
    return Path(settings.MEDIA_ROOT) / "receipts" / name / f"{d.year:04d}" / f"{d.month:02d}" / f"{d.day:02d}"

def _ocr_text(path: Path) -> str:
    img = Image.open(path)
    return pytesseract.image_to_string(img, config="--psm 6")

def _parse_vendor(text: str) -> str | None:
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    for ln in lines[:6]:
        if any(b in ln.lower() for b in BAD_WORDS):
            continue
        if re.search(r"[A-Za-z]", ln):
            return ln[:120]
    return None

def _parse_amount(text: str) -> tuple[str|None, Decimal|None]:
    # prefer line with 'Total' (not 'Subtotal')
    for ln in text.splitlines():
        low = ln.lower()
        if "total" in low and "subtotal" not in low:
            for m in AMT.finditer(ln):
                sym, raw = m.groups()
                try:
                    val = Decimal(raw.replace(",", "").replace(" ", ""))
                    return CUR_MAP.get(sym or "£"), val
                except: pass
    # fallback: largest currency-marked amount
    best = None; best_cur = None
    for m in AMT.finditer(text):
        sym, raw = m.groups()
        try:
            val = Decimal(raw.replace(",", "").replace(" ", ""))
            if sym and (best is None or val > best):
                best, best_cur = val, CUR_MAP.get(sym)
        except: pass
    return best_cur or "GBP", best

@router.post("/upload", response_model=list[ReceiptOut])
async def upload_receipts(
    entry_date: str = Form(...),
    time_entry_id: int | None = Form(None),
    files: list[UploadFile] = File(...),
    session: AsyncSession = Depends(get_session),
    user=Depends(get_current_user),
):
    try:
        d = date.fromisoformat(entry_date)
    except:
        raise HTTPException(400, "Invalid entry_date; expected YYYY-MM-DD")
    if not files:
        raise HTTPException(400, "No files provided")

    base_dir = _user_safe_path(user, d)
    base_dir.mkdir(parents=True, exist_ok=True)
    created: list[Receipt] = []

    for up in files:
        ctype = up.content_type or mimetypes.guess_type(up.filename or "")[0] or "application/octet-stream"
        if not ctype.startswith("image/"):
            raise HTTPException(415, f"Unsupported type: {ctype}")

        ts = datetime.utcnow().strftime("%H%M%S%f")
        ext = Path(up.filename or "").suffix or ".jpg"
        dest = base_dir / f"{ts}{ext}"
        with dest.open("wb") as f:
            shutil.copyfileobj(up.file, f)

        rec = Receipt(
            created_by=user.email,
            time_entry_id=time_entry_id,
            entry_date=d,
            file_path=str(dest),
            original_filename=up.filename,
            mime_type=ctype,
            size_bytes=dest.stat().st_size,
        )
        session.add(rec)
        await session.flush()

        # OCR -> Expense row
        try:
            text = _ocr_text(dest)
        except Exception:
            text = ""
        cur, amt = _parse_amount(text)
        vendor = _parse_vendor(text)
        exp = Expense(
            created_by=user.email,
            receipt_id=rec.id,
            time_entry_id=time_entry_id,
            entry_date=d,
            vendor_name=vendor,
            total_amount=amt,
            currency=cur or "GBP",
            status="parsed" if amt is not None else "needs_review",
            raw_text=text[:4000],
        )
        session.add(exp)
        created.append(rec)

    await session.commit()
    for r in created:
        await session.refresh(r)
    return created

@router.get("", response_model=list[ReceiptOut])
async def list_receipts(
    start: date | None = Query(None), end: date | None = Query(None),
    session: AsyncSession = Depends(get_session), user=Depends(get_current_user),
):
    q = select(Receipt).where(Receipt.created_by == user.email)
    if start: q = q.where(Receipt.entry_date >= start)
    if end:   q = q.where(Receipt.entry_date <= end)
    q = q.order_by(Receipt.entry_date.desc(), Receipt.created_date.desc(), Receipt.id.desc())
    rows = (await session.execute(q)).scalars().all()
    return rows

@router.get("/{receipt_id}/file")
async def get_file(receipt_id: int, session: AsyncSession = Depends(get_session), user=Depends(get_current_user)):
    rec = await session.get(Receipt, receipt_id)
    if not rec or rec.created_by != user.email:
        raise HTTPException(404, "Not found")
    p = Path(rec.file_path)
    if not p.exists():
        raise HTTPException(404, "File missing")
    return FileResponse(str(p), media_type=rec.mime_type or "application/octet-stream", filename=rec.original_filename or p.name)
