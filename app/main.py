import os, json, random, uuid, shutil, secrets, csv, io
from datetime import datetime, timezone, timedelta
from pathlib import Path
import mimetypes
from fastapi import FastAPI, Depends, HTTPException, UploadFile, File, Form, Request
from fastapi.responses import FileResponse, RedirectResponse, StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text, select, func, desc
from sqlalchemy.orm import Session
from slowapi import Limiter
from slowapi.util import get_remote_address
from slowapi.middleware import SlowAPIMiddleware
from .database import Base, engine, get_db
from .models import *
from .schemas import *
from .auth import *
from .services import add_xp, make_certificate, token_hash, random_token
from .storage import CloudStorageError, delete_file as delete_cloud_file, enabled as cloud_storage_enabled, open_file as open_cloud_file, require_remote_storage, upload_file as upload_cloud_file

if os.getenv('APP_ENV', 'development').lower() == 'production':
    if not os.getenv('DATABASE_URL', '').startswith(('postgresql://', 'postgresql+psycopg://')):
        raise RuntimeError('Production requires a PostgreSQL DATABASE_URL.')
    require_remote_storage()

Base.metadata.create_all(bind=engine)
ASSIGNABLE_ROLES={'learner','admin','content_moderator','assessor','instructor'}
app=FastAPI(title='Swaya',version='2.0.0')
limiter=Limiter(key_func=get_remote_address,default_limits=['120/minute']); app.state.limiter=limiter; app.add_middleware(SlowAPIMiddleware)
app.add_middleware(CORSMiddleware,allow_origins=os.getenv('CORS_ORIGINS','http://localhost:8000').split(','),allow_credentials=True,allow_methods=['*'],allow_headers=['*'])
STATIC=Path(__file__).parent/'static'; STORAGE=Path(os.getenv('STORAGE_ROOT','./uploads')); STORAGE.mkdir(parents=True,exist_ok=True)
MAX_MEDIA_BYTES=min(int(os.getenv('MAX_MEDIA_MB', '50')), 50)*1024*1024
MEDIA_EXTENSIONS={
    '.pdf':('application/pdf','pdf'),
    '.png':('image/png','image'),'.jpg':('image/jpeg','image'),'.jpeg':('image/jpeg','image'),'.gif':('image/gif','image'),'.webp':('image/webp','image'),
    '.mp3':('audio/mpeg','audio'),'.wav':('audio/wav','audio'),'.ogg':('audio/ogg','audio'),'.m4a':('audio/mp4','audio'),
    '.mp4':('video/mp4','video'),'.m4v':('video/x-m4v','video'),'.mov':('video/quicktime','video'),'.webm':('video/webm','video'),'.avi':('video/x-msvideo','video')
}

def media_output(media):
    return {'id':media.id,'course_id':media.course_id,'lesson_id':media.lesson_id,'title':media.title,'filename':media.original_filename,'media_type':media.media_type,'media_kind':media.media_kind,'size_bytes':media.size_bytes,'url':f'/api/media/{media.id}','created_at':media.created_at.isoformat()}

async def store_course_media(course_id,lesson_id,file,title,user,db):
    original=(Path((file.filename or 'upload').replace('\\','/')).name or 'upload')[:255]
    extension=Path(original).suffix.lower()
    file_type=MEDIA_EXTENSIONS.get(extension)
    if not file_type:
        raise HTTPException(400,'Supported files are images, audio, video, and PDF.')
    stored=f'{uuid.uuid4().hex}{extension}'
    media_dir=STORAGE/'course-media'
    media_dir.mkdir(parents=True,exist_ok=True)
    path=media_dir/stored
    object_key=f'course-media/{stored}'
    remote_uploaded=False
    size=0
    try:
        with path.open('wb') as output:
            while True:
                chunk=await file.read(1024*1024)
                if not chunk: break
                size+=len(chunk)
                if size>MAX_MEDIA_BYTES:
                    raise HTTPException(413,'Media file exceeds the 50 MB free-storage limit.')
                output.write(chunk)
        if size==0:
            raise HTTPException(400,'The selected file is empty.')
        if cloud_storage_enabled():
            upload_cloud_file(path,object_key,file_type[0])
            remote_uploaded=True
        asset=CourseMedia(course_id=course_id,lesson_id=lesson_id,title=(title or '').strip()[:255] or Path(original).stem[:255],original_filename=original,stored_filename=stored,media_type=file_type[0],media_kind=file_type[1],size_bytes=size,uploaded_by=user.id)
        db.add(asset)
        db.commit()
        db.refresh(asset)
        path.unlink(missing_ok=True)
        return media_output(asset)
    except CloudStorageError as exc:
        db.rollback()
        path.unlink(missing_ok=True)
        raise HTTPException(502,'Cloud file storage is unavailable.') from exc
    except Exception:
        db.rollback()
        path.unlink(missing_ok=True)
        if remote_uploaded:
            try: delete_cloud_file(object_key)
            except CloudStorageError: pass
        raise
    finally:
        await file.close()


def cloud_file_response(object_key,media_type,filename,cache_control='private, no-store'):
    try:
        upstream=open_cloud_file(object_key)
    except CloudStorageError as exc:
        if exc.status_code==404:
            raise HTTPException(404,'Uploaded file is unavailable') from exc
        raise HTTPException(502,'Cloud file storage is unavailable.') from exc
    def chunks():
        try:
            yield from upstream.iter_content(chunk_size=1024*1024)
        finally:
            upstream.close()
    from urllib.parse import quote
    headers={'Cache-Control':cache_control,'Content-Disposition':f"attachment; filename*=UTF-8''{quote(filename)}"}
    return StreamingResponse(chunks(),media_type=media_type,headers=headers)


def generate_abbreviation(name: str) -> str:
    import re

    words = re.findall(r"[A-Za-z0-9]+", (name or "").upper())

    stop_words = {
        "AND", "OR", "THE", "OF", "TO", "FOR",
        "A", "AN", "IN", "ON", "WITH"
    }

    words = [w for w in words if w not in stop_words]

    if not words:
        return "X"

    # Preserve common short technical names/acronyms
    if len(words) == 1:
        word = words[0]

        if len(word) <= 5:
            return word

        return word[:5]

    return "".join(word[0] for word in words)


def generate_course_code(title: str, db) -> str:
    base = generate_abbreviation(title)
    code = base
    counter = 2

    while db.scalar(select(Course).where(Course.course_code == code)):
        code = f"{base}{counter}"
        counter += 1

    return code


def generate_lesson_code(course: Course, lesson_title: str, day_number: int, db) -> str:
    lesson_abbreviation = generate_abbreviation(lesson_title)

    base = f"{course.course_code}-{lesson_abbreviation}-{day_number:02d}"
    code = base
    counter = 2

    while db.scalar(select(Lesson).where(Lesson.lesson_code == code)):
        code = f"{base}-{counter}"
        counter += 1

    return code

