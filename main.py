from fastapi import FastAPI, HTTPException, Request, Response, Depends, status
from fastapi.staticfiles import StaticFiles
from sqlmodel import Session, select, delete
from database import engine, create_db_and_tables, seed_data, Employee, Location, Shift
from pydantic import BaseModel
from datetime import datetime, timedelta
import os

app = FastAPI()

# --- Configuration ---
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "admin")
SECRET_KEY = os.getenv("SECRET_KEY", "secret")

@app.on_event("startup")
def on_startup():
    create_db_and_tables()
    seed_data()

# --- Auth Dependency ---
def get_current_admin(request: Request):
    token = request.cookies.get("admin_token")
    if token != SECRET_KEY:
        raise HTTPException(status_code=401, detail="Unauthorized")
    return True

# --- Pydantic Models ---
class LoginRequest(BaseModel):
    password: str

class MoveRequest(BaseModel):
    employee_id: int
    date_str: str
    location_id: int

class DeleteRequest(BaseModel):
    employee_id: int
    date_str: str

class NameRequest(BaseModel):
    name: str

# --- Public Routes ---

@app.get("/api/roster/{start_date_str}")
def get_roster_state(start_date_str: str, request: Request):
    """Returns the schedule. Checks cookie to tell frontend if user is admin."""
    
    is_admin = request.cookies.get("admin_token") == SECRET_KEY

    # Calculate dates
    start_date = datetime.strptime(start_date_str, "%Y-%m-%d").date()
    week_dates = [(start_date + timedelta(days=i)).strftime("%Y-%m-%d") for i in range(7)]
    
    with Session(engine) as session:
        employees = session.exec(select(Employee).where(Employee.active == True)).all()
        locations = session.exec(select(Location)).all()
        shifts = session.exec(select(Shift).where(
            Shift.date_str >= week_dates[0],
            Shift.date_str <= week_dates[6]
        )).all()

        grid = {e.id: {d: None for d in week_dates} for e in employees}
        loc_map = {l.id: l for l in locations}

        for shift in shifts:
            if shift.employee_id in grid and shift.date_str in grid[shift.employee_id]:
                if shift.location_id in loc_map:
                    grid[shift.employee_id][shift.date_str] = loc_map[shift.location_id]

        return {
            "week_dates": week_dates,
            "employees": employees,
            "locations": locations,
            "grid": grid,
            "is_admin": is_admin
        }

@app.post("/api/login")
def login(req: LoginRequest, response: Response):
    if req.password == ADMIN_PASSWORD:
        # Set a simple cookie
        response.set_cookie(key="admin_token", value=SECRET_KEY, httponly=True)
        return {"status": "ok"}
    raise HTTPException(status_code=401, detail="Incorrect password")

@app.post("/api/logout")
def logout(response: Response):
    response.delete_cookie("admin_token")
    return {"status": "ok"}

# --- Protected Routes (Require Login) ---

@app.post("/api/assign", dependencies=[Depends(get_current_admin)])
def assign_shift(req: MoveRequest):
    with Session(engine) as session:
        existing = session.exec(select(Shift).where(
            Shift.employee_id == req.employee_id,
            Shift.date_str == req.date_str
        )).first()
        if existing:
            session.delete(existing)
        
        session.add(Shift(employee_id=req.employee_id, location_id=req.location_id, date_str=req.date_str))
        session.commit()
    return {"status": "ok"}

@app.post("/api/remove", dependencies=[Depends(get_current_admin)])
def remove_shift(req: DeleteRequest):
    with Session(engine) as session:
        statement = delete(Shift).where(
            Shift.employee_id == req.employee_id, 
            Shift.date_str == req.date_str
        )
        session.exec(statement)
        session.commit()
    return {"status": "ok"}

# --- Management Routes (Add/Delete Staff & Shops) ---

@app.post("/api/employees", dependencies=[Depends(get_current_admin)])
def add_employee(req: NameRequest):
    with Session(engine) as session:
        session.add(Employee(name=req.name))
        session.commit()
    return {"status": "ok"}

@app.delete("/api/employees/{id}", dependencies=[Depends(get_current_admin)])
def delete_employee(id: int):
    with Session(engine) as session:
        # Cascade delete shifts first
        session.exec(delete(Shift).where(Shift.employee_id == id))
        session.exec(delete(Employee).where(Employee.id == id))
        session.commit()
    return {"status": "ok"}

@app.post("/api/locations", dependencies=[Depends(get_current_admin)])
def add_location(req: NameRequest):
    with Session(engine) as session:
        session.add(Location(name=req.name))
        session.commit()
    return {"status": "ok"}

@app.delete("/api/locations/{id}", dependencies=[Depends(get_current_admin)])
def delete_location(id: int):
    with Session(engine) as session:
        session.exec(delete(Shift).where(Shift.location_id == id))
        session.exec(delete(Location).where(Location.id == id))
        session.commit()
    return {"status": "ok"}

app.mount("/", StaticFiles(directory="static", html=True), name="static")
