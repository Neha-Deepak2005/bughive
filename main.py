import os, uuid, datetime as dt
from typing import Optional
from fastapi import FastAPI, Depends, HTTPException, UploadFile, File
from fastapi.security import OAuth2PasswordBearer
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy import create_engine, Column, Integer, String, Text, ForeignKey, DateTime, or_
from sqlalchemy.orm import sessionmaker, declarative_base, Session
import jwt
from passlib.hash import pbkdf2_sha256

DB = os.getenv("DATABASE_URL", "sqlite:///./app.db")
if DB.startswith("postgres://"):
    DB = DB.replace("postgres://", "postgresql+psycopg2://", 1)
elif DB.startswith("postgresql://"):
    DB = DB.replace("postgresql://", "postgresql+psycopg2://", 1)
SECRET = os.getenv("SECRET_KEY", "change-me-in-production")
engine = create_engine(DB, connect_args={"check_same_thread": False} if DB.startswith("sqlite") else {})
SessionLocal = sessionmaker(bind=engine)
Base = declarative_base()
now = lambda: dt.datetime.utcnow()

class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True); name = Column(String(80)); email = Column(String(120), unique=True, index=True); pw = Column(String(200))
class Project(Base):
    __tablename__ = "projects"
    id = Column(Integer, primary_key=True); name = Column(String(80)); description = Column(Text, default=""); owner_id = Column(Integer, ForeignKey("users.id"))
class Member(Base):
    __tablename__ = "members"
    id = Column(Integer, primary_key=True); project_id = Column(Integer, ForeignKey("projects.id"), index=True); user_id = Column(Integer, ForeignKey("users.id")); role = Column(String(20))
class Ticket(Base):
    __tablename__ = "tickets"
    id = Column(Integer, primary_key=True); project_id = Column(Integer, ForeignKey("projects.id"), index=True)
    title = Column(String(200)); description = Column(Text, default=""); type = Column(String(20), default="bug"); priority = Column(String(20), default="medium")
    status = Column(String(20), default="todo", index=True); assignee_id = Column(Integer, ForeignKey("users.id"), nullable=True); reporter_id = Column(Integer, ForeignKey("users.id")); created_at = Column(DateTime, default=now)
class Comment(Base):
    __tablename__ = "comments"
    id = Column(Integer, primary_key=True); ticket_id = Column(Integer, ForeignKey("tickets.id"), index=True); user_id = Column(Integer, ForeignKey("users.id")); body = Column(Text); parent_id = Column(Integer, nullable=True); created_at = Column(DateTime, default=now)
class Attachment(Base):
    __tablename__ = "attachments"
    id = Column(Integer, primary_key=True); ticket_id = Column(Integer, ForeignKey("tickets.id"), index=True); filename = Column(String(200)); url = Column(String(300))
Base.metadata.create_all(engine)

app = FastAPI(title="Bug Tracker API")  # Swagger UI at /docs
oauth = OAuth2PasswordBearer(tokenUrl="/api/auth/login")
def get_db():
    db = SessionLocal()
    try: yield db
    finally: db.close()
def current_user(token: str = Depends(oauth), db: Session = Depends(get_db)):
    try: uid = jwt.decode(token, SECRET, algorithms=["HS256"])["sub"]
    except Exception: raise HTTPException(401, "Invalid or expired token")
    u = db.get(User, int(uid))
    if not u: raise HTTPException(401, "User not found")
    return u
def role_of(db, pid, uid):
    m = db.query(Member).filter_by(project_id=pid, user_id=uid).first()
    if not m: raise HTTPException(403, "Not a project member")
    return m.role
def need(role, *allowed):
    if role not in allowed: raise HTTPException(403, "Permission denied for your role")

class Reg(BaseModel): name: str; email: str; password: str
class Login(BaseModel): email: str; password: str
class ProjIn(BaseModel): name: str; description: str = ""
class MemIn(BaseModel): email: str; role: str = "developer"
class TicketIn(BaseModel):
    title: str; description: str = ""; type: str = "bug"; priority: str = "medium"; assignee_id: Optional[int] = None
