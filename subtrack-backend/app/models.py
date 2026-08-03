from sqlalchemy import Column, String, Float, DateTime, Boolean, Enum, Integer, Text
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
    # `amount` is always what THIS user pays. For a shared bill that's their
    # share, so every total downstream stays correct without special-casing.
    amount = Column(Float, nullable=False)
    # The whole bill, when it's split with other people. Null means the user
    # pays all of it. Kept so rescans can compare receipts against the real
    # cost — comparing a receipt to someone's share would flag a price change
    # on every single scan.
    full_amount = Column(Float, nullable=True)
    share_ratio = Column(Float, default=1.0)          # amount = full_amount * share_ratio
    # How the share behaves when the bill changes:
    #   full  — no split; the user pays the whole bill
    #   ratio — an equal split (a third of the internet bill). A price rise
    #           scales the user's share automatically.
    #   fixed — an agreed uneven amount (rent split 320/320/410). A price rise
    #           must NOT silently rescale it; the housemates decide who absorbs
    #           the increase, so it surfaces for review instead.
    split_mode = Column(String, default="full")
    # Where this came from, when it was approved from an email detection.
    # Matching future scans on the display name is unreliable: the analyzer
    # writes free text, so "Anthropic (Claude)" one scan and "Anthropic Claude"
    # the next would create a duplicate. The domain + stable product key is what
    # actually identifies the same bill across scans.
    source_domain = Column(String, nullable=True, index=True)
    source_key = Column(String, nullable=True, index=True)
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

class GmailAccount(Base):
    """A connected Gmail mailbox. Stores only the refresh token, encrypted."""
    __tablename__ = "gmail_accounts"
    user_id = Column(String, primary_key=True)        # Supabase user ID
    email_address = Column(String, nullable=False)
    refresh_token_encrypted = Column(Text, nullable=False)
    connected_at = Column(DateTime, server_default=func.now())
    last_scanned_at = Column(DateTime, nullable=True)
    scan_status = Column(String, default="idle")      # idle | running | done | error
    scan_error = Column(String, nullable=True)


class DetectionStatus(str, enum.Enum):
    pending = "pending"
    approved = "approved"
    dismissed = "dismissed"


class DetectedSubscription(Base):
    """A subscription found in email, awaiting the user's verdict.

    Nothing touches the real subscriptions table until the user approves —
    email parsing is noisy, and one wrong entry makes the total untrustworthy.
    """
    __tablename__ = "detected_subscriptions"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(String, nullable=False, index=True)
    merchant = Column(String, nullable=False)
    sender_domain = Column(String, nullable=False)
    product_key = Column(String, nullable=False, default="")   # stable across scans
    category = Column(Enum(Category), default=Category.other)
    cycle = Column(Enum(BillingCycle), nullable=False)
    amount = Column(Float, nullable=False)
    currency = Column(String, default="AUD")
    previous_amount = Column(Float, nullable=True)
    cancelled = Column(Boolean, default=False)
    confidence = Column(String, default="medium")     # high | medium
    charge_count = Column(Integer, default=0)
    # Set when this looks like a price change to a subscription the user
    # already tracks; approving updates that row instead of creating one.
    existing_subscription_id = Column(UUID(as_uuid=True), nullable=True)
    # A subscription that appears to be the SAME service under a different name
    # ("Claude" vs "Anthropic"), which no amount of string matching would find.
    # Only a suggestion: the user chooses replace or keep both.
    similar_subscription_id = Column(UUID(as_uuid=True), nullable=True)
    similar_reason = Column(String, nullable=True)
    status = Column(Enum(DetectionStatus), default=DetectionStatus.pending, index=True)
    detected_at = Column(DateTime, server_default=func.now())
    resolved_at = Column(DateTime, nullable=True)

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