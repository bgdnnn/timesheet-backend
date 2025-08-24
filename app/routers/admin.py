from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update
from typing import List

from ..db import get_session
from ..auth import get_admin_user
from ..models import User
from ..schemas import UserOut, AdminUserUpdate

router = APIRouter(prefix="/admin", tags=["admin"])

@router.get("/users", response_model=List[UserOut])
async def list_users(
    session: AsyncSession = Depends(get_session),
    admin: User = Depends(get_admin_user)
):
    """
    Lists all users. Requires admin privileges.
    """
    users = (await session.execute(select(User).order_by(User.id))).scalars().all()
    return users

@router.put("/users/{user_id}", response_model=UserOut)
async def update_user(
    user_id: int,
    payload: AdminUserUpdate,
    session: AsyncSession = Depends(get_session),
    admin: User = Depends(get_admin_user)
):
    """
    Updates a user's details. Requires admin privileges.
    """
    user_to_update = (await session.execute(select(User).where(User.id == user_id))).scalar_one_or_none()
    if not user_to_update:
        raise HTTPException(status_code=404, detail="User not found")

    update_data = payload.dict(exclude_unset=True)
    
    if not update_data:
        raise HTTPException(status_code=400, detail="No update data provided")

    await session.execute(
        update(User).where(User.id == user_id).values(**update_data)
    )
    await session.commit()
    await session.refresh(user_to_update)
    return user_to_update

@router.get("/users/{user_id}", response_model=UserOut)
async def get_user(
    user_id: int,
    session: AsyncSession = Depends(get_session),
    admin: User = Depends(get_admin_user)
):
    """
    Retrieves a single user's details. Requires admin privileges.
    """
    user = (await session.execute(select(User).where(User.id == user_id))).scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return user

@router.delete("/users/{user_id}", status_code=200)
async def delete_user(
    user_id: int,
    session: AsyncSession = Depends(get_session),
    admin: User = Depends(get_admin_user)
):
    """
    Deletes a user. Requires admin privileges.
    """
    user_to_delete = (await session.execute(select(User).where(User.id == user_id))).scalar_one_or_none()
    if not user_to_delete:
        raise HTTPException(status_code=404, detail="User not found")
    
    await session.delete(user_to_delete)
    await session.commit()
    return {"message": "User deleted successfully"}