class TicketPatch(BaseModel):
    title: Optional[str] = None; description: Optional[str] = None; type: Optional[str] = None
    priority: Optional[str] = None; status: Optional[str] = None; assignee_id: Optional[int] = None
class CommentIn(BaseModel): body: str; parent_id: Optional[int] = None

def token_for(u): return {"access_token": jwt.encode({"sub": str(u.id), "exp": now() + dt.timedelta(days=7)}, SECRET, "HS256"), "user": {"id": u.id, "name": u.name, "email": u.email}}

@app.post("/api/auth/register")
def register(b: Reg, db: Session = Depends(get_db)):
    if db.query(User).filter_by(email=b.email.lower()).first(): raise HTTPException(400, "Email already registered")
    u = User(name=b.name, email=b.email.lower(), pw=pbkdf2_sha256.hash(b.password)); db.add(u); db.commit()
    return token_for(u)
@app.post("/api/auth/login")
def login(b: Login, db: Session = Depends(get_db)):
    u = db.query(User).filter_by(email=b.email.lower()).first()
    if not u or not pbkdf2_sha256.verify(b.password, u.pw): raise HTTPException(401, "Wrong email or password")
    return token_for(u)

@app.get("/api/projects")
def projects(u=Depends(current_user), db: Session = Depends(get_db)):
    rows = db.query(Project, Member.role).join(Member, Member.project_id == Project.id).filter(Member.user_id == u.id).all()
    return [{"id": p.id, "name": p.name, "description": p.description, "role": r} for p, r in rows]
@app.post("/api/projects")
def new_project(b: ProjIn, u=Depends(current_user), db: Session = Depends(get_db)):
    p = Project(name=b.name, description=b.description, owner_id=u.id); db.add(p); db.flush()
    db.add(Member(project_id=p.id, user_id=u.id, role="admin")); db.commit()
    return {"id": p.id, "name": p.name, "description": p.description, "role": "admin"}
@app.get("/api/projects/{pid}/members")
def members(pid: int, u=Depends(current_user), db: Session = Depends(get_db)):
    role_of(db, pid, u.id)
    rows = db.query(User, Member.role).join(Member, Member.user_id == User.id).filter(Member.project_id == pid).all()
    return [{"id": x.id, "name": x.name, "email": x.email, "role": r} for x, r in rows]
@app.post("/api/projects/{pid}/members")
def add_member(pid: int, b: MemIn, u=Depends(current_user), db: Session = Depends(get_db)):
    need(role_of(db, pid, u.id), "admin")
    if b.role not in ("admin", "developer", "viewer"): raise HTTPException(400, "Bad role")
    t = db.query(User).filter_by(email=b.email.lower()).first()
    if not t: raise HTTPException(404, "No user with that email (ask them to register first)")
    m = db.query(Member).filter_by(project_id=pid, user_id=t.id).first()
    if m: m.role = b.role
    else: db.add(Member(project_id=pid, user_id=t.id, role=b.role))
    db.commit(); return {"ok": True}

def tdict(t, db):
    return {"id": t.id, "title": t.title, "description": t.description, "type": t.type, "priority": t.priority, "status": t.status,
            "assignee_id": t.assignee_id, "reporter_id": t.reporter_id, "created_at": t.created_at.isoformat(), "project_id": t.project_id}
@app.get("/api/projects/{pid}/tickets")
def tickets(pid: int, q: str = "", status: str = "", priority: str = "", type: str = "", assignee_id: int = 0, u=Depends(current_user), db: Session = Depends(get_db)):
    role_of(db, pid, u.id)
    qs = db.query(Ticket).filter(Ticket.project_id == pid)
    if q: qs = qs.filter(or_(Ticket.title.ilike(f"%{q}%"), Ticket.description.ilike(f"%{q}%")))
    if status: qs = qs.filter(Ticket.status == status)
    if priority: qs = qs.filter(Ticket.priority == priority)
    if type: qs = qs.filter(Ticket.type == type)
    if assignee_id: qs = qs.filter(Ticket.assignee_id == assignee_id)
    return [tdict(t, db) for t in qs.order_by(Ticket.id.desc()).all()]
