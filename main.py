from fastapi import FastAPI, HTTPException, Request, Response, Depends, status
from fastapi.staticfiles import StaticFiles
from sqlmodel import Session, select, delete, or_
from database import engine, create_db_and_tables, seed_data, Employee, Location, Shift, LocationConstraint, EmployeeConstraint, LocationPreference, EmployeeUnavailableDay, EmployeeTargetDays, WeekStatus, EmployeeCoworkerPreference, LocationTarget
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
# UPDATED: Request model now takes min/max
class LocationTargetRequest(BaseModel): location_id: int; min_employees: int; max_employees: int
class PublishRequest(BaseModel): week_start: str
class AutoFillRequest(BaseModel): week_start: str; mode: str

# --- Public Routes ---

@app.get("/api/roster/{start_date_str}")
def get_roster_state(start_date_str: str, request: Request):
    is_admin = request.cookies.get("admin_token") == SECRET_KEY
    start_date = datetime.strptime(start_date_str, "%Y-%m-%d").date()
    week_dates = [(start_date + timedelta(days=i)).strftime("%Y-%m-%d") for i in range(6)]
    
    with Session(engine) as session:
        status_entry = session.exec(select(WeekStatus).where(WeekStatus.week_start == start_date_str)).first()
        is_published = status_entry.is_published if status_entry else False
        published_at = status_entry.published_at if status_entry else None

        employees = session.exec(select(Employee).where(Employee.active == True).order_by(Employee.name)).all()
        locations = session.exec(select(Location).order_by(Location.name)).all()
        
        shifts = []
        if is_admin or is_published:
            shifts = session.exec(select(Shift).where(Shift.date_str >= week_dates[0], Shift.date_str <= week_dates[-1])).all()
        
        # Constraints
        loc_constraints = session.exec(select(LocationConstraint)).all()
        emp_constraints = session.exec(select(EmployeeConstraint)).all()
        loc_preferences = session.exec(select(LocationPreference)).all()
        day_constraints = session.exec(select(EmployeeUnavailableDay)).all()
        target_days = session.exec(select(EmployeeTargetDays)).all()
        coworker_preferences = session.exec(select(EmployeeCoworkerPreference)).all()
        
        # NEW: Return min/max dict
        location_targets_db = session.exec(select(LocationTarget)).all()
        location_targets = {lt.location_id: {"min": lt.min_employees, "max": lt.max_employees} for lt in location_targets_db}

        constraints = {e.id: {"bad_locs": [], "bad_coworkers": [], "preferred_locs": [], "preferred_coworkers": [], "bad_days": [], "target_days": None} for e in employees}
        
        for lc in loc_constraints:
            if lc.employee_id in constraints: constraints[lc.employee_id]["bad_locs"].append(lc.location_id)
        for ec in emp_constraints:
            if ec.employee_id in constraints: constraints[ec.employee_id]["bad_coworkers"].append(ec.target_employee_id)
            if ec.target_employee_id in constraints: constraints[ec.target_employee_id]["bad_coworkers"].append(ec.employee_id)
        for lp in loc_preferences:
            if lp.employee_id in constraints: constraints[lp.employee_id]["preferred_locs"].append(lp.location_id)
        for dc in day_constraints:
            if dc.employee_id in constraints: constraints[dc.employee_id]["bad_days"].append(dc.day_of_week)
        for td in target_days:
            if td.employee_id in constraints: constraints[td.employee_id]["target_days"] = td.target_days
        for cp in coworker_preferences:
            if cp.employee_id in constraints: constraints[cp.employee_id]["preferred_coworkers"].append(cp.target_employee_id)

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
            "location_targets": location_targets,
            "grid": grid,
            "constraints": constraints,
            "is_admin": is_admin,
            "is_published": is_published,
            "published_at": published_at.isoformat() if published_at else None
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

@app.post("/api/publish", dependencies=[Depends(get_current_admin)])
def publish_week(req: PublishRequest):
    with Session(engine) as session:
        status_entry = session.exec(select(WeekStatus).where(WeekStatus.week_start == req.week_start)).first()
        if not status_entry:
            status_entry = WeekStatus(week_start=req.week_start)
            session.add(status_entry)
        status_entry.is_published = True
        status_entry.published_at = datetime.now()
        session.commit()
    return {"status": "ok"}