def audit(db,user,action,entity='',entity_id='',request=None): db.add(AuditLog(user_id=getattr(user,'id',None),action=action,entity=entity,entity_id=str(entity_id),ip_address=request.client.host if request else ''))
def seed_data():
    db=next(get_db())
    admin_email=os.getenv('INITIAL_ADMIN_EMAIL','admin@example.com').strip().lower()
    if not admin_email:
        db.close()
        raise RuntimeError('Set INITIAL_ADMIN_EMAIL before starting with an empty database.')
    admin=db.scalar(select(User).where(User.email==admin_email))
    if not admin:
        admin_password=os.getenv('INITIAL_ADMIN_PASSWORD','')
        if not admin_password:
            db.close()
            raise RuntimeError('Set INITIAL_ADMIN_PASSWORD before starting with an empty database.')
        a=User(name=os.getenv('INITIAL_ADMIN_NAME','Swaya Admin'),email=admin_email,password_hash=hash_password(admin_password),role='admin',email_verified=True); db.add(a); db.flush()
        c=Course(course_code=generate_course_code('30-Day Data Engineering',db),title='30-Day Data Engineering',slug='data-engineering-30-day',description='Job-ready Data Engineering learning path',status='published',created_by=a.id); db.add(c); db.flush()
        db.add(InstructorCourse(course_id=c.id,user_id=a.id))
        demo_email=os.getenv('DEMO_LEARNER_EMAIL','').strip().lower()
        demo_password=os.getenv('DEMO_LEARNER_PASSWORD','')
        if os.getenv('APP_ENV','development').lower()!='production' and demo_email and demo_password:
            demo=User(name='Demo Learner',email=demo_email,password_hash=hash_password(demo_password),role='learner',email_verified=True); db.add(demo); db.flush()
            cohort=Cohort(course_id=c.id,name='Cohort 2026-A',start_date='2026-09-01',end_date='2026-09-30'); db.add(cohort); db.flush(); db.add(Enrollment(user_id=demo.id,course_id=c.id,cohort_id=cohort.id))
        for i,title in enumerate(['Python Fundamentals','Conditions & Loops','Lists, Tuples & Sets','Dictionaries','Functions','Files, CSV & JSON','APIs & Week 1 Project','Linux & CLI','Git & GitHub','SQL Fundamentals','SQL Aggregation','SQL Joins','CTEs & Window Functions','Database Design & PostgreSQL','Python + SQL','ETL / ELT Architecture','Data Quality','APIs & Ingestion','Logging & Secrets','Testing Pipelines','Pandas','Data Modeling','dbt','Spark Fundamentals','Spark SQL & Performance','Airflow','Cloud Data Engineering','Data Lake / Lakehouse','Capstone Build','Portfolio & Interview'],1):
            l=Lesson(course_id=c.id,lesson_code=generate_lesson_code(c,title,i,db),day_number=i,title=title,goal=f'Build practical capability in {title}.',content_md=f'# Day {i}: {title}\n\nStudy the lesson, complete the assignment, then pass the 5-question assessment.',objectives_json=json.dumps([f'Understand {title}',f'Apply {title} to a data engineering scenario']),resources_json=json.dumps([{'title':'Python Docs','url':'https://docs.python.org/3/'}] if i<=7 else [])); db.add(l); db.flush()
            for qn in range(1,7):
                opts=[f'Option A for {title}',f'Option B for {title}',f'Option C for {title}',f'Option D for {title}']; correct=(qn+i)%4
                db.add(Question(lesson_id=l.id,question=f'Day {i} question {qn}: Which statement best applies to {title}?',options_json=json.dumps(opts),correct_index=correct,explanation=f'Review the core concepts of {title}.',resource_url='https://docs.python.org/3/' if i<=7 else '',difficulty=['easy','medium','hard'][qn%3],topic=title,tags_json=json.dumps([title.lower().replace(' ','-')])) )
            db.add(Assignment(lesson_id=l.id,title=f'{title} Practical Assignment',description=f'Complete a practical task demonstrating {title}.'))
        for n,d,cg in [('First Step','Complete your first learning day',1),('SQL Explorer','Complete 10 learning days',10),('Data Engineer','Complete all 30 learning days',30),('XP Starter','Earn 500 XP',500)]: db.add(Badge(name=n,description=d,criteria=str(cg)))
        db.commit()
    db.close()
seed_data()



# ==================== PYTHON PRACTICE LAB ====================

import ast
import json
import subprocess
import tempfile
import os
import time

PYTHON_ALLOWED_IMPORTS = {
    "math", "statistics", "datetime", "decimal", "fractions", "random"
}

PYTHON_BLOCKED_CALLS = {
    "eval", "exec", "compile", "open", "breakpoint", "__import__"
}

def validate_python_code(code: str):
    if len(code) > 20000:
        raise HTTPException(400, "Code is too long")

    try:
        tree = ast.parse(code)
    except SyntaxError as e:
        raise HTTPException(400, f"Syntax error: {e}")

    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            names = [a.name.split(".")[0] for a in node.names]
            if any(name not in PYTHON_ALLOWED_IMPORTS for name in names):
                raise HTTPException(400, "Import not allowed")

        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name) and node.func.id in PYTHON_BLOCKED_CALLS:
                raise HTTPException(400, f"Call not allowed: {node.func.id}")

        if isinstance(node, ast.Name) and node.id.startswith("__"):
            raise HTTPException(400, "Dunder names are not allowed")

        if isinstance(node, ast.Attribute) and node.attr.startswith("__"):
            raise HTTPException(400, "Dunder attributes are not allowed")


def ensure_python_lab_tables(db):
    db.execute(text("""
        CREATE TABLE IF NOT EXISTS python_exercises (
            id SERIAL PRIMARY KEY,
            lesson_id INTEGER NOT NULL,
            title VARCHAR(200) NOT NULL,
            instructions TEXT NOT NULL DEFAULT '',
            starter_code TEXT NOT NULL DEFAULT '',
            expected_output TEXT NOT NULL DEFAULT '',
            test_cases_json TEXT NOT NULL DEFAULT '[]',
            difficulty VARCHAR(30) NOT NULL DEFAULT 'beginner',
            sort_order INTEGER NOT NULL DEFAULT 0,
            active BOOLEAN NOT NULL DEFAULT TRUE,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """))

    db.execute(text("""
        CREATE TABLE IF NOT EXISTS python_submissions (
            id BIGSERIAL PRIMARY KEY,
            exercise_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            code TEXT NOT NULL,
            stdin TEXT NOT NULL DEFAULT '',
            output TEXT NOT NULL DEFAULT '',
            passed BOOLEAN NOT NULL DEFAULT FALSE,
            score INTEGER NOT NULL DEFAULT 0,
            execution_ms INTEGER NOT NULL DEFAULT 0,
            error TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """))

    db.execute(text("""
        CREATE INDEX IF NOT EXISTS ix_python_exercises_lesson
        ON python_exercises(lesson_id)
    """))

    db.execute(text("""
        CREATE INDEX IF NOT EXISTS ix_python_submissions_user
        ON python_submissions(user_id)
    """))

    db.commit()


def seed_python_exercises(db, lesson_id):
    count = db.execute(
        text("SELECT COUNT(*) FROM python_exercises WHERE lesson_id=:id"),
        {"id": lesson_id}
    ).scalar()

    if count:
        return

    exercises = [
        (
            "Print your first message",
            "Print the text exactly as shown in the expected output.",
            'print("Hello, Data Engineer!")',
            "Hello, Data Engineer!",
            "beginner"
        ),
        (
            "Variables",
            "Create a variable named name and print it.",
            'name = "Data Engineer"\nprint(name)',
            "Data Engineer",
            "beginner"
        ),
        (
            "Numbers",
            "Calculate 10 + 20 and print the result.",
            "a = 10\nb = 20\nprint(a + b)",
            "30",
            "beginner"
        ),
        (
            "Conditionals",
            "Print Passed when score is 50 or greater.",
            "score = 75\n\nif score >= 50:\n    print(\"Passed\")\nelse:\n    print(\"Failed\")",
            "Passed",
            "beginner"
        ),
        (
            "Loops",
            "Print the numbers 1 through 5 using a loop.",
            "for i in range(1, 6):\n    print(i)",
            "1\n2\n3\n4\n5",
            "beginner"
        )
    ]

    for i, (title, instructions, starter, expected, difficulty) in enumerate(exercises):
        db.execute(text("""
            INSERT INTO python_exercises
            (lesson_id,title,instructions,starter_code,expected_output,
             test_cases_json,difficulty,sort_order)
            VALUES
            (:lesson_id,:title,:instructions,:starter,:expected,'[]',
             :difficulty,:sort_order)
        """), {
            "lesson_id": lesson_id,
            "title": title,
            "instructions": instructions,
            "starter": starter,
            "expected": expected,
            "difficulty": difficulty,
            "sort_order": i
        })

    db.commit()


