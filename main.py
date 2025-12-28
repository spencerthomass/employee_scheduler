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

@app.get("/api/week/{start_date_str}")
def get_week_state(start_date_str: str):
    """Returns the schedule for 7 days starting from start_date_str."""
    
    # Calculate the 7 dates in this week
    start_date = datetime.strptime(start_date_str, "%Y-%m-%d").date()
    week_dates = [(start_date + timedelta(days=i)).strftime("%Y-%m-%d") for i in range(7)]
    
    with Session(engine) as session:
        employees = session.exec(select(Employee).where(Employee.active == True)).all()
        locations = session.exec(select(Location)).all()
        
        # Get all shifts that happen in this date range
        # Note: SQLModel string comparison works for ISO dates
        shifts = session.exec(select(Shift).where(
            Shift.date_str >= week_dates[0],
            Shift.date_str <= week_dates[6]
        )).all()

        # Build the Grid: Location -> Date -> List of Employees
        # Structure: grid[location_id][date_str] = [Employee, Employee]
        grid = {}
        for loc in locations:
            grid[loc.id] = {d: [] for d in week_dates}

        for shift in shifts:
            if shift.location_id in grid and shift.date_str in grid[shift.location_id]:
                emp = next((e for e in employees if e.id == shift.employee_id), None)
                if emp:
                    grid[shift.location_id][shift.date_str].append(emp)

        return {
            "week_dates": week_dates,
            "employees": employees,
            "locations": locations,
            "grid": grid
        }

@app.post("/api/assign")
def assign_employee(req: MoveRequest):
    with Session(engine) as session:
        # 1. Ensure employee isn't already working SOMEWHERE else on this specific day
        # (Optional rule: If you want to allow re-assigning, we delete old shift first)
        existing = session.exec(select(Shift).where(
            Shift.employee_id == req.employee_id,
            Shift.date_str == req.date_str
        )).first()
        
        if existing:
            session.delete(existing)

        # 2. Add new shift
        new_shift = Shift(
            employee_id=req.employee_id,
            location_id=req.location_id,
            date_str=req.date_str
        )
        session.add(new_shift)
        session.commit()
    return {"status": "ok"}

@app.post("/api/remove")
def remove_employee(req: DeleteRequest):
    """Removes an employee from a specific day."""
    with Session(engine) as session:
        statement = delete(Shift).where(
            Shift.employee_id == req.employee_id, 
            Shift.date_str == req.date_str
        )
        session.exec(statement)
        session.commit()
    return {"status": "ok"}

app.mount("/", StaticFiles(directory="static", html=True), name="static")
