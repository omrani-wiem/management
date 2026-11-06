from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.auth_utils import get_current_user
from app.database import get_db
from app.models.audit_event import AuditEvent
from app.models.user import User
from app.schemas.audit_event import AuditEventOut

router = APIRouter(prefix="/api/audit", tags=["audit"])


@router.get("/", response_model=list[AuditEventOut])
def list_audit_events(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Affiche les événements de l'utilisateur courant, sans corps ni contenu des réunions."""
    return (
        db.query(AuditEvent)
        .filter(AuditEvent.actor_id == current_user.id)
        .order_by(AuditEvent.created_at.desc(), AuditEvent.id.desc())
        .offset(skip)
        .limit(limit)
        .all()
    )
