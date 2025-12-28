from sqlmodel import SQLModel, Field, create_engine, Session, select
from typing import Optional
import os

# --- Database Configuration ---
# This ensures the 'data' folder exists before trying to create the DB file.
# This is crucial for Docker volume mapping.
os.makedirs("data", exist_ok=True)
sqlite_file_name = "data/scheduler.db"
sqlite_url = f"sqlite:///{sqlite_file_name}"

# Connect args needed for SQLite to handle concurrent writes better
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
    date_str: str  # Stored as "YYYY-MM-DD"
    employee_id: int = Field(foreign_key="employee.id")
    location_id: int = Field(foreign_key="location.id")

# --- Database Setup Functions ---

def create_db_and_tables():
    """Creates the database tables if they don't exist."""
    SQLModel.metadata.create_all(engine)

def seed_data():
    """Populates the DB with initial data if it's empty."""
    with Session(engine) as session:
        # Check if locations exist; if not, seed them
        if not session.exec(select(Location)).first():
            print("Seeding initial data...")
            
            # Add Shops (Your 10 locations)
            # You can edit these names here before the first run
            locs = [
                "Sandy", "Lehi", "Provo", "Orem", "SLC Downtown", 
                "West Jordan", "Draper", "Murray", "Bountiful", "Ogden"
            ]
            for l in locs:
                session.add(Location(name=l))
            
            # Add Employees (Dummy data to get you started)
            emps = [
                "John", "Sarah", "Mike", "Steve", "Amy", 
                "Tucker", "Rosie", "Bill", "Ted", "Lisa"
            ]
            for e in emps:
                session.add(Employee(name=e))
            
            session.commit()
            print("Seeding complete.")