@app.get("/api/lessons/{lesson_id}/python-exercises")
def python_exercises(
    lesson_id: int,
    user=Depends(current_user),
    db: Session = Depends(get_db)
):
    ensure_python_lab_tables(db)

    lesson_obj = db.get(Lesson, lesson_id)
    if not lesson_obj:
        raise HTTPException(404, "Lesson not found")

    seed_python_exercises(db, lesson_id)

    rows = db.execute(text("""
        SELECT id,title,instructions,starter_code,expected_output,
               difficulty,sort_order
        FROM python_exercises
        WHERE lesson_id=:lesson_id AND active=true
        ORDER BY sort_order,id
    """), {"lesson_id": lesson_id}).mappings().all()

    return [dict(r) for r in rows]


def execute_python(code, stdin=""):
    validate_python_code(code)

    if len(stdin or "") > 10000:
        raise HTTPException(400, "Input is too long")

    fd, path = tempfile.mkstemp(suffix=".py")
    os.close(fd)

    try:
        Path(path).write_text(code, encoding="utf-8")

        start = time.perf_counter()

        try:
            result = subprocess.run(
                ["python", "-I", path],
                input=stdin or "",
                text=True,
                capture_output=True,
                timeout=3
            )
        except subprocess.TimeoutExpired:
            return {
                "output": "",
                "error": "Execution timed out after 3 seconds.",
                "execution_ms": 3000
            }

        elapsed = int((time.perf_counter() - start) * 1000)

        output = (result.stdout or "")[:20000]
        error = (result.stderr or "")[:20000]

        return {
            "output": output,
            "error": error,
            "execution_ms": elapsed
        }

    finally:
        try:
            os.remove(path)
        except OSError:
            pass


@app.post("/api/python/run")
def run_python(
    x: dict,
    user=Depends(current_user),
    db: Session = Depends(get_db)
):
    code = x.get("code", "")
    stdin = x.get("stdin", "")

    if not isinstance(code, str):
        raise HTTPException(400, "code must be text")

    if not isinstance(stdin, str):
        raise HTTPException(400, "stdin must be text")

    return execute_python(code, stdin)


@app.post("/api/python/exercises/{exercise_id}/submit")
def submit_python(
    exercise_id: int,
    x: dict,
    user=Depends(current_user),
    db: Session = Depends(get_db)
):
    ensure_python_lab_tables(db)

    row = db.execute(
        text("SELECT * FROM python_exercises WHERE id=:id AND active=true"),
        {"id": exercise_id}
    ).mappings().first()

    if not row:
        raise HTTPException(404, "Exercise not found")

    code = x.get("code", "")
    stdin = x.get("stdin", "")

    result = execute_python(code, stdin)

    actual = (result.get("output") or "").strip()
    expected = (row["expected_output"] or "").strip()

    passed = not result.get("error") and actual == expected
    score = 100 if passed else 0

    db.execute(text("""
        INSERT INTO python_submissions
        (exercise_id,user_id,code,stdin,output,passed,score,execution_ms,error)
        VALUES
        (:exercise_id,:user_id,:code,:stdin,:output,:passed,:score,:execution_ms,:error)
    """), {
        "exercise_id": exercise_id,
        "user_id": user.id,
        "code": code,
        "stdin": stdin,
        "output": result.get("output", ""),
        "passed": passed,
        "score": score,
        "execution_ms": result.get("execution_ms", 0),
        "error": result.get("error")
    })

    db.commit()

    return {
        "passed": passed,
        "score": score,
        "output": result.get("output", ""),
        "error": result.get("error", ""),
        "execution_ms": result.get("execution_ms", 0)
    }


@app.get("/api/python/my-progress")
def python_progress(
    user=Depends(current_user),
    db: Session = Depends(get_db)
):
    ensure_python_lab_tables(db)

    rows = db.execute(text("""
        SELECT e.id,e.lesson_id,e.title,e.difficulty,
               COALESCE(s.passed,false) AS passed,
               COALESCE(s.score,0) AS score
        FROM python_exercises e
        LEFT JOIN LATERAL (
            SELECT passed,score
            FROM python_submissions
            WHERE exercise_id=e.id AND user_id=:user_id
            ORDER BY created_at DESC
            LIMIT 1
        ) s ON true
        WHERE e.active=true
        ORDER BY e.lesson_id,e.sort_order,e.id
    """), {"user_id": user.id}).mappings().all()

    return [dict(r) for r in rows]

@app.post('/api/auth/register')
@limiter.limit('10/minute')
def register(request:Request,x:RegisterIn,db:Session=Depends(get_db)):
    email=x.email.lower()
    if db.scalar(select(User).where(User.email==email)): raise HTTPException(409,'Email already registered')
    u=User(name=x.name,email=email,password_hash=hash_password(x.password),role='learner',email_verified=True); db.add(u); db.flush()
    course=db.scalar(select(Course).where(Course.slug=='data-engineering-30-day')); cohort=db.scalar(select(Cohort).where(Cohort.course_id==course.id).order_by(Cohort.id))
    db.add(Enrollment(user_id=u.id,course_id=course.id,cohort_id=cohort.id if cohort else None)); audit(db,u,'register','user',u.id,request); db.commit()
    return tokens(u)

def tokens(u): return {'access_token':make_token(u),'refresh_token':make_token(u,'refresh'),'token_type':'bearer','user':{'id':u.id,'name':u.name,'email':u.email,'role':u.role}}

@app.post('/api/auth/login')
@limiter.limit('10/minute')
def login(request:Request,x:LoginIn,db:Session=Depends(get_db)):
    u=db.scalar(select(User).where(User.email==x.email.lower()))
    if not u or not verify_password(x.password,u.password_hash) or not u.active: raise HTTPException(401,'Invalid email or password')
    audit(db,u,'login','user',u.id,request); db.commit(); return tokens(u)

@app.post('/api/auth/refresh')
def refresh(x:RefreshIn,db:Session=Depends(get_db)):
    p=decode(x.refresh_token,'refresh'); u=db.get(User,int(p['sub']));
    if not u or not u.active: raise HTTPException(401,'Account unavailable')
    return {'access_token':make_token(u),'token_type':'bearer'}

@app.get('/api/me')
def me(user=Depends(current_user)): return {'id':user.id,'name':user.name,'email':user.email,'role':user.role,'email_verified':user.email_verified,'mfa_enabled':user.mfa_enabled}

@app.get('/api/courses')
def courses(user=Depends(current_user),db:Session=Depends(get_db)):
    if user.role == 'learner':
        cs=db.scalars(select(Course).join(Enrollment,Enrollment.course_id==Course.id).where(Enrollment.user_id==user.id,Enrollment.status=='active',Course.status=='published').order_by(Course.id)).all()
    else:
        cs=db.scalars(select(Course).where(Course.status=='published').order_by(Course.id)).all()
    return [{'id':c.id,'course_code':c.course_code,'title':c.title,'slug':c.slug,'description':c.description} for c in cs]

