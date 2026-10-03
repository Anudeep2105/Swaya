from datetime import datetime, timezone
from sqlalchemy import String, Integer, Boolean, DateTime, ForeignKey, Text, UniqueConstraint, Float
from sqlalchemy.orm import Mapped, mapped_column
from .database import Base

def utcnow(): return datetime.now(timezone.utc)

class User(Base):
    __tablename__='users'
    id: Mapped[int]=mapped_column(primary_key=True)
    name: Mapped[str]=mapped_column(String(120))
    email: Mapped[str]=mapped_column(String(255),unique=True,index=True)
    password_hash: Mapped[str]=mapped_column(String(255))
    role: Mapped[str]=mapped_column(String(20),default='learner',index=True)
    active: Mapped[bool]=mapped_column(Boolean,default=True)
    email_verified: Mapped[bool]=mapped_column(Boolean,default=False)
    mfa_enabled: Mapped[bool]=mapped_column(Boolean,default=False)
    mfa_secret: Mapped[str|None]=mapped_column(String(64),nullable=True)
    created_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),default=utcnow)

class Course(Base):
    __tablename__='courses'
    id: Mapped[int]=mapped_column(primary_key=True)
    course_code: Mapped[str]=mapped_column(String(30),unique=True,index=True)
    title: Mapped[str]=mapped_column(String(200))
    slug: Mapped[str]=mapped_column(String(220),unique=True,index=True)
    description: Mapped[str]=mapped_column(Text,default='')
    status: Mapped[str]=mapped_column(String(20),default='draft')
    created_by: Mapped[int]=mapped_column(ForeignKey('users.id'))
    created_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),default=utcnow)
    updated_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),default=utcnow,onupdate=utcnow)

class InstructorCourse(Base):
    __tablename__='instructor_courses'
    id: Mapped[int]=mapped_column(primary_key=True)
    course_id: Mapped[int]=mapped_column(ForeignKey('courses.id'),index=True)
    user_id: Mapped[int]=mapped_column(ForeignKey('users.id'),index=True)
    __table_args__=(UniqueConstraint('course_id','user_id',name='uq_instructor_course'),)

class Cohort(Base):
    __tablename__='cohorts'
    id: Mapped[int]=mapped_column(primary_key=True)
    course_id: Mapped[int]=mapped_column(ForeignKey('courses.id'),index=True)
    name: Mapped[str]=mapped_column(String(120))
    start_date: Mapped[str]=mapped_column(String(20))
    end_date: Mapped[str]=mapped_column(String(20))
    status: Mapped[str]=mapped_column(String(20),default='active')

class Enrollment(Base):
    __tablename__='enrollments'
    id: Mapped[int]=mapped_column(primary_key=True)
    user_id: Mapped[int]=mapped_column(ForeignKey('users.id'),index=True)
    course_id: Mapped[int]=mapped_column(ForeignKey('courses.id'),index=True)
    cohort_id: Mapped[int|None]=mapped_column(ForeignKey('cohorts.id'),nullable=True)
    enrolled_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),default=utcnow)
    status: Mapped[str]=mapped_column(String(20),default='active')
    __table_args__=(UniqueConstraint('user_id','course_id',name='uq_enrollment'),)

class Lesson(Base):
    __tablename__='lessons'
    id: Mapped[int]=mapped_column(primary_key=True)
    course_id: Mapped[int]=mapped_column(ForeignKey('courses.id'),index=True)
    day_number: Mapped[int]=mapped_column(Integer,index=True)
    title: Mapped[str]=mapped_column(String(200))
    goal: Mapped[str]=mapped_column(Text,default='')
    content_md: Mapped[str]=mapped_column(Text,default='')
    content_html: Mapped[str]=mapped_column(Text,default='')
    content_css: Mapped[str]=mapped_column(Text,default='')
    objectives_json: Mapped[str]=mapped_column(Text,default='[]')
    resources_json: Mapped[str]=mapped_column(Text,default='[]')
    status: Mapped[str]=mapped_column(String(20),default='published')
    estimated_minutes: Mapped[int]=mapped_column(Integer,default=60)
    lesson_code: Mapped[str]=mapped_column(String(60),unique=True,index=True)
    __table_args__=(UniqueConstraint('course_id','day_number',name='uq_course_day'),)

