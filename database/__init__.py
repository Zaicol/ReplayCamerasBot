from .models import Base
from .db_engine import engine, SessionLocal
from .queries import *

Base.metadata.create_all(engine)
