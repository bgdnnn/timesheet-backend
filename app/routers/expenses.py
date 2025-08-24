from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from typing import List

from ..db import get_session
from ..auth import get_current_user
from ..models import Expense
from ..schemas import ExpenseOut, ExpenseGroupOut

router = APIRouter(prefix="/expenses", tags=["expenses"])

@router.get("", response_model=List[ExpenseOut])
async def list_expenses(session: AsyncSession = Depends(get_session), user=Depends(get_current_user)):
    # For now, this will return an empty list as there are no expenses.
    # In the future, we will query the Expense table here.
    return []

@router.get("/summary", response_model=List[ExpenseGroupOut])
async def get_expenses_summary(group_by: str = Query("month"), session: AsyncSession = Depends(get_session), user=Depends(get_current_user)):
    # For now, this will return an empty list.
    # In the future, we will implement the grouping logic here.
    return []
