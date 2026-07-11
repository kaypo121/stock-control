from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker
from sqlalchemy.pool import StaticPool

from app.config import DATABASE_URL

# Connect arguments needed for SQLite to avoid thread-sharing errors
connect_args = {}
engine_options = {}
if DATABASE_URL.startswith("sqlite"):
    connect_args = {"check_same_thread": False}
    # SQLite in-memory databases are scoped to a connection. A static pool
    # keeps the application lifespan and request sessions on the same database.
    if DATABASE_URL == "sqlite:///:memory:":
        engine_options["poolclass"] = StaticPool

engine = create_engine(DATABASE_URL, connect_args=connect_args, **engine_options)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


# FastAPI Dependency for Session injection
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
