from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

DATABASE_URL = "postgresql://postgres:yazid2002@localhost:5432/heart_disease_db"

def add_unique_constraint():
    engine = create_engine(DATABASE_URL)
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    db = SessionLocal()
    
    try:
        # First, clean up any duplicate assignments (keep the most recent)
        db.execute(text("""
            DELETE FROM doctors d1 USING doctors d2 
            WHERE d1.assigned_to = d2.assigned_to 
            AND d1.id > d2.id 
            AND d1.assigned_to IS NOT NULL
        """))
        
        # Add unique constraint
        db.execute(text("""
            ALTER TABLE doctors 
            ADD CONSTRAINT unique_assigned_to UNIQUE (assigned_to)
        """))
        
        db.commit()
        print("✅ Unique constraint added successfully")
    except Exception as e:
        db.rollback()
        print(f"❌ Error: {e}")
    finally:
        db.close()

if __name__ == "__main__":
    add_unique_constraint()