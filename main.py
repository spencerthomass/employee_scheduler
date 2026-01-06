from fastapi import FastAPI, HTTPException, Request, Response, Depends, status
from fastapi.staticfiles import StaticFiles
from sqlmodel import Session, select, delete, or_, text
from database import engine, create_db_and_tables, seed_data, Employee, Location, Shift, LocationConstraint, EmployeeConstraint, LocationPreference, EmployeeUnavailableDay, EmployeeTargetDays, WeekStatus, EmployeeCoworkerPreference, LocationTarget
from pydantic import BaseModel
from datetime import datetime, timedelta
import os
import json
import random

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
class LocationTargetRequest(BaseModel): location_id: int; min_employees: int; max_employees: int
class EmployeeTargetDaysRequest(BaseModel): employee_id: int; min_days: int; max_days: int
class PublishRequest(BaseModel): week_start: str
class AutoFillRequest(BaseModel): week_start: str; mode: str
class ExportRequest(BaseModel): tables: list[str]
class ClearWeekRequest(BaseModel): week_start: str

TABLE_MAP = {
    "employees": Employee, "locations": Location, "shifts": Shift,
    "location_constraints": LocationConstraint, "employee_constraints": EmployeeConstraint,
    "location_preferences": LocationPreference, "coworker_preferences": EmployeeCoworkerPreference,
    "unavailable_days": EmployeeUnavailableDay, "employee_target_days": EmployeeTargetDays,
    "location_targets": LocationTarget, "week_status": WeekStatus
}

# --- Backup/Restore Routes ---

@app.post("/api/backup/export", dependencies=[Depends(get_current_admin)])
def export_data(req: ExportRequest):
    data = {}
    with Session(engine) as session:
        for table_name in req.tables:
            if table_name in TABLE_MAP:
                model = TABLE_MAP[table_name]
                results = session.exec(select(model)).all()
                data[table_name] = [row.dict() for row in results]
    return data

@app.post("/api/backup/import", dependencies=[Depends(get_current_admin)])
async def import_data(request: Request):
    try: data = await request.json()
    except: raise HTTPException(status_code=400, detail="Invalid JSON")
    with Session(engine) as session:
        session.exec(text("SET FOREIGN_KEY_CHECKS=0"))
        try:
            for table_name, rows in data.items():
                if table_name in TABLE_MAP and rows:
                    model = TABLE_MAP[table_name]
                    session.exec(delete(model))
                    for row in rows:
                        try: session.add(model.model_validate(row))
                        except Exception as e: print(f"Skipping invalid row in {table_name}: {e}")
            session.commit()
        finally: session.exec(text("SET FOREIGN_KEY_CHECKS=1"))
    return {"status": "ok", "message": "Import successful"}

