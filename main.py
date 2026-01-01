from fastapi import FastAPI, HTTPException, Request, Response, Depends, status
from fastapi.staticfiles import StaticFiles
from sqlmodel import Session, select, delete, or_
from database import engine, create_db_and_tables, seed_data, Employee, Location, Shift, LocationConstraint, EmployeeConstraint, LocationPreference
from pydantic import BaseModel
from datetime import datetime, timedelta
import os

app = FastAPI()

ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "admin")
SECRET_KEY = os.getenv("SECRET_KEY", "secret")

@app.on_event("startup")
def on_startup():
    create_db_and_tables()
    seed_data()

def get_current_admin(request: Request):
    token = request.cookies.get("admin_token")
    if token != SECRET_KEY:
        raise HTTPException(status_code=401, detail="Unauthorized")
    return True

# --- API Models ---
class LoginRequest(BaseModel): password: str
class MoveRequest(BaseModel): employee_id: int; date_str: str; location_id: int
class DeleteRequest(BaseModel): employee_id: int; date_str: str
class NameRequest(BaseModel): name: str
class ConstraintRequest(BaseModel): employee_id: int; target_id: int 

# --- Public Routes ---

@app.get("/api/roster/{start_date_str}")
def get_roster_state(start_date_str: str, request: Request):
    is_admin = request.cookies.get("admin_token") == SECRET_KEY
    start_date = datetime.strptime(start_date_str, "%Y-%m-%d").date()
    week_dates = [(start_date + timedelta(days=i)).strftime("%Y-%m-%d") for i in range(6)]
    
    with Session(engine) as session:
        employees = session.exec(select(Employee).where(Employee.active == True).order_by(Employee.name)).all()
        locations = session.exec(select(Location).order_by(Location.name)).all()
        shifts = session.exec(select(Shift).where(Shift.date_str >= week_dates[0], Shift.date_str <= week_dates[-1])).all()
        
        # Fetch Constraints & Preferences
        loc_constraints = session.exec(select(LocationConstraint)).all()
        emp_constraints = session.exec(select(EmployeeConstraint)).all()
        loc_preferences = session.exec(select(LocationPreference)).all()

        # Build Constraints Map
        # constraints[emp_id] = { bad_locs: [], bad_coworkers: [], preferred_locs: [] }
        constraints = {e.id: {"bad_locs": [], "bad_coworkers": [], "preferred_locs": []} for e in employees}
        
        for lc in loc_constraints:
            if lc.employee_id in constraints:
                constraints[lc.employee_id]["bad_locs"].append(lc.location_id)
        
        for ec in emp_constraints:
            if ec.employee_id in constraints:
                constraints[ec.employee_id]["bad_coworkers"].append(ec.target_employee_id)
            if ec.target_employee_id in constraints:
                constraints[ec.target_employee_id]["bad_coworkers"].append(ec.employee_id)
                
        for lp in loc_preferences:
            if lp.employee_id in constraints:
                constraints[lp.employee_id]["preferred_locs"].append(lp.location_id)

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
            "constraints": constraints,
            "is_admin": is_admin
        }

@app.post("/api/login")
def login(req: LoginRequest, response: Response):
    if req.password == ADMIN_PASSWORD:
        response.set_cookie(key="admin_token", value=SECRET_KEY, httponly=True)
        return {"status": "ok"}
    raise HTTPException(status_code=401, detail="Incorrect password")

@app.post("/api/logout")
def logout(response: Response):
    response.delete_cookie("admin_token")
    return {"status": "ok"}

# --- Protected Routes ---

@app.post("/api/assign", dependencies=[Depends(get_current_admin)])
def assign_shift(req: MoveRequest):
    with Session(engine) as session:
        existing = session.exec(select(Shift).where(Shift.employee_id == req.employee_id, Shift.date_str == req.date_str)).first()
        if existing: session.delete(existing)
        session.add(Shift(employee_id=req.employee_id, location_id=req.location_id, date_str=req.date_str))
        session.commit()
    return {"status": "ok"}

@app.post("/api/remove", dependencies=[Depends(get_current_admin)])
def remove_shift(req: DeleteRequest):
    with Session(engine) as session:
        session.exec(delete(Shift).where(Shift.employee_id == req.employee_id, Shift.date_str == req.date_str))
        session.commit()
    return {"status": "ok"}

# --- Management Routes ---

@app.post("/api/employees", dependencies=[Depends(get_current_admin)])
def add_employee(req: NameRequest):
    with Session(engine) as session:
        session.add(Employee(name=req.name))
        session.commit()
    return {"status": "ok"}

@app.put("/api/employees/{id}", dependencies=[Depends(get_current_admin)])
def update_employee(id: int, req: NameRequest):
    with Session(engine) as session:
        emp = session.get(Employee, id)
        if emp:
            emp.name = req.name
            session.add(emp)
            session.commit()
    return {"status": "ok"}

