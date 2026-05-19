from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session, declarative_base
from src.core.config import settings
import time

MAX_RETRIES = 10
RETRY_DELAY = 3

SQLALCHEMY_DATABASE_URL = settings.DATABASE_URL

engine = None

# ✅ Retry logic for DB connection
for attempt in range(MAX_RETRIES):
    try:
        print(f"⏳ Attempting DB connection ({attempt + 1}/{MAX_RETRIES})...")

        engine = create_engine(
            SQLALCHEMY_DATABASE_URL,
            pool_pre_ping=True,  # 🔥 important for stale connections
        )

        # Try connecting
        with engine.connect() as connection:
            print("✅ Database connected successfully!")
        
        break

    except Exception as e:
        print(f"❌ DB connection failed: {e}")
        time.sleep(RETRY_DELAY)

else:
    raise Exception("🚨 Could not connect to the database after multiple attempts")

# ✅ Session setup
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# ✅ Base model
Base = declarative_base()


# ✅ Dependency
def get_db():
    db: Session = SessionLocal()
    try:
        yield db
    finally:
        db.close()