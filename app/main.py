from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.database import Base, engine
from app import models
from app.routers import auth, meetings, tasks


Base.metadata.create_all(bind=engine)

app = FastAPI(title="Meeting AI API", version="1.0.0")


app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(meetings.router)
app.include_router(tasks.router)


@app.get("/health")
def health():
    return {"status": "ok", "message": "Meeting AI is running"}
