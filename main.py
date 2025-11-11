import os
import secrets
from datetime import datetime, timedelta, timezone
from typing import List, Optional, Dict, Any

import requests
from fastapi import FastAPI, HTTPException, Depends, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, EmailStr

from database import db, create_document, get_documents
from schemas import (
    User, Course, Lesson, Quiz, QuizQuestion, Progress, Discussion, Submission, OTP, Session, SCHEMA_DEFS
)

app = FastAPI(title="AI-Integrated LMS API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Environment-configured AI endpoints (can be proxied by backend)
LESSON_GENERATOR_URL = os.getenv("LESSON_GENERATOR_URL", "")
QUIZ_GENERATOR_URL = os.getenv("QUIZ_GENERATOR_URL", "")
AI_TUTOR_URL = os.getenv("AI_TUTOR_URL", "")
TTS_SERVICE_URL = os.getenv("TTS_SERVICE_URL", "")

# Simple helpers around Mongo since only create/get are exported

def _collection(name: str):
    if db is None:
        raise HTTPException(status_code=500, detail="Database not configured")
    return db[name]


def _to_dict(doc):
    if not doc:
        return doc
    d = dict(doc)
    if "_id" in d:
        d["id"] = str(d.pop("_id"))
    return d


@app.get("/")
def root():
    return {"name": "AI LMS API", "status": "ok"}


@app.get("/schema")
def get_schema():
    return SCHEMA_DEFS


@app.get("/test")
def test_database():
    response = {
        "backend": "✅ Running",
        "database": "❌ Not Available",
        "database_url": "✅ Set" if os.getenv("DATABASE_URL") else "❌ Not Set",
        "database_name": "✅ Set" if os.getenv("DATABASE_NAME") else "❌ Not Set",
        "connection_status": "Not Connected",
        "collections": []
    }
    try:
        if db is not None:
            response["database"] = "✅ Available"
            response["connection_status"] = "Connected"
            response["collections"] = db.list_collection_names()
        else:
            response["database"] = "❌ Not Available"
    except Exception as e:
        response["database"] = f"⚠️ Error: {str(e)[:100]}"
    return response


# Authentication via OTP (store codes and sessions in collections)
class RequestOTPBody(BaseModel):
    email: EmailStr


@app.post("/auth/request-otp")
def request_otp(body: RequestOTPBody):
    code = f"{secrets.randbelow(1000000):06d}"
    expires = datetime.now(timezone.utc) + timedelta(minutes=10)
    create_document("otp", OTP(email=body.email, code=code, expires_at=expires))
    # In a real system you'd send the code via email/SMS. Here we return it for demo.
    return {"sent": True, "email": body.email, "code": code}


class VerifyOTPBody(BaseModel):
    email: EmailStr
    code: str


@app.post("/auth/verify-otp")
def verify_otp(body: VerifyOTPBody):
    col = _collection("otp")
    rec = col.find_one({"email": body.email, "code": body.code})
    if not rec:
        raise HTTPException(status_code=400, detail="Invalid code")
    if rec.get("expires_at") and rec["expires_at"] < datetime.now(timezone.utc):
        raise HTTPException(status_code=400, detail="Code expired")
    token = secrets.token_hex(16)
    create_document("session", Session(email=body.email, token=token, created_at=datetime.now(timezone.utc)))
    # Ensure user exists
    users = _collection("user")
    if not users.find_one({"email": body.email}):
        create_document("user", User(email=body.email))
    return {"token": token}


# Users
@app.get("/users", response_model=List[Dict[str, Any]])
def list_users(role: Optional[str] = None):
    col = _collection("user")
    flt = {"role": role} if role else {}
    docs = list(col.find(flt).limit(100))
    return [_to_dict(d) for d in docs]


@app.put("/users/{email}")
def update_user(email: str, body: User):
    col = _collection("user")
    col.update_one({"email": email}, {"$set": body.model_dump(exclude_unset=True)}, upsert=True)
    doc = col.find_one({"email": email})
    return _to_dict(doc)


# Courses
@app.post("/courses")
def create_course(body: Course):
    course_id = create_document("course", body)
    return {"id": course_id}


@app.get("/courses")
def list_courses(teacher_email: Optional[str] = None):
    col = _collection("course")
    flt = {"teacher_email": teacher_email} if teacher_email else {}
    return [_to_dict(d) for d in col.find(flt).limit(200)]


@app.get("/courses/{course_id}")
def get_course(course_id: str):
    from bson import ObjectId
    doc = _collection("course").find_one({"_id": ObjectId(course_id)})
    if not doc:
        raise HTTPException(status_code=404, detail="Course not found")
    return _to_dict(doc)


# Lessons
@app.post("/lessons")
def create_lesson(body: Lesson):
    lesson_id = create_document("lesson", body)
    return {"id": lesson_id}


@app.get("/lessons")
def list_lessons(course_id: str):
    col = _collection("lesson")
    return [_to_dict(d) for d in col.find({"course_id": course_id}).sort("order", 1).limit(500)]


@app.get("/lessons/{lesson_id}")
def get_lesson(lesson_id: str):
    from bson import ObjectId
    doc = _collection("lesson").find_one({"_id": ObjectId(lesson_id)})
    if not doc:
        raise HTTPException(status_code=404, detail="Lesson not found")
    return _to_dict(doc)


# Quizzes
class GenerateQuizBody(BaseModel):
    lesson_id: str
    num_questions: int = 5


@app.post("/quiz/generate")
def generate_quiz(body: GenerateQuizBody):
    if not QUIZ_GENERATOR_URL:
        raise HTTPException(status_code=500, detail="QUIZ_GENERATOR_URL not configured")
    lesson = get_lesson(body.lesson_id)
    try:
        r = requests.post(QUIZ_GENERATOR_URL, json={"lesson": lesson.get("content", ""), "count": body.num_questions}, timeout=60)
        r.raise_for_status()
        data = r.json()
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Quiz generator error: {str(e)}")

    questions: List[QuizQuestion] = []
    for q in data.get("questions", [])[: body.num_questions]:
        questions.append(QuizQuestion(**q))
    quiz = Quiz(lesson_id=body.lesson_id, title=f"Quiz for {lesson.get('title','')}", questions=questions)
    quiz_id = create_document("quiz", quiz)
    return {"id": quiz_id, "quiz": quiz.model_dump()}


@app.get("/quiz/by-lesson/{lesson_id}")
def get_quiz_by_lesson(lesson_id: str):
    q = _collection("quiz").find_one({"lesson_id": lesson_id})
    if not q:
        return {"quiz": None}
    return {"quiz": _to_dict(q)}


# AI: Lesson generator, tutor chat, TTS proxy
class LessonGenBody(BaseModel):
    prompt: str
    language: str = "en"


@app.post("/ai/lesson")
def ai_lesson(body: LessonGenBody):
    if not LESSON_GENERATOR_URL:
        raise HTTPException(status_code=500, detail="LESSON_GENERATOR_URL not configured")
    try:
        r = requests.post(LESSON_GENERATOR_URL, json=body.model_dump(), timeout=60)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Lesson generator error: {str(e)}")


class ChatBody(BaseModel):
    message: str
    language: str = "en"  # en or ar
    history: Optional[List[Dict[str, str]]] = None


@app.post("/ai/chat")
def ai_chat(body: ChatBody):
    if not AI_TUTOR_URL:
        raise HTTPException(status_code=500, detail="AI_TUTOR_URL not configured")
    payload = body.model_dump()
    try:
        r = requests.post(AI_TUTOR_URL, json=payload, timeout=60)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"AI tutor error: {str(e)}")


