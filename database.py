from sqlmodel import SQLModel, Field, create_engine, Session, select
from typing import Optional
from datetime import datetime
import os

# --- Database Configuration ---

db_user = os.getenv("DB_USER", "root")
db_password = os.getenv("DB_PASSWORD", "password")
db_host = os.getenv("DB_HOST", "192.168.1.27")
db_port = os.getenv("DB_PORT", "3306")
db_name = os.getenv("DB_NAME", "scheduler")

database_url = f"mysql+pymysql://{db_user}:{db_password}@{db_host}:{db_port}/{db_name}"
engine = create_engine(database_url, pool_recycle=3600)

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

class LocationConstraint(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    employee_id: int = Field(foreign_key="employee.id")
    location_id: int = Field(foreign_key="location.id")

class LocationPreference(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    employee_id: int = Field(foreign_key="employee.id")
    location_id: int = Field(foreign_key="location.id")

class EmployeeConstraint(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    employee_id: int = Field(foreign_key="employee.id")
    target_employee_id: int = Field(foreign_key="employee.id")

class EmployeeCoworkerPreference(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    employee_id: int = Field(foreign_key="employee.id")
    target_employee_id: int = Field(foreign_key="employee.id")

class EmployeeUnavailableDay(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    employee_id: int = Field(foreign_key="employee.id")
    day_of_week: int 

# UPDATED: Range-based Targets for Employees
class EmployeeTargetDays(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    employee_id: int = Field(foreign_key="employee.id")
    min_days: int = Field(default=0)
    max_days: int = Field(default=7)

class LocationTarget(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    location_id: int = Field(foreign_key="location.id")
    min_employees: int = Field(default=1)
    max_employees: int = Field(default=1)

class WeekStatus(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    week_start: str 
    is_published: bool = Field(default=False)
    published_at: Optional[datetime] = Field(default=None)

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