@app.get('/api/courses/{course_id}/media')
def course_media(course_id:int,user=Depends(current_user),db:Session=Depends(get_db)):
    course=db.get(Course,course_id)
    if not course: raise HTTPException(404,'Course not found')
    if user.role=='learner':
        enrollment=db.scalar(select(Enrollment).where(Enrollment.user_id==user.id,Enrollment.course_id==course_id,Enrollment.status=='active'))
        if not enrollment or course.status!='published': raise HTTPException(403,'You are not enrolled in this course')
    rows=db.scalars(select(CourseMedia).where(CourseMedia.course_id==course_id,CourseMedia.lesson_id.is_(None)).order_by(CourseMedia.id)).all()
    return [media_output(row) for row in rows]

@app.get('/api/courses/{course_id}/lessons')
def lessons(course_id:int,user=Depends(current_user),db:Session=Depends(get_db)):
    course=db.get(Course,course_id)
    if not course: raise HTTPException(404,'Course not found')
    if user.role=='learner':
        enrollment=db.scalar(select(Enrollment).where(Enrollment.user_id==user.id,Enrollment.course_id==course_id,Enrollment.status=='active'))
        if not enrollment or course.status!='published': raise HTTPException(403,'You are not enrolled in this course')
    ls=db.scalars(select(Lesson).where(Lesson.course_id==course_id).order_by(Lesson.day_number)).all(); out=[]
    for l in ls:
        p=db.scalar(select(Progress).where(Progress.user_id==user.id,Progress.lesson_id==l.id)); prev=db.scalar(select(Progress).join(Lesson,Progress.lesson_id==Lesson.id).where(Progress.user_id==user.id,Lesson.course_id==course_id,Lesson.day_number==l.day_number-1))
        out.append({'id':l.id,'day_number':l.day_number,'title':l.title,'completed':bool(p and p.completed),'learning_complete':bool(p and p.learning_complete),'assessment_complete':bool(p and p.assessment_complete),'best_score':p.best_score if p else 0,'attempts':p.attempts if p else 0,'unlocked':l.day_number==1 or bool(prev and prev.completed)})
    return out

@app.get('/api/lessons/{lesson_id}')
def lesson(lesson_id:int,user=Depends(current_user),db:Session=Depends(get_db)):
    l=db.get(Lesson,lesson_id)
    if not l: raise HTTPException(404,'Lesson not found')
    course=db.get(Course,l.course_id)
    if user.role=='learner':
        enrollment=db.scalar(select(Enrollment).where(Enrollment.user_id==user.id,Enrollment.course_id==l.course_id,Enrollment.status=='active'))
        if not enrollment or not course or course.status!='published': raise HTTPException(403,'You are not enrolled in this course')
    p=db.scalar(select(Progress).where(Progress.user_id==user.id,Progress.lesson_id==lesson_id));
    if user.role=='learner' and l.day_number>1:
        prev=db.scalar(select(Progress).join(Lesson,Progress.lesson_id==Lesson.id).where(Progress.user_id==user.id,Lesson.course_id==l.course_id,Lesson.day_number==l.day_number-1))
        if not prev or not prev.completed: raise HTTPException(423,'Lesson locked')
    a=db.scalars(select(Assignment).where(Assignment.lesson_id==lesson_id)).all()
    media=db.scalars(select(CourseMedia).where(CourseMedia.lesson_id==lesson_id).order_by(CourseMedia.id)).all()
    tasks=[{'index':i,'text':t,'done':False} for i,t in enumerate(['Read the lesson','Complete the practical assignment','Pass the assessment'],1)]
    return {'id':l.id,'course_id':l.course_id,'day_number':l.day_number,'title':l.title,'goal':l.goal,'content_md':l.content_md,'content_html':l.content_html,'content_css':l.content_css,'objectives':json.loads(l.objectives_json),'resources':json.loads(l.resources_json),'media':[media_output(x) for x in media],'learning_complete':bool(p and p.learning_complete),'completed':bool(p and p.completed),'best_score':p.best_score if p else 0,'attempts':p.attempts if p else 0,'assignments':[{'id':x.id,'title':x.title,'description':x.description,'max_score':x.max_score,'due_date':x.due_date} for x in a],'tasks':tasks}

@app.get('/api/media/{media_id}')
def get_course_media_file(media_id:int,user=Depends(current_user),db:Session=Depends(get_db)):
    media=db.get(CourseMedia,media_id)
    if not media: raise HTTPException(404,'Media file not found')
    if user.role=='learner':
        course=db.get(Course,media.course_id)
        enrollment=db.scalar(select(Enrollment).where(Enrollment.user_id==user.id,Enrollment.course_id==media.course_id,Enrollment.status=='active'))
        if not course or course.status!='published' or not enrollment: raise HTTPException(403,'You are not enrolled in this course')
        if media.lesson_id:
            media_lesson=db.get(Lesson,media.lesson_id)
            if media_lesson and media_lesson.day_number>1:
                previous=db.scalar(select(Progress).join(Lesson,Progress.lesson_id==Lesson.id).where(Progress.user_id==user.id,Lesson.course_id==media.course_id,Lesson.day_number==media_lesson.day_number-1))
                if not previous or not previous.completed: raise HTTPException(423,'Lesson locked')
    if cloud_storage_enabled():
        return cloud_file_response(f'course-media/{media.stored_filename}',media.media_type,media.original_filename)
    path=STORAGE/'course-media'/media.stored_filename
    if not path.is_file(): raise HTTPException(404,'Media file is unavailable')
    return FileResponse(path,media_type=media.media_type,filename=media.original_filename,headers={'Cache-Control':'private, no-store'})

def get_progress(db,user_id,lesson_id):
    p=db.scalar(select(Progress).where(Progress.user_id==user_id,Progress.lesson_id==lesson_id))
    if not p: p=Progress(user_id=user_id,lesson_id=lesson_id); db.add(p); db.flush()
    return p

@app.post('/api/lessons/{lesson_id}/learning-complete')
def learning_complete(lesson_id:int,request:Request,user=Depends(current_user),db:Session=Depends(get_db)):
    l=db.get(Lesson,lesson_id); p=get_progress(db,user.id,lesson_id); p.learning_complete=True; p.last_activity=datetime.now(timezone.utc); add_xp(db,user.id,'lesson_complete',50); audit(db,user,'learning_complete','lesson',lesson_id,request); db.commit(); return {'ok':True}

@app.get('/api/lessons/{lesson_id}/quiz')
def quiz(lesson_id:int,user=Depends(current_user),db:Session=Depends(get_db)):
    p=get_progress(db,user.id,lesson_id)
    if not p.learning_complete: raise HTTPException(423,'Complete learning first')
    qs=db.scalars(select(Question).where(Question.lesson_id==lesson_id,Question.active==True)).all(); chosen=random.sample(qs,min(5,len(qs))); random.shuffle(chosen)
    return {'questions':[{'id':q.id,'question':q.question,'options':json.loads(q.options_json),'difficulty':q.difficulty,'topic':q.topic} for q in chosen]}

@app.post('/api/lessons/{lesson_id}/quiz')
def quiz_submit(lesson_id:int,x:QuizSubmitIn,request:Request,user=Depends(current_user),db:Session=Depends(get_db)):
    p=get_progress(db,user.id,lesson_id); ids=[int(k) for k in x.answers]; qs=db.scalars(select(Question).where(Question.lesson_id==lesson_id,Question.id.in_(ids),Question.active==True)).all(); by={q.id:q for q in qs}
    if len(x.answers)!=5 or len(by)!=5: raise HTTPException(400,'A valid quiz requires exactly 5 questions from this lesson')
    score=sum(1 for k,v in x.answers.items() if by[int(k)].correct_index==v); feedback=[]
    for k,v in x.answers.items():
        q=by[int(k)]
        if q.correct_index!=v: feedback.append({'question_id':q.id,'correct_answer':json.loads(q.options_json)[q.correct_index],'explanation':q.explanation,'resource':q.resource_url})
    p.attempts+=1; p.best_score=max(p.best_score,score); p.last_activity=datetime.now(timezone.utc); passed=score==5; p.assessment_complete=p.assessment_complete or passed; p.completed=p.learning_complete and p.assessment_complete
    db.add(Attempt(user_id=user.id,lesson_id=lesson_id,score=score,total=5,answers_json=json.dumps(x.answers)))
    if passed: add_xp(db,user.id,'quiz_pass',100)
    audit(db,user,'quiz_submit','lesson',lesson_id,request); db.commit(); return {'score':score,'total':5,'passed':passed,'feedback':feedback}