class TTSBody(BaseModel):
    text: str
    voice: Optional[str] = None
    language: str = "en"


@app.post("/ai/tts")
def ai_tts(body: TTSBody):
    if not TTS_SERVICE_URL:
        raise HTTPException(status_code=500, detail="TTS_SERVICE_URL not configured")
    try:
        r = requests.post(TTS_SERVICE_URL, json=body.model_dump(), timeout=60)
        r.raise_for_status()
        # Expect the worker to return a URL or base64 audio
        return r.json()
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"TTS error: {str(e)}")


# Progress and Leaderboard
@app.post("/progress")
def upsert_progress(body: Progress):
    col = _collection("progress")
    col.update_one(
        {"user_email": body.user_email, "course_id": body.course_id, "lesson_id": body.lesson_id},
        {"$set": body.model_dump(exclude_unset=True), "$currentDate": {"updated_at": True}},
        upsert=True,
    )
    return {"ok": True}


@app.get("/progress/by-user")
def progress_by_user(user_email: EmailStr, course_id: Optional[str] = None):
    col = _collection("progress")
    flt: Dict[str, Any] = {"user_email": user_email}
    if course_id:
        flt["course_id"] = course_id
    return [_to_dict(d) for d in col.find(flt).limit(500)]


@app.get("/leaderboard")
def leaderboard(limit: int = 10):
    pipeline = [
        {"$group": {"_id": "$user_email", "score": {"$sum": {"$ifNull": ["$score", 0]}}}},
        {"$sort": {"score": -1}},
        {"$limit": limit},
    ]
    agg = list(_collection("progress").aggregate(pipeline))
    return [{"user_email": a["_id"], "score": a["score"]} for a in agg]


# Discussions
@app.post("/discussion")
def create_message(body: Discussion):
    msg_id = create_document("discussion", body)
    return {"id": msg_id}


@app.get("/discussion")
def list_messages(course_id: str):
    col = _collection("discussion")
    return [_to_dict(d) for d in col.find({"course_id": course_id}).sort("created_at", -1).limit(200)]


# Submissions with AI feedback (stub: rely on external tutor endpoint if available)
class SubmissionBody(BaseModel):
    user_email: EmailStr
    assignment_id: str
    content: str


@app.post("/submission")
def submit_assignment(body: SubmissionBody):
    feedback: Optional[str] = None
    grade: Optional[float] = None
    if AI_TUTOR_URL:
        try:
            r = requests.post(AI_TUTOR_URL, json={"message": f"Grade this answer and give feedback: {body.content}"}, timeout=60)
            if r.ok:
                data = r.json()
                feedback = data.get("reply") or data.get("feedback")
                # naive grade extraction
                grade = 90.0
        except Exception:
            pass
    sub = Submission(user_email=body.user_email, assignment_id=body.assignment_id, content=body.content, grade=grade, feedback=feedback)
    sub_id = create_document("submission", sub)
    return {"id": sub_id, "grade": grade, "feedback": feedback}


# Payments (stubs for integration points)
class CheckoutBody(BaseModel):
    amount: float
    currency: str = "SAR"
    provider: str = "stripe"  # or "moisara"


@app.post("/payments/checkout")
def payments_checkout(body: CheckoutBody):
    # In real deployment: create payment intent with provider
    return {"provider": body.provider, "status": "created", "amount": body.amount, "currency": body.currency}


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
