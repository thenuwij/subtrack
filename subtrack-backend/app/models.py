from sqlalchemy import Column, String, Float, DateTime, Boolean, Enum, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func
from app.database import Base
import uuid
import enum

class BillingCycle(str, enum.Enum):
    weekly = "weekly"
    monthly = "monthly"
    yearly = "yearly"

class Category(str, enum.Enum):
    streaming = "streaming"
    software = "software"
    cloud = "cloud"
    utilities = "utilities"
    fitness = "fitness"
    food = "food"
    transport = "transport"
    other = "other"

class Subscription(Base):
    __tablename__ = "subscriptions"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(String, nullable=False, index=True)
    name = Column(String, nullable=False)
    category = Column(Enum(Category), nullable=False)
    amount = Column(Float, nullable=False)
    currency = Column(String, default="AUD")
    exchange_rate = Column(Float, default=1.0)        # rate used at time of entry
    converted_amount = Column(Float, nullable=True)   # amount in user's base currency
    cycle = Column(Enum(BillingCycle), nullable=False)
    next_due = Column(DateTime, nullable=True)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, server_default=func.now())

class Expense(Base):
    __tablename__ = "expenses"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(String, nullable=False, index=True)
    name = Column(String, nullable=False)
    category = Column(Enum(Category), nullable=False)
    amount = Column(Float, nullable=False)
    currency = Column(String, default="AUD")
    exchange_rate = Column(Float, default=1.0)        # rate used at time of entry
    converted_amount = Column(Float, nullable=True)   # amount in user's base currency
    date = Column(DateTime, nullable=False)
    note = Column(String, nullable=True)
    created_at = Column(DateTime, server_default=func.now())

class Budget(Base):
    __tablename__ = "budgets"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(String, nullable=False, index=True)
    category = Column(Enum(Category), nullable=False)
    monthly_limit = Column(Float, nullable=False)
    currency = Column(String, default="AUD")
    created_at = Column(DateTime, server_default=func.now())

class UserPreference(Base):
    __tablename__ = "user_preferences"
    user_id = Column(String, primary_key=True)        # Supabase user ID
    base_currency = Column(String, default="AUD")
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())