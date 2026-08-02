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

class ChangeKind(str, enum.Enum):
    added = "added"
    price_change = "price_change"
    removed = "removed"

class SubscriptionChange(Base):
    """Append-only log of subscription changes.

    Without this the app can only ever show what a subscription costs *now* —
    it could never answer "what changed since last month", which is the whole point.
    """
    __tablename__ = "subscription_changes"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(String, nullable=False, index=True)
    subscription_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    name = Column(String, nullable=False)             # denormalised so removals still read well
    kind = Column(Enum(ChangeKind), nullable=False)
    old_monthly = Column(Float, nullable=True)        # monthly-equivalent, in entry currency
    new_monthly = Column(Float, nullable=True)
    currency = Column(String, default="AUD")
    changed_at = Column(DateTime, server_default=func.now(), index=True)

class SavingsGoal(Base):
    __tablename__ = "savings_goals"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(String, nullable=False, index=True)
    name = Column(String, nullable=False)
    target_amount = Column(Float, nullable=False)
    current_amount = Column(Float, default=0.0)
    currency = Column(String, default="AUD")
    target_date = Column(DateTime, nullable=True)
    created_by = Column(String, default="user")
    created_at = Column(DateTime, server_default=func.now())
    completed_at = Column(DateTime, nullable=True)

class UserPreference(Base):
    __tablename__ = "user_preferences"
    user_id = Column(String, primary_key=True)        # Supabase user ID
    base_currency = Column(String, default="AUD")
    monthly_income = Column(Float, nullable=True)     # in base currency; drives share-of-income
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())