from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.database import get_db
from app.models.task import Task
from app.schemas.task import TaskOut, TaskUpdate

router = APIRouter(prefix="/api/tasks", tags=["tasks"])

@router.get("/meeting/{meeting_id}", response_model=list[TaskOut])
def get_tasks_for_meeting(meeting_id: str, db: Session = Depends(get_db)):
    return db.query(Task).filter(Task.meeting_id == meeting_id).all()


@router.patch("/{task_id}", response_model=TaskOut)
def update_task(task_id: str, payload: TaskUpdate, db: Session = Depends(get_db)):
    task = db.query(Task).filter(Task.id == task_id).first()
    if not task:
        raise HTTPException(404, "Tâche non trouvée")
    
    if payload.status is not None:
        task.status = payload.status
    if payload.assignee is not None:
        task.assignee = payload.assignee

    
    db.commit()
    db.refresh(task)
    return task