class CourseMedia(Base):
    __tablename__='course_media'
    id: Mapped[int]=mapped_column(primary_key=True)
    course_id: Mapped[int]=mapped_column(ForeignKey('courses.id'),index=True)
    lesson_id: Mapped[int|None]=mapped_column(ForeignKey('lessons.id'),nullable=True,index=True)
    title: Mapped[str]=mapped_column(String(255))
    original_filename: Mapped[str]=mapped_column(String(255))
    stored_filename: Mapped[str]=mapped_column(String(80),unique=True)
    media_type: Mapped[str]=mapped_column(String(100))
    media_kind: Mapped[str]=mapped_column(String(20),index=True)
    size_bytes: Mapped[int]=mapped_column(Integer)
    uploaded_by: Mapped[int]=mapped_column(ForeignKey('users.id'))
    created_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),default=utcnow)

class Question(Base):
    __tablename__='questions'
    id: Mapped[int]=mapped_column(primary_key=True)
    lesson_id: Mapped[int]=mapped_column(ForeignKey('lessons.id'),index=True)
    question: Mapped[str]=mapped_column(Text)
    options_json: Mapped[str]=mapped_column(Text)
    correct_index: Mapped[int]=mapped_column(Integer)
    explanation: Mapped[str]=mapped_column(Text,default='')
    resource_url: Mapped[str]=mapped_column(Text,default='')
    difficulty: Mapped[str]=mapped_column(String(20),default='medium',index=True)
    topic: Mapped[str]=mapped_column(String(100),default='',index=True)
    tags_json: Mapped[str]=mapped_column(Text,default='[]')
    active: Mapped[bool]=mapped_column(Boolean,default=True)

class Progress(Base):
    __tablename__='progress'
    id: Mapped[int]=mapped_column(primary_key=True)
    user_id: Mapped[int]=mapped_column(ForeignKey('users.id'),index=True)
    lesson_id: Mapped[int]=mapped_column(ForeignKey('lessons.id'),index=True)
    learning_complete: Mapped[bool]=mapped_column(Boolean,default=False)
    assessment_complete: Mapped[bool]=mapped_column(Boolean,default=False)
    completed: Mapped[bool]=mapped_column(Boolean,default=False)
    best_score: Mapped[int]=mapped_column(Integer,default=0)
    attempts: Mapped[int]=mapped_column(Integer,default=0)
    last_activity: Mapped[datetime]=mapped_column(DateTime(timezone=True),default=utcnow)
    __table_args__=(UniqueConstraint('user_id','lesson_id',name='uq_progress'),)

class Attempt(Base):
    __tablename__='attempts'
    id: Mapped[int]=mapped_column(primary_key=True)
    user_id: Mapped[int]=mapped_column(ForeignKey('users.id'),index=True)
    lesson_id: Mapped[int]=mapped_column(ForeignKey('lessons.id'),index=True)
    score: Mapped[int]=mapped_column(Integer)
    total: Mapped[int]=mapped_column(Integer)
    answers_json: Mapped[str]=mapped_column(Text)
    attempted_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),default=utcnow)

class Assignment(Base):
    __tablename__='assignments'
    id: Mapped[int]=mapped_column(primary_key=True)
    lesson_id: Mapped[int]=mapped_column(ForeignKey('lessons.id'),index=True)
    title: Mapped[str]=mapped_column(String(200))
    description: Mapped[str]=mapped_column(Text,default='')
    submission_type: Mapped[str]=mapped_column(String(30),default='file_or_github')
    max_score: Mapped[int]=mapped_column(Integer,default=100)
    due_date: Mapped[str|None]=mapped_column(String(30),nullable=True)

class Submission(Base):
    __tablename__='submissions'
    id: Mapped[int]=mapped_column(primary_key=True)
    assignment_id: Mapped[int]=mapped_column(ForeignKey('assignments.id'),index=True)
    user_id: Mapped[int]=mapped_column(ForeignKey('users.id'),index=True)
    file_path: Mapped[str|None]=mapped_column(Text,nullable=True)
    original_filename: Mapped[str|None]=mapped_column(String(255),nullable=True)
    github_url: Mapped[str|None]=mapped_column(Text,nullable=True)
    comments: Mapped[str]=mapped_column(Text,default='')
    submitted_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),default=utcnow)
    status: Mapped[str]=mapped_column(String(30),default='submitted')
    score: Mapped[float|None]=mapped_column(Float,nullable=True)
    feedback: Mapped[str]=mapped_column(Text,default='')
    reviewed_at: Mapped[datetime|None]=mapped_column(DateTime(timezone=True),nullable=True)

