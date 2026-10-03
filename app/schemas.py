from pydantic import BaseModel, EmailStr, Field, HttpUrl
from typing import Any
class RegisterIn(BaseModel): name:str=Field(min_length=2,max_length=120); email:EmailStr; password:str=Field(min_length=10,max_length=128); course_ids:list[int]=Field(min_length=1,max_length=50)
class LoginIn(BaseModel): email:EmailStr; password:str; mfa_code:str|None=None
class RefreshIn(BaseModel): refresh_token:str
class MFAIn(BaseModel): code:str=Field(min_length=6,max_length=6)
class MFASetupIn(BaseModel): setup_token:str
class MFAEnableIn(BaseModel): setup_token:str; code:str=Field(min_length=6,max_length=6)
class PublicRequestIn(BaseModel): name:str=Field(min_length=2,max_length=120); email:EmailStr; request_type:str; course_id:int|None=None; message:str=Field(default='',max_length=3000)
class PublicRequestStatusIn(BaseModel): status:str
class CourseIn(BaseModel): title:str; slug:str; description:str=''; status:str='draft'
class LessonIn(BaseModel): day_number:int=Field(ge=1,le=365); title:str; goal:str=''; content_md:str=''; content_html:str=''; content_css:str=''; objectives:list[str]=[]; resources:list[dict[str,Any]]=[]; estimated_minutes:int=60; status:str='published'
class QuestionIn(BaseModel): lesson_id:int; question:str; options:list[str]; correct_index:int; explanation:str=''; resource_url:str=''; difficulty:str='medium'; topic:str=''; tags:list[str]=[]; active:bool=True
class AssignmentIn(BaseModel): lesson_id:int; title:str; description:str=''; submission_type:str='file_or_github'; max_score:int=100; due_date:str|None=None
class ReviewIn(BaseModel): score:float; feedback:str=''
class TaskCompleteIn(BaseModel): done:bool=True
class QuizSubmitIn(BaseModel): answers:dict[str,int]
class UserAdminIn(BaseModel): active:bool|None=None; role:str|None=None; name:str|None=Field(default=None,min_length=2,max_length=120); email:EmailStr|None=None; password:str|None=Field(default=None,min_length=10,max_length=128)
class AdminUserCreateIn(BaseModel): name:str=Field(min_length=2,max_length=120); email:EmailStr; password:str=Field(min_length=10,max_length=128); role:str='learner'
class CohortIn(BaseModel): course_id:int; name:str; start_date:str; end_date:str; status:str='active'