@app.post('/api/assignments/{assignment_id}/submit')
async def submit_assignment(assignment_id:int,user=Depends(current_user),db:Session=Depends(get_db),file:UploadFile|None=File(None),github_url:str|None=Form(None),comments:str=Form('')):
    a=db.get(Assignment,assignment_id)
    if not a: raise HTTPException(404,'Assignment not found')
    path=None; original=None; object_key=None; remote_uploaded=False
    if file:
        allowed={'.py','.sql','.zip','.txt','.md','.csv','.json'}; ext=Path(file.filename or '').suffix.lower()
        if ext not in allowed: raise HTTPException(400,'Unsupported file type')
        if file.size and file.size>10*1024*1024: raise HTTPException(413,'File too large')
        dest=STORAGE/'assignments'/str(user.id); dest.mkdir(parents=True,exist_ok=True); name=f'{uuid.uuid4().hex}{ext}'; path=str(dest/name); original=file.filename
        try:
            with open(path,'wb') as out:
                shutil.copyfileobj(file.file,out)
            if cloud_storage_enabled():
                object_key=f'assignments/{user.id}/{name}'
                upload_cloud_file(path,object_key,mimetypes.guess_type(original)[0] or 'application/octet-stream')
                remote_uploaded=True
                path=f'supabase://{object_key}'
        except CloudStorageError as exc:
            Path(path).unlink(missing_ok=True)
            raise HTTPException(502,'Cloud file storage is unavailable.') from exc
        finally:
            await file.close()
        if remote_uploaded:
            local_path=dest/name
            local_path.unlink(missing_ok=True)
    if not path and not github_url: raise HTTPException(400,'Provide a file or GitHub URL')
    s=Submission(assignment_id=assignment_id,user_id=user.id,file_path=path,original_filename=original,github_url=github_url,comments=comments); db.add(s); add_xp(db,user.id,'assignment_submit',150); audit(db,user,'assignment_submit','assignment',assignment_id); db.commit(); return {'id':s.id,'status':s.status}

@app.get('/api/instructor/dashboard')
def instructor_dashboard(user=Depends(require_roles('admin','instructor','assessor')),db:Session=Depends(get_db)):
    course_ids=db.scalars(select(InstructorCourse.course_id).where(InstructorCourse.user_id==user.id)).all() if user.role!='admin' else db.scalars(select(Course.id)).all()
    total_learners=db.scalar(select(func.count(func.distinct(Enrollment.user_id))).where(Enrollment.course_id.in_(course_ids))) if course_ids else 0
    lesson_stats=[]
    for l in db.scalars(select(Lesson).where(Lesson.course_id.in_(course_ids)).order_by(Lesson.day_number)).all():
        enrolled=db.scalar(select(func.count(func.distinct(Enrollment.user_id))).where(Enrollment.course_id==l.course_id)) or 0
        completed=db.scalar(select(func.count()).select_from(Progress).where(Progress.lesson_id==l.id,Progress.completed==True)) or 0
        lesson_stats.append({'day':l.day_number,'title':l.title,'completion_rate':round(completed/enrolled*100) if enrolled else 0})
    avg=db.scalar(select(func.avg(Attempt.score*100.0/func.nullif(Attempt.total,0))).join(Lesson,Attempt.lesson_id==Lesson.id).where(Lesson.course_id.in_(course_ids))) if course_ids else 0
    # At-risk: no activity in 3 days or low completion.
    cutoff=datetime.now(timezone.utc)-timedelta(days=3); learners=db.scalars(select(User).join(Enrollment,Enrollment.user_id==User.id).where(Enrollment.course_id.in_(course_ids),User.role=='learner').distinct()).all() if course_ids else []
    at=[]
    for u in learners:
        last=db.scalar(select(func.max(Progress.last_activity)).where(Progress.user_id==u.id)); comp=db.scalar(select(func.count()).select_from(Progress).join(Lesson,Progress.lesson_id==Lesson.id).where(Progress.user_id==u.id,Lesson.course_id.in_(course_ids),Progress.completed==True)) or 0
        if not last or last<cutoff or comp<3: at.append({'id':u.id,'name':u.name,'email':u.email,'completed_days':comp,'last_activity':last.isoformat() if last else None})
    return {'learners':total_learners,'average_assessment_score':round(float(avg or 0),1),'day_completion':lesson_stats,'at_risk':at}

@app.post('/api/admin/cohorts')
def create_cohort(x:CohortIn,user=Depends(require_roles('admin')),db:Session=Depends(get_db)):
    if not db.get(Course,x.course_id): raise HTTPException(404,'Course not found')
    c=Cohort(**x.model_dump()); db.add(c); db.commit(); db.refresh(c); return {'id':c.id,'name':c.name}

@app.get('/api/admin/courses')
def admin_courses(user=Depends(require_roles('admin','content_moderator','instructor','assessor')),db:Session=Depends(get_db)):
    cs=db.scalars(select(Course).order_by(Course.id)).all()
    return [
        {
            'id':c.id,
'course_code':c.course_code,
'title':c.title,
            'slug':c.slug,
            'description':c.description,
            'status':c.status
        }
        for c in cs
    ]
@app.post('/api/admin/courses')
def create_course(
    x:CourseIn,
    user=Depends(require_roles('admin')),
    db:Session=Depends(get_db)
):
    data=x.model_dump()

    course_code=generate_course_code(x.title,db)

    c=Course(
        **data,
        course_code=course_code,
        created_by=user.id
    )

    db.add(c)
    db.commit()
    db.refresh(c)

    return {
        'id':c.id,
        'course_code':c.course_code,
        'title':c.title,
        'slug':c.slug,
        'status':c.status
    }

@app.put('/api/admin/courses/{course_id}')
def update_course(course_id:int,x:CourseIn,user=Depends(require_roles('admin','content_moderator')),db:Session=Depends(get_db)):
    c=db.get(Course,course_id)
    if not c: raise HTTPException(404,'Course not found')
    for k,v in x.model_dump().items(): setattr(c,k,v)
    db.commit(); return {'ok':True}

@app.post('/api/admin/lessons')
def create_lesson(
    x:LessonIn,
    course_id:int,
    user=Depends(require_roles('admin','content_moderator','instructor')),
    db:Session=Depends(get_db)
):
    course=db.get(Course,course_id)

    if not course:
        raise HTTPException(404,'Course not found')

    if db.scalar(select(Lesson).where(Lesson.course_id==course_id,Lesson.day_number==x.day_number)):
        raise HTTPException(409,f'Course already has a lesson for day {x.day_number}. Choose another day number.')

    data=x.model_dump()

    lesson_code=generate_lesson_code(
        course,
        x.title,
        x.day_number,
        db
    )

    lesson=Lesson(
        course_id=course_id,
        lesson_code=lesson_code,
        objectives_json=json.dumps(data.pop('objectives',[])),
        resources_json=json.dumps(data.pop('resources',[])),
        **data
    )

    db.add(lesson)
    db.commit()
    db.refresh(lesson)

    return {
        'id':lesson.id,
        'lesson_code':lesson.lesson_code,
        'course_id':course.id,
        'course_code':course.course_code,
        'day_number':lesson.day_number,
        'title':lesson.title
    }

