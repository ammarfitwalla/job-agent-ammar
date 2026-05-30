from fastapi import APIRouter
from config import ROLES_BY_CATEGORY

router = APIRouter(prefix="/roles", tags=["roles"])


@router.get("")
async def get_roles():
    return {"categories": ROLES_BY_CATEGORY}
