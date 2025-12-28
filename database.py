from sqlmodel import SQLModel, Field, create_engine, Session, select
from typing import Optional
import os

# --- Database Configuration ---
os.makedirs("data", exist_ok=True)
sqlite_file_name = "data/scheduler.db"
sqlite_url = f"sqlite:///{sqlite_file_name}"

connect_args = {"check_same_thread": False}
engine = create_engine(sqlite_url, connect_args=connect_args)

# --- Models ---

class Employee(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str
    active: bool = Field(default=True)

class Location(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str

class Shift(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    date_str: str
    employee_id: int = Field(foreign_key="employee.id")
    location_id: int = Field(foreign_key="location.id")

# NEW: Tracks locations an employee cannot/should not work at
class LocationConstraint(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    employee_id: int = Field(foreign_key="employee.id")
    location_id: int = Field(foreign_key="location.id")

# NEW: Tracks incompatible employees (One-way reference for simplicity, checked both ways in logic)
class EmployeeConstraint(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    employee_id: int = Field(foreign_key="employee.id")
    target_employee_id: int = Field(foreign_key="employee.id")

# --- Setup ---

def create_db_and_tables():
    SQLModel.metadata.create_all(engine)

def seed_data():
    with Session(engine) as session:
        if not session.exec(select(Location)).first():
            locs = ["Sandy", "Lehi", "Provo", "Orem", "SLC Downtown", "West Jordan", "Draper", "Murray", "Bountiful", "Ogden"]
            for l in locs: session.add(Location(name=l))
            
            emps = ["John", "Sarah", "Mike", "Steve", "Amy", "Tucker", "Rosie", "Bill", "Ted", "Lisa"]
            for e in emps: session.add(Employee(name=e))
            
            session.commit()