@app.post('/api/admin/courses/{course_id}/lessons/bulk')
async def bulk_create_lessons(
    course_id:int,
    file:UploadFile=File(...),
    user=Depends(require_roles('admin','content_moderator','instructor')),
    db:Session=Depends(get_db)
):
    course=db.get(Course,course_id)
    if not course:
        raise HTTPException(404,'Course not found')
    if Path(file.filename or '').suffix.lower() != '.csv':
        raise HTTPException(400,'Upload a CSV file. Excel workbooks should be saved as CSV UTF-8 first.')
    raw=await file.read(2*1024*1024+1)
    await file.close()
    if len(raw)>2*1024*1024:
        raise HTTPException(413,'CSV file is too large (maximum 2 MB).')
    try:
        text_data=raw.decode('utf-8-sig')
        reader=csv.DictReader(io.StringIO(text_data))
    except (UnicodeDecodeError,csv.Error) as exc:
        raise HTTPException(400,'Could not read the CSV. Save it as UTF-8 CSV and try again.') from exc
    required={'day_number','title'}
    headers={h.strip().lower() for h in (reader.fieldnames or []) if h}
    if not required.issubset(headers):
        raise HTTPException(400,'CSV needs day_number and title columns. Download the template for all supported columns.')
    rows=[]
    errors=[]
    seen=set()
    allowed={'day_number','title','goal','content_md','content_html','content_css','estimated_minutes','status'}
    for line,row in enumerate(reader,start=2):
        if line>367:
            errors.append('CSV may contain at most 365 lessons.')
            break
        normalized={(k or '').strip().lower():(v or '').strip() for k,v in row.items() if k}
        if not any(normalized.values()):
            continue
        try:
            day=int(normalized.get('day_number',''))
            if not 1<=day<=365: raise ValueError
        except ValueError:
            errors.append(f'Row {line}: day_number must be a whole number from 1 to 365.')
            continue
        title=normalized.get('title','')
        if not title:
            errors.append(f'Row {line}: title is required.')
            continue
        if len(title)>200:
            errors.append(f'Row {line}: title must be 200 characters or fewer.')
            continue
        if day in seen:
            errors.append(f'Row {line}: day {day} appears more than once in this CSV.')
            continue
        seen.add(day)
        try:
            minutes=int(normalized.get('estimated_minutes') or 60)
            if not 1<=minutes<=1440: raise ValueError
        except ValueError:
            errors.append(f'Row {line}: estimated_minutes must be from 1 to 1440.')
            continue
        status=normalized.get('status') or 'published'
        if status not in {'draft','published'}:
            errors.append(f'Row {line}: status must be draft or published.')
            continue
        lesson_data={key:normalized.get(key,'') for key in allowed if key not in {'day_number','title','estimated_minutes','status'}}
        rows.append({'day_number':day,'title':title,'estimated_minutes':minutes,'status':status,**lesson_data})
    if not rows and not errors:
        errors.append('CSV contains no lesson rows.')
    existing=set(db.scalars(select(Lesson.day_number).where(Lesson.course_id==course_id,Lesson.day_number.in_(seen))).all()) if seen else set()
    for day in sorted(existing):
        errors.append(f'Course already has a lesson for day {day}. Remove that row or choose another day number.')
    if errors:
        raise HTTPException(400,{'message':'No lessons were imported. Fix the following issues and upload again.','errors':errors[:50]})
    lessons=[]
    for row in rows:
        lesson=Lesson(course_id=course_id,lesson_code=generate_lesson_code(course,row['title'],row['day_number'],db),objectives_json='[]',resources_json='[]',**row)
        db.add(lesson)
        lessons.append(lesson)
    try:
        db.commit()
    except Exception:
        db.rollback()
        raise HTTPException(409,'Lessons could not be imported because another change used one of these day numbers. Refresh and retry.')
    return {'created':len(lessons),'course_id':course_id,'days':[l.day_number for l in lessons]}

@app.put('/api/admin/lessons/{lesson_id}')
def update_lesson(lesson_id:int,x:LessonIn,course_id:int,user=Depends(require_roles('admin','content_moderator','instructor')),db:Session=Depends(get_db)):
    l=db.get(Lesson,lesson_id)
    if not l: raise HTTPException(404,'Lesson not found')
    if not db.get(Course,course_id): raise HTTPException(404,'Course not found')
    duplicate=db.scalar(select(Lesson).where(Lesson.course_id==course_id,Lesson.day_number==x.day_number,Lesson.id!=lesson_id))
    if duplicate: raise HTTPException(409,f'Course already has a lesson for day {x.day_number}. Choose another day number.')
    data=x.model_dump()
    l.course_id=course_id
    l.objectives_json=json.dumps(data.pop('objectives',[]))
    l.resources_json=json.dumps(data.pop('resources',[]))
    for k,v in data.items(): setattr(l,k,v)
    db.commit(); return {'ok':True}

@app.post('/api/admin/courses/{course_id}/media')
async def upload_course_level_media(course_id:int,file:UploadFile=File(...),title:str=Form(''),user=Depends(require_roles('admin','content_moderator','instructor')),db:Session=Depends(get_db)):
    if not db.get(Course,course_id): raise HTTPException(404,'Course not found')
    return await store_course_media(course_id,None,file,title,user,db)

@app.post('/api/admin/lessons/{lesson_id}/media')
async def upload_lesson_media(lesson_id:int,file:UploadFile=File(...),title:str=Form(''),user=Depends(require_roles('admin','content_moderator','instructor')),db:Session=Depends(get_db)):
    lesson=db.get(Lesson,lesson_id)
    if not lesson: raise HTTPException(404,'Lesson not found')
    return await store_course_media(lesson.course_id,lesson.id,file,title,user,db)

@app.get('/api/admin/questions')
def admin_questions(user=Depends(require_roles('admin','instructor','content_moderator','assessor')),db:Session=Depends(get_db)):
    qs=db.scalars(select(Question).order_by(desc(Question.id)).limit(500)).all(); return [{'id':q.id,'lesson_id':q.lesson_id,'question':q.question,'difficulty':q.difficulty,'topic':q.topic,'tags':json.loads(q.tags_json),'active':q.active} for q in qs]

@app.post('/api/admin/questions')
def create_question(x:QuestionIn,user=Depends(require_roles('admin','instructor','content_moderator')),db:Session=Depends(get_db)):
    q=Question(options_json=json.dumps(x.options),tags_json=json.dumps(x.tags),**{k:v for k,v in x.model_dump().items() if k not in ('options','tags')}); db.add(q); db.commit(); db.refresh(q); return {'id':q.id}

@app.put('/api/admin/questions/{question_id}')
def update_question(question_id:int,x:QuestionIn,user=Depends(require_roles('admin','instructor','content_moderator')),db:Session=Depends(get_db)):
    q=db.get(Question,question_id)
    if not q: raise HTTPException(404,'Question not found')
    for k,v in x.model_dump().items(): setattr(q,k,json.dumps(v) if k in ('options','tags') else v)
    db.commit(); return {'ok':True}

