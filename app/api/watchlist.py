"""Routes privées de liste de suivi, appelées uniquement par le BFF Next.js."""

import hmac

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field

from app.config import settings
from app.db.repo import (
    MAX_WATCHLIST_SIZE,
    add_watchlist_company,
    fetch_watchlist,
    get_company,
    get_conn,
    remove_watchlist_company,
    upsert_watchlist_user,
    watchlist_user_id,
)

router = APIRouter(prefix="/me/watchlist", tags=["watchlist"])


class WatchlistAddition(BaseModel):
    cik: int = Field(gt=0)


def _verify_frontend_request(
    x_watchlist_api_key: str = Header(default="", max_length=256),
    x_clerk_user_id: str = Header(default="", max_length=160),
    x_clerk_user_email: str = Header(default="", max_length=320),
) -> tuple[str, str]:
    """Vérifie le secret BFF et l'identité Clerk ajoutée côté serveur Next."""
    expected = settings.watchlist_api_secret
    if len(expected) < 32:
        raise HTTPException(
            status_code=503,
            detail="Le secret serveur de liste de suivi doit contenir au moins 32 caractères.",
        )
    if not hmac.compare_digest(x_watchlist_api_key, expected):
        raise HTTPException(status_code=401, detail="Authentification serveur invalide.")
    if not x_clerk_user_id or not x_clerk_user_email:
        raise HTTPException(status_code=401, detail="Connexion utilisateur requise.")
    return x_clerk_user_id, x_clerk_user_email


@router.get("")
def get_my_watchlist(
    identity: tuple[str, str] = Depends(_verify_frontend_request),
):
    conn = get_conn()
    try:
        user_id = watchlist_user_id(identity[0])
        items = fetch_watchlist(conn, user_id)
        return {"items": items, "limit": MAX_WATCHLIST_SIZE}
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


@router.post("")
def add_to_my_watchlist(
    body: WatchlistAddition,
    identity: tuple[str, str] = Depends(_verify_frontend_request),
):
    conn = get_conn()
    try:
        company = get_company(conn, body.cik)
        if company is None:
            raise HTTPException(status_code=404, detail="Entreprise introuvable.")
        user_id = upsert_watchlist_user(conn, *identity)
        status = add_watchlist_company(conn, user_id, company["id"])
        if status == "limit_reached":
            conn.rollback()
            raise HTTPException(
                status_code=409,
                detail=f"La liste est limitée à {MAX_WATCHLIST_SIZE} entreprises.",
            )
        conn.commit()
        return {"status": status, "limit": MAX_WATCHLIST_SIZE}
    except HTTPException:
        raise
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


@router.delete("/{cik}")
def remove_from_my_watchlist(
    cik: int,
    identity: tuple[str, str] = Depends(_verify_frontend_request),
):
    conn = get_conn()
    try:
        company = get_company(conn, cik)
        if company is None:
            raise HTTPException(status_code=404, detail="Entreprise introuvable.")
        user_id = watchlist_user_id(identity[0])
        removed = remove_watchlist_company(conn, user_id, company["id"])
        return {"removed": removed}
    except HTTPException:
        raise
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