@app.post("/api/autofill", dependencies=[Depends(get_current_admin)])
def autofill_schedule(req: AutoFillRequest):
    start_date = datetime.strptime(req.week_start, "%Y-%m-%d").date()
    week_dates = [(start_date + timedelta(days=i)).strftime("%Y-%m-%d") for i in range(6)]
    
    with Session(engine) as session:
        session.exec(delete(Shift).where(Shift.date_str >= week_dates[0], Shift.date_str <= week_dates[-1]))
        
        if req.mode == 'copy':
            prev_start = (start_date - timedelta(days=7)).strftime("%Y-%m-%d")
            prev_end = (start_date - timedelta(days=2)).strftime("%Y-%m-%d")
            old_shifts = session.exec(select(Shift).where(Shift.date_str >= prev_start, Shift.date_str <= prev_end)).all()
            for old in old_shifts:
                day_diff = (datetime.strptime(old.date_str, "%Y-%m-%d").date() - (start_date - timedelta(days=7))).days
                if 0 <= day_diff < 6:
                    session.add(Shift(employee_id=old.employee_id, location_id=old.location_id, date_str=week_dates[day_diff]))
        
        elif req.mode == 'smart':
            employees = session.exec(select(Employee).where(Employee.active==True)).all()
            prefs = session.exec(select(LocationPreference)).all()
            targets = session.exec(select(EmployeeTargetDays)).all()
            unavailable = session.exec(select(EmployeeUnavailableDay)).all()
            
            pref_map = {e.id: [] for e in employees}
            for p in prefs: pref_map[p.employee_id].append(p.location_id)
            target_map = {t.employee_id: t.target_days for t in targets}
            bad_days_map = {u.employee_id: [] for u in unavailable}
            for u in unavailable: bad_days_map[u.employee_id].append(u.day_of_week)

            for emp in employees:
                target = target_map.get(emp.id, 0)
                if target == 0 or not pref_map[emp.id]: continue
                days_assigned = 0
                for day_idx, date_str in enumerate(week_dates):
                    if days_assigned >= target: break
                    if day_idx in bad_days_map.get(emp.id, []): continue
                    session.add(Shift(employee_id=emp.id, location_id=pref_map[emp.id][0], date_str=date_str))
                    days_assigned += 1

        session.commit()
    return {"status": "ok"}

# --- Management Routes ---
@app.post("/api/employees", dependencies=[Depends(get_current_admin)])
def add_employee(req: NameRequest):
    with Session(engine) as session: session.add(Employee(name=req.name)); session.commit()
    return {"status": "ok"}
@app.put("/api/employees/{id}", dependencies=[Depends(get_current_admin)])
def update_employee(id: int, req: NameRequest):
    with Session(engine) as session: 
        e = session.get(Employee, id)
        if e: e.name = req.name; session.add(e); session.commit()
    return {"status": "ok"}
@app.delete("/api/employees/{id}", dependencies=[Depends(get_current_admin)])
def delete_employee(id: int):
    with Session(engine) as session:
        session.exec(delete(Shift).where(Shift.employee_id == id))
        session.exec(delete(LocationConstraint).where(LocationConstraint.employee_id == id))
        session.exec(delete(EmployeeConstraint).where(or_(EmployeeConstraint.employee_id == id, EmployeeConstraint.target_employee_id == id)))
        session.exec(delete(LocationPreference).where(LocationPreference.employee_id == id))
        session.exec(delete(EmployeeCoworkerPreference).where(EmployeeCoworkerPreference.employee_id == id)) 
        session.exec(delete(EmployeeUnavailableDay).where(EmployeeUnavailableDay.employee_id == id))
        session.exec(delete(EmployeeTargetDays).where(EmployeeTargetDays.employee_id == id))
        session.exec(delete(Employee).where(Employee.id == id))
        session.commit()
    return {"status": "ok"}
@app.post("/api/locations", dependencies=[Depends(get_current_admin)])
def add_location(req: NameRequest):
    with Session(engine) as session: session.add(Location(name=req.name)); session.commit()
    return {"status": "ok"}
@app.put("/api/locations/{id}", dependencies=[Depends(get_current_admin)])
def update_location(id: int, req: NameRequest):
    with Session(engine) as session:
        l = session.get(Location, id)
        if l: l.name = req.name; session.add(l); session.commit()
    return {"status": "ok"}
@app.delete("/api/locations/{id}", dependencies=[Depends(get_current_admin)])
def delete_location(id: int):
    with Session(engine) as session:
        session.exec(delete(Shift).where(Shift.location_id == id))
        session.exec(delete(LocationConstraint).where(LocationConstraint.location_id == id))
        session.exec(delete(LocationPreference).where(LocationPreference.location_id == id))
        session.exec(delete(LocationTarget).where(LocationTarget.location_id == id))
        session.exec(delete(Location).where(Location.id == id))
        session.commit()
    return {"status": "ok"}

# --- Constraint Routes ---
@app.post("/api/constraints/location", dependencies=[Depends(get_current_admin)])
def add_loc_constraint(req: ConstraintRequest):
    with Session(engine) as session:
        if not session.exec(select(LocationConstraint).where(LocationConstraint.employee_id==req.employee_id, LocationConstraint.location_id==req.target_id)).first():
            session.add(LocationConstraint(employee_id=req.employee_id, location_id=req.target_id)); session.commit()
    return {"status": "ok"}
@app.delete("/api/constraints/location", dependencies=[Depends(get_current_admin)])
def remove_loc_constraint(req: ConstraintRequest):
    with Session(engine) as session:
        session.exec(delete(LocationConstraint).where(LocationConstraint.employee_id==req.employee_id, LocationConstraint.location_id==req.target_id)); session.commit()
    return {"status": "ok"}
