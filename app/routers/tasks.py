from datetime import date
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Query, Session

from app.auth_utils import get_current_user
from app.database import get_db
from app.models.meeting import Meeting
from app.models.task import Task, TaskStatus
from app.models.user import User
from app.schemas.task import TaskOut, TaskUpdate
from app.services import jira as jira_service

router = APIRouter(prefix="/api/tasks", tags=["tasks"])


def _owned_tasks(db: Session, user: User) -> Query:
    """Toutes les tâches des réunions de l'utilisateur (isolation des données)."""
    return (
        db.query(Task)
        .join(Meeting, Task.meeting_id == Meeting.id)
        .filter(Meeting.owner_id == user.id)
    )


@router.get("/", response_model=list[TaskOut])
def list_tasks(
    status: TaskStatus | None = None,
    assignee: str | None = None,
    overdue: bool = False,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Filtres optionnels : ?status=todo  ?assignee=Ali  ?overdue=true (échéance dépassée, non terminée)."""
    query = _owned_tasks(db, current_user)
    if status is not None:
        query = query.filter(Task.status == status)
    if assignee:
        query = query.filter(func.lower(Task.assignee) == assignee.strip().lower())
    if overdue:
        query = query.filter(
            Task.due_date.isnot(None),
            Task.due_date < date.today(),
            Task.status != TaskStatus.done,
        )
    return query.order_by(Task.created_at.desc()).all()


@router.get("/meeting/{meeting_id}", response_model=list[TaskOut])
def get_tasks_for_meeting(
    meeting_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    meeting = (
        db.query(Meeting)
        .filter(Meeting.id == meeting_id, Meeting.owner_id == current_user.id)
        .first()
    )
    if not meeting:
        raise HTTPException(status_code=404, detail="Réunion introuvable")
    return (
        db.query(Task)
        .filter(Task.meeting_id == meeting_id)
        .order_by(Task.created_at.desc())
        .all()
    )


@router.patch("/{task_id}", response_model=TaskOut)
def update_task(
    task_id: UUID,
    payload: TaskUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    task = _owned_tasks(db, current_user).filter(Task.id == task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="Tâche introuvable")

    data = payload.model_dump(exclude_unset=True)
    if data.get("status") is not None:
        task.status = data["status"]
    if data.get("priority") is not None:
        task.priority = data["priority"]
    if "assignee" in data:  # permet aussi de désassigner avec "assignee": null
        task.assignee = data["assignee"].strip() if data["assignee"] else None
    if "due_date" in data:  # idem : "due_date": null efface l'échéance
        task.due_date = data["due_date"]

    db.commit()
    db.refresh(task)
    return task


@router.post("/{task_id}/jira", response_model=TaskOut)
def create_jira_issue(
    task_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    task = _owned_tasks(db, current_user).filter(Task.id == task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="Tâche introuvable")
    if task.jira_issue_key:
        raise HTTPException(status_code=409, detail="Cette tâche est déjà liée à un ticket Jira")

    meeting = db.query(Meeting).filter(Meeting.id == task.meeting_id).first()
    try:
        issue_key, issue_url = jira_service.create_issue(task, meeting.title)
    except jira_service.JiraError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc

    task.jira_issue_key = issue_key
    task.jira_issue_url = issue_url
    db.commit()
    db.refresh(task)
    return task


@router.post("/{task_id}/jira/refresh", response_model=TaskOut)
def refresh_jira_issue(
    task_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    task = _owned_tasks(db, current_user).filter(Task.id == task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="Tâche introuvable")
    if not task.jira_issue_key:
        raise HTTPException(status_code=409, detail="Cette tâche n'est pas encore liée à un ticket Jira")

    try:
        task.jira_status = jira_service.get_issue_status(task.jira_issue_key)
    except jira_service.JiraError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc

    db.commit()
    db.refresh(task)
    return task
