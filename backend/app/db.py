import os

from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

raw_database_url = os.getenv(
    "DATABASE_URL",
    "postgresql+psycopg://postgres:dreams@localhost:5432/mvp1_phase1",
)

if raw_database_url.startswith("postgresql://"):
    DATABASE_URL = raw_database_url.replace("postgresql://", "postgresql+psycopg://", 1)
else:
    DATABASE_URL = raw_database_url

engine = create_engine(DATABASE_URL, pool_pre_ping=True)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()