"""
Database Schemas for LMS

Each Pydantic model represents a MongoDB collection.
Collection name is the lowercase of the class name.
"""
from pydantic import BaseModel, Field, EmailStr
from typing import Optional, List, Dict, Any
from datetime import datetime

class User(BaseModel):
    name: Optional[str] = Field(None, description="Full name")
    email: EmailStr = Field(..., description="Email address")
    role: str = Field("student", description="Role: student | teacher | admin")
    avatar_url: Optional[str] = None
    locale: str = Field("en", description="Preferred locale: en | ar")
    points: int = 0

class Course(BaseModel):
    title: str
    description: Optional[str] = None
    language: str = Field("en", description="Course language")
    published: bool = False
    teacher_email: Optional[EmailStr] = None
    tags: List[str] = []

class Lesson(BaseModel):
    course_id: str
    title: str
    content: str = Field("", description="HTML or Markdown content of the lesson")
    order: int = 0
    language: str = Field("en")

class QuizQuestion(BaseModel):
    question: str
    options: List[str] = []
    answer: Optional[str] = None
    explanation: Optional[str] = None

class Quiz(BaseModel):
    lesson_id: str
    title: str
    questions: List[QuizQuestion] = []

class Progress(BaseModel):
    user_email: EmailStr
    course_id: str
    lesson_id: Optional[str] = None
    completed: bool = False
    score: Optional[float] = None

class Discussion(BaseModel):
    course_id: str
    user_email: EmailStr
    message: str
    parent_id: Optional[str] = None

class Submission(BaseModel):
    user_email: EmailStr
    assignment_id: str
    content: str
    grade: Optional[float] = None
    feedback: Optional[str] = None

class OTP(BaseModel):
    email: EmailStr
    code: str
    expires_at: datetime

class Session(BaseModel):
    email: EmailStr
    token: str
    created_at: datetime

# Export a mapping to help the /schema endpoint (optional)
SCHEMA_DEFS: Dict[str, Any] = {
    "user": User.model_json_schema(),
    "course": Course.model_json_schema(),
    "lesson": Lesson.model_json_schema(),
    "quiz": Quiz.model_json_schema(),
    "progress": Progress.model_json_schema(),
    "discussion": Discussion.model_json_schema(),
    "submission": Submission.model_json_schema(),
    "otp": OTP.model_json_schema(),
    "session": Session.model_json_schema(),
}