# --- Standard Routes ---

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
        
        loc_constraints = session.exec(select(LocationConstraint)).all()
        emp_constraints = session.exec(select(EmployeeConstraint)).all()
        loc_preferences = session.exec(select(LocationPreference)).all()
        day_constraints = session.exec(select(EmployeeUnavailableDay)).all()
        target_days = session.exec(select(EmployeeTargetDays)).all()
        coworker_preferences = session.exec(select(EmployeeCoworkerPreference)).all()
        
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
            if td.employee_id in constraints: constraints[td.employee_id]["target_days"] = {"min": td.min_days, "max": td.max_days}
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
        # Clear existing
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
            # --- FETCH ALL DATA ---
            employees = session.exec(select(Employee).where(Employee.active==True)).all()
            locations = session.exec(select(Location)).all()
            
            # Constraint Lookups
            prefs_db = session.exec(select(LocationPreference)).all()
            targets_db = session.exec(select(EmployeeTargetDays)).all()
            unavailable_db = session.exec(select(EmployeeUnavailableDay)).all()
            bad_locs_db = session.exec(select(LocationConstraint)).all()
            loc_targets_db = session.exec(select(LocationTarget)).all()

            # Mappings for O(1) access
            pref_map = {e.id: [] for e in employees}
            for p in prefs_db: pref_map[p.employee_id].append(p.location_id)
            
            # Default target: 5 days max, 0 min
            emp_targets = {e.id: {"min": 0, "max": 5} for e in employees}
            for t in targets_db: emp_targets[t.employee_id] = {"min": t.min_days, "max": t.max_days}
            
            bad_days = {e.id: [] for e in employees}
            for u in unavailable_db: bad_days[u.employee_id].append(u.day_of_week)
            
            bad_locs = {e.id: [] for e in employees}
            for bl in bad_locs_db: bad_locs[bl.employee_id].append(bl.location_id)
            
            loc_min_max = {l.id: {"min": 1, "max": 1} for l in locations}
            for lt in loc_targets_db: loc_min_max[lt.location_id] = {"min": lt.min_employees, "max": lt.max_employees}

            # Tracking State
            emp_days_assigned = {e.id: 0 for e in employees}
            # key: f"{loc_id}_{date_str}", val: count
            loc_day_counts = {} 
            # key: f"{emp_id}_{date_str}", val: bool
            emp_working_today = {}

            def is_available(emp_id, date_str, day_idx, loc_id):
                # Hard Constraints
                if emp_days_assigned[emp_id] >= emp_targets[emp_id]["max"]: return False
                if day_idx in bad_days[emp_id]: return False
                if loc_id in bad_locs[emp_id]: return False
                if emp_working_today.get(f"{emp_id}_{date_str}", False): return False
                return True

            def assign(emp_id, loc_id, date_str):
                session.add(Shift(employee_id=emp_id, location_id=loc_id, date_str=date_str))
                emp_days_assigned[emp_id] += 1
                key = f"{loc_id}_{date_str}"
                loc_day_counts[key] = loc_day_counts.get(key, 0) + 1
                emp_working_today[f"{emp_id}_{date_str}"] = True

            # --- PHASE 1: Coverage (Ensure Shops Meet Minimums) ---
            # Randomize list of days to ensure Saturday coverage gets looked at
            day_indices = list(range(6))
            random.shuffle(day_indices)

            for i in day_indices:
                date_str = week_dates[i]
                
                # Shuffle locations to prevent bias
                shuffled_locs = list(locations)
                random.shuffle(shuffled_locs)

                for loc in shuffled_locs:
                    min_req = loc_min_max[loc.id]["min"]
                    current = loc_day_counts.get(f"{loc.id}_{date_str}", 0)
                    
                    while current < min_req:
                        # Find candidates
                        candidates = []
                        for emp in employees:
                            if is_available(emp.id, date_str, i, loc.id):
                                score = 0
                                # Prefer people who like this location
                                if loc.id in pref_map[emp.id]: score += 10
                                # Prefer people who haven't met min days yet
                                if emp_days_assigned[emp.id] < emp_targets[emp.id]["min"]: score += 5
                                # Slight random factor to break ties
                                score += random.random()
                                candidates.append((score, emp))
                        
                        if not candidates:
                            break # No one available for this slot, skip
                        
                        # Pick best
                        candidates.sort(key=lambda x: x[0], reverse=True)
                        best_emp = candidates[0][1]
                        assign(best_emp.id, loc.id, date_str)
                        current += 1

            # --- PHASE 2: Hours (Ensure Employees Meet Minimums) ---
            # Iterate employees who need days
            needy_employees = [e for e in employees if emp_days_assigned[e.id] < emp_targets[e.id]["min"]]
            random.shuffle(needy_employees)

            for emp in needy_employees:
                needed = emp_targets[emp.id]["min"] - emp_days_assigned[emp.id]
                
                # Check each day to find a spot
                for i in day_indices:
                    if needed <= 0: break
                    date_str = week_dates[i]
                    
                    if emp_working_today.get(f"{emp.id}_{date_str}", False): continue
                    if i in bad_days[emp.id]: continue

                    # Find a shop that isn't over capacity
                    possible_locs = []
                    for loc in locations:
                        current = loc_day_counts.get(f"{loc.id}_{date_str}", 0)
                        max_allowed = loc_min_max[loc.id]["max"]
                        
                        if current < max_allowed and loc.id not in bad_locs[emp.id]:
                            score = 0
                            if loc.id in pref_map[emp.id]: score += 5
                            possible_locs.append((score, loc))
                    
                    if possible_locs:
                        possible_locs.sort(key=lambda x: x[0], reverse=True)
                        target_loc = possible_locs[0][1]
                        assign(emp.id, target_loc.id, date_str)
                        needed -= 1

        session.commit()
    return {"status": "ok"}

@app.post("/api/clear_week", dependencies=[Depends(get_current_admin)])
def clear_week_schedule(req: ClearWeekRequest):
    start_date = datetime.strptime(req.week_start, "%Y-%m-%d").date()
    week_dates = [(start_date + timedelta(days=i)).strftime("%Y-%m-%d") for i in range(6)]
    with Session(engine) as session:
        session.exec(delete(Shift).where(Shift.date_str >= week_dates[0], Shift.date_str <= week_dates[-1]))
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
def set_target_days(req: EmployeeTargetDaysRequest):
    with Session(engine) as session:
        existing = session.exec(select(EmployeeTargetDays).where(EmployeeTargetDays.employee_id == req.employee_id)).first()
        if existing: existing.min_days = req.min_days; existing.max_days = req.max_days; session.add(existing)
        else: session.add(EmployeeTargetDays(employee_id=req.employee_id, min_days=req.min_days, max_days=req.max_days))
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
@app.post("/api/constraints/location_target", dependencies=[Depends(get_current_admin)])
def set_location_target(req: LocationTargetRequest):
    with Session(engine) as session:
        existing = session.exec(select(LocationTarget).where(LocationTarget.location_id == req.location_id)).first()
        if existing: existing.min_employees = req.min_employees; existing.max_employees = req.max_employees; session.add(existing)
        else: session.add(LocationTarget(location_id=req.location_id, min_employees=req.min_employees, max_employees=req.max_employees))
        session.commit()
    return {"status": "ok"}

app.mount("/", StaticFiles(directory="static", html=True), name="static")
