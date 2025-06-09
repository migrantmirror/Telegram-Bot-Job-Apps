from sqlalchemy import (
    Column, String, Integer, Boolean, DateTime, ForeignKey, Text
)
from sqlalchemy.orm import declarative_base, relationship
from datetime import datetime

Base = declarative_base()

class User(Base):
    __tablename__ = "users"
    user_id = Column(Integer, primary_key=True)  # Telegram user_id
    username = Column(String)
    first_name = Column(String)
    last_name = Column(String)

    applications = relationship("JobApplication", back_populates="user")

class JobApplication(Base):
    __tablename__ = "job_applications"
    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.user_id"))
    company_email = Column(String, nullable=False)
    job_title = Column(String)
    date_applied = Column(DateTime, default=datetime.utcnow)
    email_status = Column(String)
    cv_file_path = Column(String)  # local path or cloud URL
    notes = Column(Text)

    user = relationship("User", back_populates="applications")
    reminders = relationship("Reminder", back_populates="application")

class Reminder(Base):
    __tablename__ = "reminders"
    id = Column(Integer, primary_key=True, autoincrement=True)
    application_id = Column(Integer, ForeignKey("job_applications.id"))
    remind_at = Column(DateTime, nullable=False)
    is_sent = Column(Boolean, default=False)

    application = relationship("JobApplication", back_populates="reminders")