@app.post("/api/projects/{pid}/tickets")
def new_ticket(pid: int, b: TicketIn, u=Depends(current_user), db: Session = Depends(get_db)):
    need(role_of(db, pid, u.id), "admin", "developer")
    t = Ticket(project_id=pid, reporter_id=u.id, **b.model_dump()); db.add(t); db.commit(); return tdict(t, db)
def get_ticket(db, tid, u):
    t = db.get(Ticket, tid)
    if not t: raise HTTPException(404, "Ticket not found")
    return t, role_of(db, t.project_id, u.id)
@app.patch("/api/tickets/{tid}")
def edit_ticket(tid: int, b: TicketPatch, u=Depends(current_user), db: Session = Depends(get_db)):
    t, r = get_ticket(db, tid, u); need(r, "admin", "developer")
    for k, v in b.model_dump(exclude_unset=True).items(): setattr(t, k, v)
    db.commit(); return tdict(t, db)
@app.delete("/api/tickets/{tid}")
def del_ticket(tid: int, u=Depends(current_user), db: Session = Depends(get_db)):
    t, r = get_ticket(db, tid, u)
    if r != "admin" and t.reporter_id != u.id: raise HTTPException(403, "Only admins or the reporter can delete")
    db.query(Comment).filter_by(ticket_id=tid).delete(); db.query(Attachment).filter_by(ticket_id=tid).delete(); db.delete(t); db.commit(); return {"ok": True}
@app.get("/api/tickets/{tid}/comments")
def comments(tid: int, u=Depends(current_user), db: Session = Depends(get_db)):
    get_ticket(db, tid, u)
    rows = db.query(Comment, User.name).join(User, User.id == Comment.user_id).filter(Comment.ticket_id == tid).order_by(Comment.id).all()
    return [{"id": c.id, "body": c.body, "user": n, "user_id": c.user_id, "parent_id": c.parent_id, "created_at": c.created_at.isoformat()} for c, n in rows]
@app.post("/api/tickets/{tid}/comments")
def add_comment(tid: int, b: CommentIn, u=Depends(current_user), db: Session = Depends(get_db)):
    t, r = get_ticket(db, tid, u); need(r, "admin", "developer")
    db.add(Comment(ticket_id=tid, user_id=u.id, body=b.body, parent_id=b.parent_id)); db.commit(); return {"ok": True}
@app.get("/api/tickets/{tid}/attachments")
def attachments(tid: int, u=Depends(current_user), db: Session = Depends(get_db)):
    get_ticket(db, tid, u); return [{"id": a.id, "filename": a.filename, "url": a.url} for a in db.query(Attachment).filter_by(ticket_id=tid)]
@app.post("/api/tickets/{tid}/attachments")
async def upload(tid: int, file: UploadFile = File(...), u=Depends(current_user), db: Session = Depends(get_db)):
    t, r = get_ticket(db, tid, u); need(r, "admin", "developer")
    if not (file.content_type or "").startswith("image/"): raise HTTPException(400, "Only images allowed")
    data = await file.read()
    if len(data) > 5_000_000: raise HTTPException(400, "Max 5MB")
    name = uuid.uuid4().hex + os.path.splitext(file.filename or "")[1][:6]
    os.makedirs("uploads", exist_ok=True); open(f"uploads/{name}", "wb").write(data)
    db.add(Attachment(ticket_id=tid, filename=file.filename, url=f"/uploads/{name}")); db.commit(); return {"ok": True}

os.makedirs("uploads", exist_ok=True)
app.mount("/uploads", StaticFiles(directory="uploads"), name="uploads")
@app.get("/")
def index(): return FileResponse("static/index.html")
