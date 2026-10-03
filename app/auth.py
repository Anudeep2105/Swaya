import os, hashlib, secrets
from datetime import datetime, timedelta, timezone
import jwt
from fastapi import Depends, HTTPException
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pwdlib import PasswordHash
from sqlalchemy.orm import Session
from sqlalchemy import select
from .database import get_db
from .models import User

SECRET=os.getenv('SECRET_KEY','dev-only-change-me')
ALGO='HS256'; ACCESS_MIN=int(os.getenv('ACCESS_TOKEN_MINUTES','30')); REFRESH_DAYS=int(os.getenv('REFRESH_TOKEN_DAYS','14'))
ph=PasswordHash.recommended(); bearer=HTTPBearer(auto_error=False)

def hash_password(p): return ph.hash(p)
def verify_password(p,h): return ph.verify(p,h)
def make_token(user, kind='access'):
    mins=ACCESS_MIN if kind=='access' else 10 if kind=='mfa_setup' else REFRESH_DAYS*24*60
    return jwt.encode({'sub':str(user.id),'role':user.role,'mfa':bool(user.mfa_enabled),'type':kind,'exp':datetime.now(timezone.utc)+timedelta(minutes=mins)},SECRET,algorithm=ALGO)
def decode(token, expected='access'):
    try:
        p=jwt.decode(token,SECRET,algorithms=[ALGO])
        if p.get('type')!=expected: raise ValueError()
        return p
    except Exception: raise HTTPException(401,'Invalid or expired token')
def current_user(creds:HTTPAuthorizationCredentials=Depends(bearer),db:Session=Depends(get_db)):
    if not creds: raise HTTPException(401,'Authentication required')
    p=decode(creds.credentials)
    u=db.get(User,int(p['sub']))
    if not u or not u.active: raise HTTPException(401,'Account unavailable')
    if u.role=='admin' and (not u.mfa_enabled or p.get('mfa') is not True): raise HTTPException(401,'Administrator sign-in requires authenticator setup and verification')
    return u
def require_roles(*roles):
    def dep(user=Depends(current_user)):
        if user.role not in roles: raise HTTPException(403,'Insufficient permissions')
        return user
    return dep
def token_hash(raw): return hashlib.sha256(raw.encode()).hexdigest()
def random_token(): return secrets.token_urlsafe(32)