class XPTransaction(Base):
    __tablename__='xp_transactions'
    id: Mapped[int]=mapped_column(primary_key=True)
    user_id: Mapped[int]=mapped_column(ForeignKey('users.id'),index=True)
    event: Mapped[str]=mapped_column(String(120))
    xp: Mapped[int]=mapped_column(Integer)
    created_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),default=utcnow)

class Badge(Base):
    __tablename__='badges'
    id: Mapped[int]=mapped_column(primary_key=True)
    name: Mapped[str]=mapped_column(String(100),unique=True)
    description: Mapped[str]=mapped_column(Text)
    criteria: Mapped[str]=mapped_column(Text)

class UserBadge(Base):
    __tablename__='user_badges'
    id: Mapped[int]=mapped_column(primary_key=True)
    user_id: Mapped[int]=mapped_column(ForeignKey('users.id'),index=True)
    badge_id: Mapped[int]=mapped_column(ForeignKey('badges.id'),index=True)
    earned_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),default=utcnow)
    __table_args__=(UniqueConstraint('user_id','badge_id',name='uq_user_badge'),)

class Streak(Base):
    __tablename__='streaks'
    user_id: Mapped[int]=mapped_column(ForeignKey('users.id'),primary_key=True)
    current_streak: Mapped[int]=mapped_column(Integer,default=0)
    longest_streak: Mapped[int]=mapped_column(Integer,default=0)
    last_activity_date: Mapped[str|None]=mapped_column(String(20),nullable=True)

class Certificate(Base):
    __tablename__='certificates'
    id: Mapped[int]=mapped_column(primary_key=True)
    user_id: Mapped[int]=mapped_column(ForeignKey('users.id'),index=True)
    course_id: Mapped[int]=mapped_column(ForeignKey('courses.id'),index=True)
    certificate_number: Mapped[str]=mapped_column(String(80),unique=True)
    verification_token: Mapped[str]=mapped_column(String(120),unique=True,index=True)
    issued_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),default=utcnow)
    pdf_path: Mapped[str|None]=mapped_column(Text,nullable=True)
    __table_args__=(UniqueConstraint('user_id','course_id',name='uq_certificate'),)

class SecurityToken(Base):
    __tablename__='security_tokens'
    id: Mapped[int]=mapped_column(primary_key=True)
    user_id: Mapped[int]=mapped_column(ForeignKey('users.id'),index=True)
    token_hash: Mapped[str]=mapped_column(String(128),unique=True,index=True)
    kind: Mapped[str]=mapped_column(String(30),index=True)
    expires_at: Mapped[datetime]=mapped_column(DateTime(timezone=True))
    used: Mapped[bool]=mapped_column(Boolean,default=False)

class AuditLog(Base):
    __tablename__='audit_logs'
    id: Mapped[int]=mapped_column(primary_key=True)
    user_id: Mapped[int|None]=mapped_column(ForeignKey('users.id'),nullable=True,index=True)
    action: Mapped[str]=mapped_column(String(120))
    entity: Mapped[str]=mapped_column(String(80),default='')
    entity_id: Mapped[str]=mapped_column(String(80),default='')
    ip_address: Mapped[str]=mapped_column(String(64),default='')
    created_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),default=utcnow)

class PublicRequest(Base):
    __tablename__='public_requests'
    id: Mapped[int]=mapped_column(primary_key=True)
    name: Mapped[str]=mapped_column(String(120))
    email: Mapped[str]=mapped_column(String(255),index=True)
    request_type: Mapped[str]=mapped_column(String(40),index=True)
    course_id: Mapped[int|None]=mapped_column(ForeignKey('courses.id'),nullable=True)
    message: Mapped[str]=mapped_column(Text,default='')
    status: Mapped[str]=mapped_column(String(20),default='new',index=True)
    created_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),default=utcnow)