@app.post("/api/constraints/employee", dependencies=[Depends(get_current_admin)])
def add_emp_constraint(req: ConstraintRequest):
    with Session(engine) as session:
        if req.employee_id != req.target_id and not session.exec(select(EmployeeConstraint).where(EmployeeConstraint.employee_id==req.employee_id, EmployeeConstraint.target_employee_id==req.target_id)).first():
            session.add(EmployeeConstraint(employee_id=req.employee_id, target_employee_id=req.target_id)); session.commit()
    return {"status": "ok"}
@app.delete("/api/constraints/employee", dependencies=[Depends(get_current_admin)])
def remove_emp_constraint(req: ConstraintRequest):
    with Session(engine) as session:
        session.exec(delete(EmployeeConstraint).where(EmployeeConstraint.employee_id==req.employee_id, EmployeeConstraint.target_employee_id==req.target_id))
        session.exec(delete(EmployeeConstraint).where(EmployeeConstraint.employee_id==req.target_id, EmployeeConstraint.target_employee_id==req.employee_id))
        session.commit()
    return {"status": "ok"}
@app.post("/api/constraints/day", dependencies=[Depends(get_current_admin)])
def add_day_constraint(req: ConstraintRequest):
    with Session(engine) as session:
        if not session.exec(select(EmployeeUnavailableDay).where(EmployeeUnavailableDay.employee_id==req.employee_id, EmployeeUnavailableDay.day_of_week==req.target_id)).first():
            session.add(EmployeeUnavailableDay(employee_id=req.employee_id, day_of_week=req.target_id)); session.commit()
    return {"status": "ok"}
@app.delete("/api/constraints/day", dependencies=[Depends(get_current_admin)])
def remove_day_constraint(req: ConstraintRequest):
    with Session(engine) as session:
        session.exec(delete(EmployeeUnavailableDay).where(EmployeeUnavailableDay.employee_id==req.employee_id, EmployeeUnavailableDay.day_of_week==req.target_id)); session.commit()
    return {"status": "ok"}
@app.post("/api/constraints/target_days", dependencies=[Depends(get_current_admin)])
def set_target_days(req: ConstraintRequest):
    with Session(engine) as session:
        existing = session.exec(select(EmployeeTargetDays).where(EmployeeTargetDays.employee_id == req.employee_id)).first()
        if existing: existing.target_days = req.target_id; session.add(existing)
        else: session.add(EmployeeTargetDays(employee_id=req.employee_id, target_days=req.target_id))
        session.commit()
    return {"status": "ok"}

# --- Preference Routes ---
@app.post("/api/preferences/location", dependencies=[Depends(get_current_admin)])
def add_loc_preference(req: ConstraintRequest):
    with Session(engine) as session:
        if not session.exec(select(LocationPreference).where(LocationPreference.employee_id==req.employee_id, LocationPreference.location_id==req.target_id)).first():
            session.add(LocationPreference(employee_id=req.employee_id, location_id=req.target_id)); session.commit()
    return {"status": "ok"}
@app.delete("/api/preferences/location", dependencies=[Depends(get_current_admin)])
def remove_loc_preference(req: ConstraintRequest):
    with Session(engine) as session:
        session.exec(delete(LocationPreference).where(LocationPreference.employee_id==req.employee_id, LocationPreference.location_id==req.target_id)); session.commit()
    return {"status": "ok"}
@app.post("/api/preferences/employee", dependencies=[Depends(get_current_admin)])
def add_emp_preference(req: ConstraintRequest):
    with Session(engine) as session:
        if req.employee_id != req.target_id and not session.exec(select(EmployeeCoworkerPreference).where(EmployeeCoworkerPreference.employee_id==req.employee_id, EmployeeCoworkerPreference.target_employee_id==req.target_id)).first():
            session.add(EmployeeCoworkerPreference(employee_id=req.employee_id, target_employee_id=req.target_id)); session.commit()
    return {"status": "ok"}
@app.delete("/api/preferences/employee", dependencies=[Depends(get_current_admin)])
def remove_emp_preference(req: ConstraintRequest):
    with Session(engine) as session:
        session.exec(delete(EmployeeCoworkerPreference).where(EmployeeCoworkerPreference.employee_id==req.employee_id, EmployeeCoworkerPreference.target_employee_id==req.target_id)); session.commit()
    return {"status": "ok"}

# NEW: UPDATED Location Target Route (Min/Max)
@app.post("/api/constraints/location_target", dependencies=[Depends(get_current_admin)])
def set_location_target(req: LocationTargetRequest):
    with Session(engine) as session:
        existing = session.exec(select(LocationTarget).where(LocationTarget.location_id == req.location_id)).first()
        if existing: 
            existing.min_employees = req.min_employees
            existing.max_employees = req.max_employees
            session.add(existing)
        else: 
            session.add(LocationTarget(location_id=req.location_id, min_employees=req.min_employees, max_employees=req.max_employees))
        session.commit()
    return {"status": "ok"}

app.mount("/", StaticFiles(directory="static", html=True), name="static")
