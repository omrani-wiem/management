from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.database import get_db
from app.models.user import User
from app.schemas.user import UserCreate, UserOut
from app.auth_utils import hash_password, verify_password, create_access_token

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post("/register", response_model=UserOut)
def register(payload: UserCreate, db: Session = Depends(get_db)):
   existing = db.query(User).filter(User.email == payload.email).first()
   if existing:
      raise HTTPException(status_code=400, detail="Cet email est deja utilisé")

   user = User(
      email=payload.email,
      hashed_password=hash_password(payload.password),
      full_name=payload.full_name,
   )
   db.add(user)
   db.commit()
   db.refresh(user)
   return user

@router.post("/login")
def login(email: str, password: str, db: Session = Depends(get_db)):
   user = db.query(User).filter(User.email == email).first()
   if not user or not verify_password(password, user.hashed_password):
        raise HTTPException(status_code=401, detail="Email ou mot de passe incorrect")
   
   token = create_access_token({"sub": str(user.id)})
   return {"access_token": token, "token_type": "bearer"}



