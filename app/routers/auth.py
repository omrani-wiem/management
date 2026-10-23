import logging
import time
from collections import defaultdict

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordRequestForm
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.auth_utils import (
    create_access_token,
    get_current_user,
    hash_password,
    verify_password,
)
from app.database import get_db
from app.models.user import User
from app.schemas.user import UserCreate, UserOut

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/auth", tags=["auth"])

# --- Limitation des tentatives de connexion (en mémoire, par processus) ---
MAX_FAILED_ATTEMPTS = 5
WINDOW_SECONDS = 15 * 60
_failed: dict[str, list[float]] = defaultdict(list)


class LoginRequest(BaseModel):
    email: str
    password: str


def _rate_key(request: Request, email: str) -> str:
    ip = request.client.host if request.client else "unknown"
    return f"{ip}:{email.strip().lower()}"


def _check_rate_limit(key: str) -> None:
    now = time.time()
    recent = [t for t in _failed[key] if now - t < WINDOW_SECONDS]
    _failed[key] = recent
    if len(recent) >= MAX_FAILED_ATTEMPTS:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Trop de tentatives. Réessaie dans quelques minutes.",
        )


def _authenticate(db: Session, email: str, password: str, key: str) -> User:
    _check_rate_limit(key)
    user = db.query(User).filter(func.lower(User.email) == email.strip().lower()).first()
    if not user or not verify_password(password, user.hashed_password):
        _failed[key].append(time.time())
        raise HTTPException(status_code=401, detail="Email ou mot de passe incorrect")
    _failed.pop(key, None)
    return user


def _token_response(user: User) -> dict:
    return {
        "access_token": create_access_token({"sub": str(user.id)}),
        "token_type": "bearer",
    }


@router.post("/register", response_model=UserOut, status_code=201)
def register(payload: UserCreate, db: Session = Depends(get_db)):
    email = payload.email.lower()
    if db.query(User).filter(func.lower(User.email) == email).first():
        raise HTTPException(status_code=400, detail="Cet email est déjà utilisé")
    user = User(
        email=email,
        hashed_password=hash_password(payload.password),
        full_name=payload.full_name.strip(),
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@router.post("/login")
def login(payload: LoginRequest, request: Request, db: Session = Depends(get_db)):
    """Connexion JSON (utilisée par le front)."""
    user = _authenticate(db, payload.email, payload.password, _rate_key(request, payload.email))
    return _token_response(user)


@router.post("/token")
def login_form(
    request: Request,
    form: OAuth2PasswordRequestForm = Depends(),
    db: Session = Depends(get_db),
):
    """Connexion formulaire OAuth2 (bouton Authorize de Swagger). username = email."""
    user = _authenticate(db, form.username, form.password, _rate_key(request, form.username))
    return _token_response(user)


@router.get("/me", response_model=UserOut)
def me(current_user: User = Depends(get_current_user)):
    return current_user
