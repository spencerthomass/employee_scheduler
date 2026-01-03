from sqlmodel import SQLModel, create_engine
import os

# --- Database Configuration ---

# Get credentials from Environment Variables (set in docker-compose)
db_user = os.getenv("DB_USER", "root")
db_password = os.getenv("DB_PASSWORD", "password")
db_host = os.getenv("DB_HOST", "192.168.1.27")
db_port = os.getenv("DB_PORT", "3306")
db_name = os.getenv("DB_NAME", "scheduler")

# Construct the MySQL Connection URL
# Format: mysql+pymysql://user:password@host:port/database
database_url = f"mysql+pymysql://{db_user}:{db_password}@{db_host}:{db_port}/{db_name}"

# Create the engine
# pool_recycle is important for MySQL to prevent "Goldfish memory" (connection timeouts)
engine = create_engine(database_url, pool_recycle=3600)

# --- Setup ---

def create_db_and_tables():
    # This will create tables if they don't exist, 
    # BUT the database itself (e.g. 'scheduler') must already exist on your SQL server.
    SQLModel.metadata.create_all(engine)

# Note: The 'seed_data' function and Models are imported by main.py, 
# so we don't need to repeat the Model definitions here if main.py imports them from a models file.
# However, based on our previous single-file structure, I will include the import placeholders 
# so main.py doesn't break. 

# ... (The Models remain exactly the same as before. 
#      You do not need to change the Model classes, just the engine setup above.)
