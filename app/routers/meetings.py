from fastapi import APIRouter, UploadFile, File, Form, Depends, HTTPException
from sqlalchemy.orm import Session
from app.database import get_db
from app.models.meeting import Meeting
from app.schemas.meeting import MeetingOut, MeetingDetail
from app.workers.tasks import process_meeting
import os
import uuid

router = APIRouter(prefix="/api/meetings", tags=["meetings"])

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
UPLOAD_DIR = os.path.join(BASE_DIR, "uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)

ALLOWED_TYPES = ["audio/mpeg", "audio/wav", "audio/mp4", "audio/webm", "audio/x-m4a", "audio/m4a"]


@router.post("/upload", response_model=MeetingOut)
async def upload_meeting( title: str = Form(...), file: UploadFile = File(...), db: Session = Depends(get_db)):
    if file.content_type not in ALLOWED_TYPES:
        raise HTTPException(400, f"Format non supporté: {file.content_type}")
    
    filename = f"{uuid.uuid4()}_{file.filename}"
    filepath = os.path.join(UPLOAD_DIR, filename)

    with open(filepath, "wb") as f:
        content = await file.read()
        f.write(content)

    meeting = Meeting(title=title, audio_path=filepath)
    db.add(meeting)
    db.commit()
    db.refresh(meeting)

    process_meeting.delay(str(meeting.id))
    

    return meeting

@router.get("/", response_model=list[MeetingOut])
def list_meetings(db: Session = Depends(get_db)):
    return db.query(Meeting).order_by(Meeting.created_at.desc()).all()


@router.get("/{meeting_id}", response_model=MeetingDetail)
def get_meeting(meeting_id: str, db: Session = Depends(get_db)):
    meeting = db.query(Meeting).filter(Meeting.id == meeting_id).first()
    if not meeting:
        raise HTTPException(404, "Réunion non trouvée")
    
    result = MeetingDetail.model_validate(meeting)
    if meeting.transcript:
        result.summary = meeting.transcript.summary
        result.raw_text = meeting.transcript.raw_text
    return result