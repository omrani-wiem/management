from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session, joinedload
import uuid

from app.database import get_db
from app.models.team import Team, TeamMember
from app.schemas.team import TeamCreate, TeamOut, TeamSummary, TeamMemberCreate, TeamMemberOut
from app.auth_utils import get_current_user  # adapte le nom si différent
from app.models.user import User

router = APIRouter(prefix="/api/team", tags=["team"])



@router.get("/", response_model=list[TeamMemberOut])
def list_team(db: Session = Depends(get_db)):
    """
    Renvoie les utilisateurs avec leur nombre de tâches assignées.

    L'assignee est généré par l'IA à partir de la transcription : ce n'est
    pas une clé fiable (casse différente, espaces, parfois juste le prénom).
    On normalise donc la comparaison, avec un repli sur le prénom seul.
    """
    users = db.query(User).order_by(User.full_name).all()

    raw_counts = (
        db.query(Task.assignee, func.count(Task.id))
        .group_by(Task.assignee)
        .all()
    )
    assignee_counts = [(a, c) for a, c in raw_counts if a]

    def normalize(s: str) -> str:
        return " ".join(s.strip().lower().split())

    # ex: {"karim ben ali": 4, "karim": 2, ...}
    normalized_counts: dict[str, int] = {}
    for assignee, count in raw_counts:
        if not assignee:
            continue
        normalized_counts[normalize(assignee)] = normalized_counts.get(normalize(assignee), 0) + count

    result = []
    for u in users:
        display_name = u.full_name or u.email
        norm_full = normalize(display_name)
        norm_first = norm_full.split(" ")[0] if norm_full else ""

        count = normalized_counts.get(norm_full, 0)
        if count == 0 and norm_first:
            # Repli : additionne tout ce qui correspond au prénom seul
            # (utile quand l'IA n'a extrait que "Karim" et non "Karim Ben Ali")
            count = sum(
                c for name, c in normalized_counts.items()
                if name == norm_first or name.startswith(norm_first + " ")
            )

        result.append(
            TeamMemberOut(
                id=u.id,
                name=display_name,
                email=u.email,
                task_count=count,
            )
        )
    return result