from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from sqlmodel import Session, select, delete
from database import engine, create_db_and_tables, seed_data, Employee, Location, Shift
from pydantic import BaseModel
from datetime import datetime, timedelta

app = FastAPI()

@app.on_event("startup")
def on_startup():
    create_db_and_tables()
    seed_data()

class MoveRequest(BaseModel):
    employee_id: int
    date_str: str
    location_id: int

class DeleteRequest(BaseModel):
    employee_id: int
    date_str: str

# --- APIs ---

@app.get("/api/roster/{start_date_str}")
def get_roster_state(start_date_str: str):
    """Returns the schedule organized by Employee for the week."""
    
    # Calculate the 7 dates
    start_date = datetime.strptime(start_date_str, "%Y-%m-%d").date()
    week_dates = [(start_date + timedelta(days=i)).strftime("%Y-%m-%d") for i in range(7)]
    
    with Session(engine) as session:
        employees = session.exec(select(Employee).where(Employee.active == True)).all()
        locations = session.exec(select(Location)).all()
        
        # Get shifts for this week
        shifts = session.exec(select(Shift).where(
            Shift.date_str >= week_dates[0],
            Shift.date_str <= week_dates[6]
        )).all()

        # Build Grid: grid[employee_id][date_str] = Location object
        grid = {e.id: {d: None for d in week_dates} for e in employees}
        
        # Helper map to look up location details quickly
        loc_map = {l.id: l for l in locations}

        for shift in shifts:
            if shift.employee_id in grid and shift.date_str in grid[shift.employee_id]:
                if shift.location_id in loc_map:
                    grid[shift.employee_id][shift.date_str] = loc_map[shift.location_id]

        return {
            "week_dates": week_dates,
            "employees": employees,
            "locations": locations,
            "grid": grid
        }

@app.post("/api/assign")
def assign_shift(req: MoveRequest):
    with Session(engine) as session:
        # 1. Delete any existing shift for this employee on this day
        # (This allows overwriting: Dragging "Lehi" onto "Sandy" replaces it)
        existing = session.exec(select(Shift).where(
            Shift.employee_id == req.employee_id,
            Shift.date_str == req.date_str
        )).first()
        
        if existing:
            session.delete(existing)

        # 2. Add the new shift
        new_shift = Shift(
            employee_id=req.employee_id,
            location_id=req.location_id,
            date_str=req.date_str
        )
        session.add(new_shift)
        session.commit()
    return {"status": "ok"}

@app.post("/api/remove")
def remove_shift(req: DeleteRequest):
    with Session(engine) as session:
        statement = delete(Shift).where(
            Shift.employee_id == req.employee_id, 
            Shift.date_str == req.date_str
        )
        session.exec(statement)
        session.commit()
    return {"status": "ok"}

app.mount("/", StaticFiles(directory="static", html=True), name="static")
