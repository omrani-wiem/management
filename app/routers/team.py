import unicodedata
from collections import Counter
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func
from sqlalchemy.orm import Session, selectinload

from app.auth_utils import get_current_user
from app.database import get_db
from app.models.meeting import Meeting
from app.models.task import Task
from app.models.team import Team, TeamMember
from app.models.user import User
from app.schemas.team import (
    TeamCreate,
    TeamMemberCreate,
    TeamMemberOut,
    TeamMemberWithCount,
    TeamOut,
    TeamSummary,
)

router = APIRouter(prefix="/api/team", tags=["team"])


def _normalize(name: str) -> str:
    """minuscules, sans accents, espaces normalisés : 'Hélène  B.' -> 'helene b.'"""
    s = unicodedata.normalize("NFKD", name or "")
    s = "".join(c for c in s if not unicodedata.combining(c))
    return " ".join(s.lower().split())


def _get_team(db: Session, team_id: UUID, user: User) -> Team:
    team = db.query(Team).filter(Team.id == team_id, Team.owner_id == user.id).first()
    if not team:
        raise HTTPException(status_code=404, detail="Équipe introuvable")
    return team


def _task_counts(db: Session, user: User) -> dict[str, int]:
    """Nombre de tâches par assignee (normalisé), uniquement sur les réunions de l'utilisateur."""
    rows = (
        db.query(Task.assignee, func.count(Task.id))
        .join(Meeting, Task.meeting_id == Meeting.id)
        .filter(Meeting.owner_id == user.id, Task.assignee.isnot(None))
        .group_by(Task.assignee)
        .all()
    )
    counts: dict[str, int] = {}
    for assignee, n in rows:
        key = _normalize(assignee)
        counts[key] = counts.get(key, 0) + n
    return counts


# NB : les routes statiques (/members) doivent être déclarées AVANT /{team_id}

@router.get("/members", response_model=list[TeamMemberWithCount])
def list_members_with_workload(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    members = (
        db.query(TeamMember)
        .join(Team, TeamMember.team_id == Team.id)
        .filter(Team.owner_id == current_user.id)
        .order_by(TeamMember.full_name)
        .all()
    )
    counts = _task_counts(db, current_user)
    first_name_freq = Counter(_normalize(m.full_name).split(" ")[0] for m in members)

    result = []
    for m in members:
        full = _normalize(m.full_name)
        n = counts.get(full, 0)
        first = full.split(" ")[0]
        # repli sur le prénom seul, seulement s'il n'est pas ambigu dans l'équipe
        if n == 0 and first_name_freq[first] == 1:
            n = counts.get(first, 0)
        result.append(
            TeamMemberWithCount(
                id=m.id, team_id=m.team_id, full_name=m.full_name,
                email=m.email, role=m.role, task_count=n,
            )
        )
    return result


@router.get("/", response_model=list[TeamSummary])
def list_teams(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    teams = (
        db.query(Team)
        .options(selectinload(Team.members))
        .filter(Team.owner_id == current_user.id)
        .order_by(Team.created_at)
        .all()
    )
    return [TeamSummary(id=t.id, name=t.name, member_count=len(t.members)) for t in teams]


@router.post("/", response_model=TeamOut, status_code=status.HTTP_201_CREATED)
def create_team(
    payload: TeamCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    team = Team(name=payload.name.strip(), owner_id=current_user.id)
    db.add(team)
    db.commit()
    db.refresh(team)
    return team


@router.get("/{team_id}", response_model=TeamOut)
def get_team(
    team_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return _get_team(db, team_id, current_user)


@router.post("/{team_id}/members", response_model=TeamMemberOut, status_code=201)
def add_member(
    team_id: UUID,
    payload: TeamMemberCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    team = _get_team(db, team_id, current_user)
    member = TeamMember(
        team_id=team.id,
        full_name=payload.full_name.strip(),
        email=payload.email,
        role=payload.role,
    )
    db.add(member)
    db.commit()
    db.refresh(member)
    return member


@router.delete("/{team_id}/members/{member_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_member(
    team_id: UUID,
    member_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    team = _get_team(db, team_id, current_user)
    member = (
        db.query(TeamMember)
        .filter(TeamMember.id == member_id, TeamMember.team_id == team.id)
        .first()
    )
    if not member:
        raise HTTPException(status_code=404, detail="Membre introuvable")
    db.delete(member)
    db.commit()
