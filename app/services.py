import hashlib
import secrets
def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()
import os, json, uuid, hashlib
from datetime import datetime, timezone, timedelta
from pathlib import Path
import qrcode
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from sqlalchemy import select, func
from sqlalchemy.orm import Session
from .models import XPTransaction, Badge, UserBadge, Streak, Certificate, Progress, Lesson
def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def random_token() -> str:
    return secrets.token_urlsafe(32)
def add_xp(db,user_id,event,xp):
    db.add(XPTransaction(user_id=user_id,event=event,xp=xp))
    st=db.get(Streak,user_id)
    today=datetime.now(timezone.utc).date().isoformat()
    if not st: st=Streak(user_id=user_id,current_streak=1,longest_streak=1,last_activity_date=today); db.add(st)
    elif st.last_activity_date != today:
        st.current_streak = st.current_streak + 1 if st.last_activity_date else 1
        st.longest_streak=max(st.longest_streak,st.current_streak); st.last_activity_date=today
    db.flush(); award_badges(db,user_id)

def award_badges(db,user_id):
    total=db.scalar(select(func.coalesce(func.sum(XPTransaction.xp),0)).where(XPTransaction.user_id==user_id)) or 0
    count=db.scalar(select(func.count()).select_from(Progress).where(Progress.user_id==user_id,Progress.completed==True)) or 0
    rules=[('First Step','Complete your first learning day',count>=1),('SQL Explorer','Complete 10 learning days',count>=10),('Data Engineer','Complete all 30 learning days',count>=30),('XP Starter','Earn 500 XP',total>=500)]
    for name,desc,ok in rules:
        b=db.scalar(select(Badge).where(Badge.name==name))
        if b and ok and not db.scalar(select(UserBadge).where(UserBadge.user_id==user_id,UserBadge.badge_id==b.id)):
            db.add(UserBadge(user_id=user_id,badge_id=b.id))

def make_certificate(db,user,course):
    c=db.scalar(select(Certificate).where(Certificate.user_id==user.id,Certificate.course_id==course.id))
    if c: return c
    num='DE-'+datetime.now(timezone.utc).strftime('%Y')+'-'+uuid.uuid4().hex[:8].upper()
    token=uuid.uuid4().hex
    c=Certificate(user_id=user.id,course_id=course.id,certificate_number=num,verification_token=token)
    db.add(c); db.flush()
    root=Path(os.getenv('STORAGE_ROOT','./uploads')); certdir=root/'certificates'; certdir.mkdir(parents=True,exist_ok=True)
    base=(os.getenv('APP_BASE_URL') or os.getenv('RENDER_EXTERNAL_URL','http://localhost:8000')).rstrip('/')
    verify=f'{base}/verify/{token}'
    qr=qrcode.make(verify); qpath=certdir/f'{num}.png'; qr.save(qpath)
    ppath=certdir/f'{num}.pdf'; pdf=canvas.Canvas(str(ppath),pagesize=A4); w,h=A4
    pdf.setFont('Helvetica-Bold',26); pdf.drawCentredString(w/2,h-150,'Certificate of Completion')
    pdf.setFont('Helvetica',14); pdf.drawCentredString(w/2,h-205,'This certifies that')
    pdf.setFont('Helvetica-Bold',22); pdf.drawCentredString(w/2,h-250,user.name)
    pdf.setFont('Helvetica',14); pdf.drawCentredString(w/2,h-300,'has successfully completed')
    pdf.setFont('Helvetica-Bold',18); pdf.drawCentredString(w/2,h-335,course.title)
    pdf.setFont('Helvetica',11); pdf.drawCentredString(w/2,h-385,f'Certificate ID: {num}')
    pdf.drawCentredString(w/2,h-405,f'Completion date: {c.issued_at.date().isoformat()}')
    pdf.drawImage(str(qpath),w/2-45,80,width=90,height=90); pdf.save()
    c.pdf_path=str(ppath); db.flush(); return c