@app.get('/api/instructor/submissions')
def submissions(user=Depends(require_roles('admin','instructor','assessor')),db:Session=Depends(get_db)):
    rows=db.execute(select(Submission,User,Assignment).join(User,User.id==Submission.user_id).join(Assignment,Assignment.id==Submission.assignment_id).order_by(desc(Submission.submitted_at)).limit(300)).all(); return [{'id':s.id,'assignment_id':s.assignment_id,'lesson_id':a.lesson_id,'user_id':s.user_id,'user_name':u.name,'user_email':u.email,'assignment_title':a.title,'filename':s.original_filename,'github_url':s.github_url,'comments':s.comments,'status':s.status,'score':s.score,'feedback':s.feedback,'submitted_at':s.submitted_at.isoformat()} for s,u,a in rows]

@app.get('/api/instructor/submissions/{submission_id}/file')
def get_submission_file(submission_id:int,user=Depends(require_roles('admin','instructor','assessor')),db:Session=Depends(get_db)):
    s=db.get(Submission,submission_id)
    if not s: raise HTTPException(404,'Submission not found')
    if not s.file_path: raise HTTPException(404,'No uploaded file for this submission')
    media_type=mimetypes.guess_type(s.original_filename or Path(s.file_path).name)[0] or 'application/octet-stream'
    if s.file_path.startswith('supabase://'):
        return cloud_file_response(s.file_path.removeprefix('supabase://'),media_type,s.original_filename or 'submission')
    file_path=Path(s.file_path)
    if not file_path.exists(): raise HTTPException(404,'Uploaded file unavailable')
    return FileResponse(file_path,media_type=media_type,filename=s.original_filename or file_path.name)

@app.patch('/api/instructor/submissions/{submission_id}')
def review_submission(submission_id:int,x:ReviewIn,user=Depends(require_roles('admin','instructor','assessor')),db:Session=Depends(get_db)):
    s=db.get(Submission,submission_id)
    if not s: raise HTTPException(404,'Submission not found')
    s.score=x.score; s.feedback=x.feedback; s.status='reviewed'; s.reviewed_at=datetime.now(timezone.utc); add_xp(db,s.user_id,'assignment_reviewed',int(max(0,min(100,x.score)))); db.commit(); return {'ok':True}

@app.get('/api/leaderboard')
def leaderboard(user=Depends(current_user),db:Session=Depends(get_db)):
    rows=db.execute(select(User.id,User.name,func.coalesce(func.sum(XPTransaction.xp),0).label('xp')).join(XPTransaction,XPTransaction.user_id==User.id,isouter=True).where(User.role=='learner').group_by(User.id,User.name).order_by(desc('xp')).limit(20)).all(); return [{'rank':i+1,'user_id':r.id,'name':r.name,'xp':int(r.xp)} for i,r in enumerate(rows)]