@app.delete("/api/employees/{id}", dependencies=[Depends(get_current_admin)])
def delete_employee(id: int):
    with Session(engine) as session:
        session.exec(delete(Shift).where(Shift.employee_id == id))
        session.exec(delete(LocationConstraint).where(LocationConstraint.employee_id == id))
        session.exec(delete(EmployeeConstraint).where(or_(EmployeeConstraint.employee_id == id, EmployeeConstraint.target_employee_id == id)))
        session.exec(delete(LocationPreference).where(LocationPreference.employee_id == id)) # Cleanup Prefs
        session.exec(delete(Employee).where(Employee.id == id))
        session.commit()
    return {"status": "ok"}

@app.post("/api/locations", dependencies=[Depends(get_current_admin)])
def add_location(req: NameRequest):
    with Session(engine) as session:
        session.add(Location(name=req.name))
        session.commit()
    return {"status": "ok"}

@app.put("/api/locations/{id}", dependencies=[Depends(get_current_admin)])
def update_location(id: int, req: NameRequest):
    with Session(engine) as session:
        loc = session.get(Location, id)
        if loc:
            loc.name = req.name
            session.add(loc)
            session.commit()
    return {"status": "ok"}

@app.delete("/api/locations/{id}", dependencies=[Depends(get_current_admin)])
def delete_location(id: int):
    with Session(engine) as session:
        session.exec(delete(Shift).where(Shift.location_id == id))
        session.exec(delete(LocationConstraint).where(LocationConstraint.location_id == id))
        session.exec(delete(LocationPreference).where(LocationPreference.location_id == id)) # Cleanup Prefs
        session.exec(delete(Location).where(Location.id == id))
        session.commit()
    return {"status": "ok"}

# --- Constraint & Preference Routes ---

@app.post("/api/constraints/location", dependencies=[Depends(get_current_admin)])
def add_loc_constraint(req: ConstraintRequest):
    with Session(engine) as session:
        exists = session.exec(select(LocationConstraint).where(LocationConstraint.employee_id==req.employee_id, LocationConstraint.location_id==req.target_id)).first()
        if not exists:
            session.add(LocationConstraint(employee_id=req.employee_id, location_id=req.target_id))
            session.commit()
    return {"status": "ok"}

@app.delete("/api/constraints/location", dependencies=[Depends(get_current_admin)])
def remove_loc_constraint(req: ConstraintRequest):
    with Session(engine) as session:
        session.exec(delete(LocationConstraint).where(LocationConstraint.employee_id==req.employee_id, LocationConstraint.location_id==req.target_id))
        session.commit()
    return {"status": "ok"}

@app.post("/api/constraints/employee", dependencies=[Depends(get_current_admin)])
def add_emp_constraint(req: ConstraintRequest):
    with Session(engine) as session:
        if req.employee_id == req.target_id: return {"status": "error"}
        exists = session.exec(select(EmployeeConstraint).where(EmployeeConstraint.employee_id==req.employee_id, EmployeeConstraint.target_employee_id==req.target_id)).first()
        if not exists:
            session.add(EmployeeConstraint(employee_id=req.employee_id, target_employee_id=req.target_id))
            session.commit()
    return {"status": "ok"}

@app.delete("/api/constraints/employee", dependencies=[Depends(get_current_admin)])
def remove_emp_constraint(req: ConstraintRequest):
    with Session(engine) as session:
        session.exec(delete(EmployeeConstraint).where(EmployeeConstraint.employee_id==req.employee_id, EmployeeConstraint.target_employee_id==req.target_id))
        session.exec(delete(EmployeeConstraint).where(EmployeeConstraint.employee_id==req.target_id, EmployeeConstraint.target_employee_id==req.employee_id))
        session.commit()
    return {"status": "ok"}

# NEW: Preference Routes
@app.post("/api/preferences/location", dependencies=[Depends(get_current_admin)])
def add_loc_preference(req: ConstraintRequest):
    with Session(engine) as session:
        exists = session.exec(select(LocationPreference).where(LocationPreference.employee_id==req.employee_id, LocationPreference.location_id==req.target_id)).first()
        if not exists:
            session.add(LocationPreference(employee_id=req.employee_id, location_id=req.target_id))
            session.commit()
    return {"status": "ok"}

@app.delete("/api/preferences/location", dependencies=[Depends(get_current_admin)])
def remove_loc_preference(req: ConstraintRequest):
    with Session(engine) as session:
        session.exec(delete(LocationPreference).where(LocationPreference.employee_id==req.employee_id, LocationPreference.location_id==req.target_id))
        session.commit()
    return {"status": "ok"}

app.mount("/", StaticFiles(directory="static", html=True), name="static")
