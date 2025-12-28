from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from sqlmodel import Session, select, delete
from database import engine, create_db_and_tables, seed_data, Employee, Location, Shift
from pydantic import BaseModel

app = FastAPI()

# Initialize DB on startup
@app.on_event("startup")
def on_startup():
    create_db_and_tables()
    seed_data()

# Data models for API requests
class MoveRequest(BaseModel):
    employee_id: int
    date_str: str
    location_id: int | None = None # If None, move to Bench

# --- APIs ---

@app.get("/api/state/{date_str}")
def get_state(date_str: str):
    """Returns the board state for a specific day."""
    with Session(engine) as session:
        employees = session.exec(select(Employee).where(Employee.active == True)).all()
        locations = session.exec(select(Location)).all()
        shifts = session.exec(select(Shift).where(Shift.date_str == date_str)).all()

        # Organize data
        location_map = {l.id: {"id": l.id, "name": l.name, "staff": []} for l in locations}
        assigned_ids = set()

        for shift in shifts:
            emp = next((e for e in employees if e.id == shift.employee_id), None)
            if emp and shift.location_id in location_map:
                location_map[shift.location_id]["staff"].append(emp)
                assigned_ids.add(emp.id)

        # Anyone not assigned is on the "Bench"
        bench = [e for e in employees if e.id not in assigned_ids]

        return {
            "bench": bench,
            "locations": list(location_map.values())
        }

@app.post("/api/move")
def move_employee(req: MoveRequest):
    """Moves an employee to a shop OR to the bench."""
    with Session(engine) as session:
        # 1. Remove existing shift for this day (if any)
        statement = delete(Shift).where(
            Shift.employee_id == req.employee_id, 
            Shift.date_str == req.date_str
        )
        session.exec(statement)

        # 2. If a location is provided, create a new shift
        if req.location_id is not None:
            new_shift = Shift(
                employee_id=req.employee_id,
                location_id=req.location_id,
                date_str=req.date_str
            )
            session.add(new_shift)
        
        session.commit()
    return {"status": "ok"}

# Serve the Frontend
app.mount("/", StaticFiles(directory="static", html=True), name="static")