@app.get('/api/gamification')
def gamification(user=Depends(current_user),db:Session=Depends(get_db)):
    xp=int(db.scalar(select(func.coalesce(func.sum(XPTransaction.xp),0)).where(XPTransaction.user_id==user.id)) or 0); st=db.get(Streak,user.id); badges=db.execute(select(Badge.name,Badge.description).join(UserBadge,UserBadge.badge_id==Badge.id).where(UserBadge.user_id==user.id)).all(); return {'xp':xp,'level':xp//1000+1,'streak':st.current_streak if st else 0,'longest_streak':st.longest_streak if st else 0,'badges':[{'name':b.name,'description':b.description} for b in badges]}

@app.get('/api/certificates/me')
def my_certificate(user=Depends(current_user),db:Session=Depends(get_db)):
    c=db.scalar(select(Certificate).where(Certificate.user_id==user.id).order_by(desc(Certificate.id)))
    if not c: return {'certificate':None}
    return {'certificate':{'id':c.certificate_number,'issued_at':c.issued_at.isoformat(),'verify_url':f"{(os.getenv('APP_BASE_URL') or os.getenv('RENDER_EXTERNAL_URL','http://localhost:8000')).rstrip('/')}/verify/{c.verification_token}"}}

@app.post('/api/certificates/generate/{course_id}')
def generate_certificate(course_id:int,user=Depends(current_user),db:Session=Depends(get_db)):
    total=db.scalar(select(func.count()).select_from(Lesson).where(Lesson.course_id==course_id)); done=db.scalar(select(func.count()).select_from(Progress).join(Lesson,Progress.lesson_id==Lesson.id).where(Progress.user_id==user.id,Lesson.course_id==course_id,Progress.completed==True));
    if not total or done<total: raise HTTPException(403,'Complete all lessons first')
    c=make_certificate(db,user,db.get(Course,course_id))
    if cloud_storage_enabled() and c.pdf_path and not c.pdf_path.startswith('supabase://'):
        local_pdf=Path(c.pdf_path); object_key=f'certificates/{c.certificate_number}.pdf'
        try:
            upload_cloud_file(local_pdf,object_key,'application/pdf')
        except CloudStorageError as exc:
            db.rollback()
            raise HTTPException(502,'Cloud file storage is unavailable.') from exc
        c.pdf_path=f'supabase://{object_key}'; db.flush(); local_pdf.unlink(missing_ok=True)
    db.commit(); return {'certificate_id':c.certificate_number,'verify_url':f"{(os.getenv('APP_BASE_URL') or os.getenv('RENDER_EXTERNAL_URL','http://localhost:8000')).rstrip('/')}/verify/{c.verification_token}"}

@app.get('/verify/{token}')
def verify_certificate(token:str,db:Session=Depends(get_db)):
    c=db.scalar(select(Certificate).where(Certificate.verification_token==token));
    if not c: raise HTTPException(404,'Certificate not found')
    u=db.get(User,c.user_id); course=db.get(Course,c.course_id); return {'valid':True,'certificate_id':c.certificate_number,'learner':u.name,'course':course.title,'completion_date':c.issued_at.date().isoformat()}

@app.get('/api/certificates/{certificate_id}/pdf')
def certificate_pdf(certificate_id:str,user=Depends(current_user),db:Session=Depends(get_db)):
    c=db.scalar(select(Certificate).where(Certificate.certificate_number==certificate_id));
    if not c or c.user_id!=user.id: raise HTTPException(404,'Certificate not found')
    if not c.pdf_path: raise HTTPException(404,'PDF unavailable')
    if c.pdf_path.startswith('supabase://'):
        return cloud_file_response(c.pdf_path.removeprefix('supabase://'),'application/pdf',f'{certificate_id}.pdf')
    if not Path(c.pdf_path).exists(): raise HTTPException(404,'PDF unavailable')
    return FileResponse(c.pdf_path,media_type='application/pdf',filename=f'{certificate_id}.pdf')

@app.get('/api/admin/users')
def admin_users(user=Depends(require_roles('admin')),db:Session=Depends(get_db)):
    us=db.scalars(select(User).order_by(desc(User.created_at))).all(); return [{'id':u.id,'name':u.name,'email':u.email,'role':u.role,'active':u.active,'verified':u.email_verified,'created_at':u.created_at.isoformat()} for u in us]

@app.post('/api/admin/users')
def admin_user_create(x:AdminUserCreateIn,user=Depends(require_roles('admin')),db:Session=Depends(get_db)):
    if x.role not in ASSIGNABLE_ROLES:
        raise HTTPException(400,'Invalid role')
    email=str(x.email).lower()
    if db.scalar(select(User).where(User.email==email)):
        raise HTTPException(409,'Email already exists')
    new_user=User(name=x.name.strip(),email=email,password_hash=hash_password(x.password),role=x.role,email_verified=True)
    db.add(new_user)
    db.flush()
    audit(db,user,'create_user','user',new_user.id)
    db.commit()
    db.refresh(new_user)
    return {'id':new_user.id,'name':new_user.name,'email':new_user.email,'role':new_user.role,'active':new_user.active}

@app.get('/api/admin/users/{user_id}/courses')
def admin_user_courses(
    user_id:int,
    user=Depends(require_roles('admin')),
    db:Session=Depends(get_db)
):
    u=db.get(User,user_id)
    if not u:
        raise HTTPException(404,'User not found')

    rows=db.execute(
        select(Enrollment,Course)
        .join(Course,Course.id==Enrollment.course_id)
        .where(Enrollment.user_id==user_id)
        .order_by(Course.id)
    ).all()

    return [
        {
            'enrollment_id':e.id,
            'course_id':c.id,
            'course_code':c.course_code,
            'course_title':c.title,
            'status':e.status,
            'enrolled_at':e.enrolled_at.isoformat()
        }
        for e,c in rows
    ]


@app.post('/api/admin/users/{user_id}/courses/{course_id}')
def admin_assign_course(
    user_id:int,
    course_id:int,
    user=Depends(require_roles('admin')),
    db:Session=Depends(get_db)
):
    learner=db.get(User,user_id)
    if not learner:
        raise HTTPException(404,'User not found')

    if learner.role!='learner':
        raise HTTPException(400,'Only learners can be assigned courses')

    course=db.get(Course,course_id)
    if not course:
        raise HTTPException(404,'Course not found')

    existing=db.scalar(
        select(Enrollment).where(
            Enrollment.user_id==user_id,
            Enrollment.course_id==course_id
        )
    )

    if existing:
        if existing.status!='active':
            existing.status='active'
            db.commit()
        return {
            'ok':True,
            'enrollment_id':existing.id,
            'course_id':course.id,
            'course_code':course.course_code,
            'message':'Course assignment restored'
        }

    enrollment=Enrollment(
        user_id=user_id,
        course_id=course_id,
        status='active'
    )

    db.add(enrollment)
    db.commit()
    db.refresh(enrollment)

    return {
        'ok':True,
        'enrollment_id':enrollment.id,
        'course_id':course.id,
        'course_code':course.course_code,
        'message':'Course assigned successfully'
    }


@app.delete('/api/admin/users/{user_id}/courses/{course_id}')
def admin_unassign_course(
    user_id:int,
    course_id:int,
    user=Depends(require_roles('admin')),
    db:Session=Depends(get_db)
):
    learner=db.get(User,user_id)
    if not learner:
        raise HTTPException(404,'User not found')

    enrollment=db.scalar(
        select(Enrollment).where(
            Enrollment.user_id==user_id,
            Enrollment.course_id==course_id
        )
    )

    if not enrollment:
        raise HTTPException(404,'Course assignment not found')

    enrollment.status='inactive'
    db.commit()

    return {
        'ok':True,
        'user_id':user_id,
        'course_id':course_id,
        'message':'Course unassigned successfully'
    }


@app.patch('/api/admin/users/{user_id}')
def admin_user_update(user_id:int,x:UserAdminIn,user=Depends(require_roles('admin')),db:Session=Depends(get_db)):
    u=db.get(User,user_id)
    if not u: raise HTTPException(404,'User not found')
    if x.role is not None and x.role not in ASSIGNABLE_ROLES:
        raise HTTPException(400,'Invalid role')
    if x.name is not None:
        updated_name=x.name.strip()
        if len(updated_name)<2:
            raise HTTPException(400,'Name must be at least 2 characters')
        u.name=updated_name
    if x.email is not None:
        updated_email=str(x.email).lower()
        duplicate=db.scalar(select(User).where(User.email==updated_email,User.id!=u.id))
        if duplicate:
            raise HTTPException(409,'Email already exists')
        u.email=updated_email
    if x.password is not None:
        u.password_hash=hash_password(x.password)
    if user_id==user.id and ((x.active is False) or (x.role is not None and x.role!='admin')):
        raise HTTPException(400,'You cannot remove your own admin access')
    if u.role=='admin' and u.active and ((x.active is False) or (x.role is not None and x.role!='admin')):
        active_admins=db.scalar(select(func.count()).select_from(User).where(User.role=='admin',User.active==True)) or 0
        if active_admins<=1:
            raise HTTPException(400,'At least one active admin account must remain')
    if x.active is not None: u.active=x.active
    if x.role is not None: u.role=x.role
    db.commit(); return {'ok':True}

@app.get('/api/admin/audit-logs')
def audit_logs(user=Depends(require_roles('admin')),db:Session=Depends(get_db)):
    rows=db.scalars(select(AuditLog).order_by(desc(AuditLog.created_at)).limit(500)).all(); return [{'id':x.id,'user_id':x.user_id,'action':x.action,'entity':x.entity,'entity_id':x.entity_id,'ip':x.ip_address,'at':x.created_at.isoformat()} for x in rows]

@app.post('/api/auth/password-reset/request')
@limiter.limit('5/minute')
def reset_request(request:Request,email:EmailStr,db:Session=Depends(get_db)):
    u=db.scalar(select(User).where(User.email==str(email).lower()));
    if u:
        raw=random_token(); db.add(SecurityToken(user_id=u.id,token_hash=token_hash(raw),kind='password_reset',expires_at=datetime.now(timezone.utc)+timedelta(hours=1))); db.commit()
        # Development-safe delivery: token is only returned when DEV_RESET_TOKENS is explicitly enabled.
        if os.getenv('DEV_RESET_TOKENS','false').lower()=='true': return {'ok':True,'dev_token':raw}
    return {'ok':True}

@app.post('/api/auth/password-reset/confirm')
def reset_confirm(token:str,new_password:str,db:Session=Depends(get_db)):
    st=db.scalar(select(SecurityToken).where(SecurityToken.token_hash==token_hash(token),SecurityToken.kind=='password_reset',SecurityToken.used==False))
    if not st or st.expires_at<datetime.now(timezone.utc): raise HTTPException(400,'Invalid or expired reset token')
    u=db.get(User,st.user_id); u.password_hash=hash_password(new_password); st.used=True; db.commit(); return {'ok':True}

@app.post('/api/auth/email-verification/confirm')
def verify_confirm(token:str,user=Depends(current_user),db:Session=Depends(get_db)):
    st=db.scalar(select(SecurityToken).where(SecurityToken.token_hash==token_hash(token),SecurityToken.kind=='email_verify',SecurityToken.user_id==user.id,SecurityToken.used==False))
    if not st or st.expires_at<datetime.now(timezone.utc): raise HTTPException(400,'Invalid or expired verification token')
    user.email_verified=True; st.used=True; db.commit(); return {'ok':True}

@app.post('/api/auth/email-verification/request')
@limiter.limit('5/minute')
def verify_request(request:Request,user=Depends(current_user),db:Session=Depends(get_db)):
    raw=random_token(); db.add(SecurityToken(user_id=user.id,token_hash=token_hash(raw),kind='email_verify',expires_at=datetime.now(timezone.utc)+timedelta(hours=24))); db.commit(); return {'ok':True,'dev_token':raw} if os.getenv('DEV_RESET_TOKENS','false').lower()=='true' else {'ok':True}

@app.post('/api/auth/mfa/setup')
def mfa_setup(user=Depends(current_user),db:Session=Depends(get_db)):
    import pyotp
    secret=pyotp.random_base32(); user.mfa_secret=secret; db.commit(); return {'secret':secret,'otpauth_url':pyotp.totp.TOTP(secret).provisioning_uri(name=user.email,issuer_name='Swaya')}

@app.post('/api/auth/mfa/enable')
def mfa_enable(x:MFAIn,user=Depends(current_user),db:Session=Depends(get_db)):
    import pyotp
    if not user.mfa_secret or not pyotp.TOTP(user.mfa_secret).verify(x.code): raise HTTPException(400,'Invalid MFA code')
    user.mfa_enabled=True; db.commit(); return {'ok':True}

@app.get('/')
def index(): return FileResponse(STATIC/'index.html')















