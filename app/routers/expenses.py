from datetime import date
from fastapi import APIRouter, Depends, Query, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from typing import List
import os
from pathlib import Path
import traceback
import re

from ..db import get_session
from ..auth import get_current_user
from ..models import Expense, User, Receipt
from ..schemas import ExpenseOut, ExpenseGroupOut, ExpenseIn

router = APIRouter(prefix="/expenses", tags=["expenses"])

@router.post("", response_model=ExpenseOut)
async def create_expense(expense_in: ExpenseIn, session: AsyncSession = Depends(get_session), user: User = Depends(get_current_user)):
    expense = Expense(**expense_in.model_dump(), created_by=user.email)
    session.add(expense)
    await session.commit()
    await session.refresh(expense)
    return expense

@router.put("/{expense_id}", response_model=ExpenseOut)
async def update_expense(
    expense_id: int,
    expense_in: ExpenseIn,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user)
):
    expense = await session.get(Expense, expense_id)
    if not expense or expense.created_by != user.email:
        raise HTTPException(status_code=404, detail="Expense not found")

    # Update fields from expense_in
    for field, value in expense_in.model_dump(exclude_unset=True).items():
        setattr(expense, field, value)

    await session.commit()
    await session.refresh(expense)
    return expense

@router.get("", response_model=List[ExpenseOut])
async def list_expenses(
    start: date | None = Query(None),
    end: date | None = Query(None),
    session: AsyncSession = Depends(get_session),
    user=Depends(get_current_user)
):
    try:
        q = (
            select(Expense, Receipt.original_filename)
            .join(Receipt, Expense.receipt_id == Receipt.id, isouter=True)
            .filter(Expense.created_by == user.email)
            .order_by(Expense.entry_date.desc(), Expense.created_date.desc(), Expense.id.desc())
        )

        if start:
            q = q.where(Expense.entry_date >= start)
        if end:
            q = q.where(Expense.entry_date <= end)

        result = await session.execute(q)
        expenses = []
        for expense, receipt_filename in result:
            expenses.append(
                ExpenseOut(
                    id=expense.id,
                    receipt_id=expense.receipt_id,
                    receipt_filename=receipt_filename,
                    time_entry_id=expense.time_entry_id,
                    entry_date=expense.entry_date,
                    vendor=expense.vendor,
                    expense_type=expense.expense_type,
                    total_amount=expense.total_amount,
                    currency=expense.currency,
                    created_date=expense.created_date,
                )
            )
        return expenses
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error listing expenses: {e}\n{traceback.format_exc()}")


@router.get("/summary", response_model=List[ExpenseGroupOut])
async def get_expenses_summary(group_by: str = Query("month"), session: AsyncSession = Depends(get_session), user=Depends(get_current_user)):
    # For now, this will return an empty list.
    # In the future, we will implement the grouping logic here.
    return []
