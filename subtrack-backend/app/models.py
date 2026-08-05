from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func
from app.database import Base
import uuid
import enum

class BillingCycle(str, enum.Enum):
    weekly = "weekly"
    monthly = "monthly"
    yearly = "yearly"


class RecurrenceUnit(str, enum.Enum):
    """Calendar unit used by the flexible cadence model.

    ``BillingCycle`` remains in the schema during the compatibility window so
    an older application instance can still read every row. New calculations
    use ``interval_unit`` + ``interval_count`` exclusively.
    """

    day = "day"
    week = "week"
    month = "month"
    year = "year"


class PaymentStatus(str, enum.Enum):
    active = "active"
    paused = "paused"
    cancelling = "cancelling"
    cancelled = "cancelled"
    ended = "ended"


class AmountType(str, enum.Enum):
    fixed = "fixed"
    variable = "variable"


class SpendingType(str, enum.Enum):
    unspecified = "unspecified"
    essential = "essential"
    optional = "optional"

class Category(str, enum.Enum):
    housing = "housing"
    insurance = "insurance"
    phone_internet = "phone_internet"
    streaming = "streaming"
    software = "software"
    cloud = "cloud"
    utilities = "utilities"
    fitness = "fitness"
    food = "food"
    transport = "transport"
    education = "education"
    childcare = "childcare"
    debt = "debt"
    memberships = "memberships"
    donations = "donations"
    business = "business"
    other = "other"

class Subscription(Base):
    __tablename__ = "subscriptions"
    __table_args__ = (
        CheckConstraint(
            "(interval_unit IS NULL AND interval_count IS NULL) OR "
            "(interval_unit IS NOT NULL AND interval_count IS NOT NULL "
            "AND interval_count >= 1 AND interval_count <= 1200)",
            name="ck_subscriptions_cadence_pair",
        ),
        CheckConstraint(
            "interval_unit IS NULL OR interval_unit IN ('day', 'week', 'month', 'year')",
            name="ck_subscriptions_interval_unit",
        ),
        CheckConstraint(
            "status IN ('active', 'paused', 'cancelling', 'cancelled', 'ended')",
            name="ck_subscriptions_status",
        ),
        CheckConstraint(
            "amount_type IN ('fixed', 'variable')",
            name="ck_subscriptions_amount_type",
        ),
        CheckConstraint(
            "spending_type IN ('unspecified', 'essential', 'optional')",
            name="ck_subscriptions_spending_type",
        ),
        Index("ix_subscriptions_user_status_due", "user_id", "status", "next_due"),
        Index("ix_subscriptions_user_active_name", "user_id", "is_active", "name"),
    )
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
    # Null means no honest server-side conversion was available. Never use 1.0
    # as a cross-currency fallback.
    exchange_rate = Column(Float, nullable=True)      # native -> stored-base rate
    converted_amount = Column(Float, nullable=True)   # amount in user's base currency
    # Legacy compatibility field. Flexible cadence is represented by the unit
    # and positive interval below; e.g. quarterly is 3 months and fortnightly
    # is 2 weeks. Do not use ``cycle`` for calculations in new code.
    cycle = Column(Enum(BillingCycle), nullable=False)
    # Nullable only for rolling-deploy compatibility with the previous backend.
    # Every create/update in the new API writes both fields; null pairs fall
    # back to the legacy cycle and can be backfilled safely.
    interval_unit = Column(String(12), nullable=True)
    interval_count = Column(Integer, nullable=True)
    next_due = Column(DateTime, nullable=True)
    recurrence_end_at = Column(DateTime, nullable=True)
    # Present when this recurring payment began as a free trial.  ``amount``
    # remains the price that will be charged after the trial; dashboards omit
    # future trials from current paid totals until this date passes.
    trial_ends_at = Column(DateTime, nullable=True)
    status = Column(String(24), nullable=False, default="active")
    paused_until = Column(DateTime, nullable=True)
    cancellation_effective_at = Column(DateTime, nullable=True)
    amount_type = Column(String(16), nullable=False, default="fixed")
    spending_type = Column(String(16), nullable=False, default="unspecified")
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, server_default=func.now())


class DuplicateDismissal(Base):
    """A user's durable decision that two tracked records are distinct.

    Pair IDs are stored in canonical lexical order by every write path. The
    uniqueness constraint makes repeated clicks and assistant action replays
    idempotent, while cascading foreign keys remove obsolete decisions when
    either tracked record is deleted or merged.
    """

    __tablename__ = "duplicate_dismissals"
    __table_args__ = (
        UniqueConstraint(
            "user_id", "subscription_a_id", "subscription_b_id",
            name="uq_duplicate_dismissals_user_pair",
        ),
        CheckConstraint(
            "subscription_a_id <> subscription_b_id",
            name="ck_duplicate_dismissals_distinct_pair",
        ),
        Index(
            "ix_duplicate_dismissals_user_created",
            "user_id", "created_at",
        ),
        Index(
            "ix_duplicate_dismissals_subscription_a",
            "subscription_a_id",
        ),
        Index(
            "ix_duplicate_dismissals_subscription_b",
            "subscription_b_id",
        ),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(String, nullable=False)
    subscription_a_id = Column(
        UUID(as_uuid=True),
        ForeignKey("subscriptions.id", ondelete="CASCADE"),
        nullable=False,
    )
    subscription_b_id = Column(
        UUID(as_uuid=True),
        ForeignKey("subscriptions.id", ondelete="CASCADE"),
        nullable=False,
    )
    created_at = Column(DateTime, nullable=False, server_default=func.now())

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
    __table_args__ = (
        Index("ix_subscription_changes_user_changed", "user_id", "changed_at"),
    )
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
    __table_args__ = (
        Index("ix_gmail_accounts_scan_heartbeat", "scan_status", "scan_heartbeat_at"),
        Index("ix_gmail_accounts_scan_started", "scan_status", "scan_started_at"),
    )
    user_id = Column(String, primary_key=True)        # Supabase user ID
    email_address = Column(String, nullable=False)
    refresh_token_encrypted = Column(Text, nullable=False)
    connected_at = Column(DateTime, server_default=func.now())
    last_scanned_at = Column(DateTime, nullable=True)
    scan_status = Column(String, default="idle")      # idle | running | done | error
    scan_error = Column(String, nullable=True)
    # ``scan_started_at`` is the real start time and never moves. Keeping the
    # heartbeat separately makes both the two-minute budget and dead-worker
    # detection reliable.
    scan_started_at = Column(DateTime, nullable=True)
    scan_heartbeat_at = Column(DateTime, nullable=True)
    scan_run_id = Column(String(36), nullable=True)
    scan_stage = Column(String(24), nullable=True)    # queued | reading | analysing | finalising
    scan_processed = Column(Integer, nullable=False, default=0)
    scan_total = Column(Integer, nullable=False, default=0)
    scan_partial = Column(Boolean, nullable=False, default=False)
    scan_message = Column(String(300), nullable=True)


class GmailOAuthState(Base):
    """One pending, authenticated Gmail connection handshake.

    The browser-visible OAuth state is stored only as a SHA-256 digest. The
    PKCE verifier is encrypted with the same deployment key as refresh tokens
    and the row is deleted before the authorization code is exchanged.
    """

    __tablename__ = "gmail_oauth_states"
    __table_args__ = (
        CheckConstraint(
            "length(state_hash) = 64",
            name="ck_gmail_oauth_states_hash_length",
        ),
        Index("ix_gmail_oauth_states_user_expires", "user_id", "expires_at"),
        Index("ix_gmail_oauth_states_expires", "expires_at"),
    )

    state_hash = Column(String(64), primary_key=True)
    user_id = Column(String, nullable=False)
    code_verifier_encrypted = Column(Text, nullable=False)
    expires_at = Column(DateTime, nullable=False)


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
    __table_args__ = (
        CheckConstraint(
            "(interval_unit IS NULL AND interval_count IS NULL) OR "
            "(interval_unit IS NOT NULL AND interval_count IS NOT NULL "
            "AND interval_count >= 1 AND interval_count <= 1200)",
            name="ck_detected_subscriptions_cadence_pair",
        ),
        CheckConstraint(
            "interval_unit IS NULL OR interval_unit IN ('day', 'week', 'month', 'year')",
            name="ck_detected_subscriptions_interval_unit",
        ),
        CheckConstraint(
            "cadence_confidence IN ('high', 'medium', 'unknown')",
            name="ck_detected_subscriptions_cadence_confidence",
        ),
        CheckConstraint(
            "due_date_confidence IN ('high', 'medium', 'unknown')",
            name="ck_detected_subscriptions_due_confidence",
        ),
        CheckConstraint(
            "amount_type IN ('fixed', 'variable')",
            name="ck_detected_subscriptions_amount_type",
        ),
        Index(
            "ix_detected_subscriptions_user_status_charge",
            "user_id", "status", "charge_count", "detected_at",
        ),
    )
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(String, nullable=False, index=True)
    merchant = Column(String, nullable=False)
    sender_domain = Column(String, nullable=False)
    product_key = Column(String, nullable=False, default="")   # stable across scans
    category = Column(Enum(Category), default=Category.other)
    # ``cycle`` remains non-null for compatibility with the previous release.
    # A detection whose cadence is unknown stores no interval unit/count and
    # must be corrected before approval; new code never treats the compatibility
    # cycle as evidence of a known cadence.
    cycle = Column(Enum(BillingCycle), nullable=False)
    interval_unit = Column(String(12), nullable=True)
    interval_count = Column(Integer, nullable=True)
    # Python writes ``unknown`` explicitly for genuinely uncertain new Gmail
    # findings. The temporary database default stays ``medium`` so a previous
    # backend binary writing only the legacy cycle during a rolling deployment
    # remains distinguishable and readable by the new release.
    cadence_confidence = Column(
        String(16), nullable=False, default="unknown", server_default="medium",
    )
    cadence_evidence = Column(String(300), nullable=True)
    next_due = Column(DateTime, nullable=True)
    due_date_confidence = Column(String(16), nullable=False, default="unknown")
    due_date_evidence = Column(String(300), nullable=True)
    amount_type = Column(String(16), nullable=False, default="fixed")
    amount = Column(Float, nullable=False)
    currency = Column(String, default="AUD")
    previous_amount = Column(Float, nullable=True)
    cancelled = Column(Boolean, default=False)
    confidence = Column(String, default="medium")     # high | medium
    charge_count = Column(Integer, default=0)
    # Gmail can identify an auto-renewing free trial before its first charge.
    # The detected row remains review-only until the user approves it.
    trial_ends_at = Column(DateTime, nullable=True)
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

class UserPreference(Base):
    __tablename__ = "user_preferences"
    user_id = Column(String, primary_key=True)        # Supabase user ID
    base_currency = Column(String, default="AUD")
    monthly_income = Column(Float, nullable=True)     # in base currency; drives share-of-income
    timezone = Column(String(64), nullable=False, default="UTC")
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())


class ExchangeRateSnapshot(Base):
    """Small shared cache of provider rates, one bounded row per base currency."""

    __tablename__ = "exchange_rate_snapshots"
    __table_args__ = (
        CheckConstraint(
            "base_currency IN ('AUD', 'USD', 'GBP', 'SGD', 'EUR', 'JPY')",
            name="ck_exchange_rate_snapshots_supported_base",
        ),
    )

    base_currency = Column(String(3), primary_key=True)
    rates = Column(JSON, nullable=False)
    provider = Column(String(32), nullable=False, default="frankfurter")
    # Frankfurter publishes the market date separately from the time Subtrack
    # fetched it (weekends commonly return Friday's market date).
    provider_date = Column(String(10), nullable=True)
    fetched_at = Column(DateTime, nullable=False)
    updated_at = Column(
        DateTime,
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


class PaymentReminder(Base):
    """An in-app reminder tied to one of the user's recurring payments.

    ``target_date`` makes trials and other one-off deadlines explicit. When it
    is null, the next occurrence is projected from the payment's existing due
    date and billing cycle, so renewal reminders continue across cycles.
    """

    __tablename__ = "payment_reminders"
    __table_args__ = (
        Index("ix_payment_reminders_user_active", "user_id", "is_active"),
        Index("ix_payment_reminders_user_subscription", "user_id", "subscription_id"),
        Index(
            "ix_payment_reminders_user_active_created",
            "user_id", "is_active", "created_at",
        ),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(String, nullable=False, index=True)
    subscription_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    kind = Column(String(24), nullable=False)  # cancel | renewal | trial_end
    days_before = Column(Integer, nullable=False, default=7)
    target_date = Column(DateTime, nullable=True)
    note = Column(String(300), nullable=True)
    is_active = Column(Boolean, nullable=False, default=True)
    dismissed_for = Column(DateTime, nullable=True)
    created_at = Column(DateTime, nullable=False, server_default=func.now())
    updated_at = Column(
        DateTime,
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


class AgentThread(Base):
    """A durable conversation owned by exactly one Subtrack user."""

    __tablename__ = "agent_threads"
    __table_args__ = (
        Index("ix_agent_threads_user_updated", "user_id", "updated_at"),
        Index(
            "ix_agent_threads_user_archived_updated",
            "user_id", "archived", "updated_at",
        ),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(String, nullable=False, index=True)
    title = Column(String(120), nullable=False, default="New conversation")
    archived = Column(Boolean, nullable=False, default=False, index=True)
    next_message_sequence = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime, nullable=False, server_default=func.now())
    updated_at = Column(
        DateTime,
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


class AgentMessage(Base):
    """A persisted user or assistant message, including interrupted replies.

    Assistant placeholders are written before the model is called. That means a
    browser refresh or a backend failure never loses the user's message, and a
    failed response can be retried without duplicating their question.
    """

    __tablename__ = "agent_messages"
    __table_args__ = (
        UniqueConstraint(
            "thread_id",
            "client_message_id",
            name="uq_agent_messages_thread_client_id",
        ),
        UniqueConstraint(
            "thread_id",
            "sequence",
            name="uq_agent_messages_thread_sequence",
        ),
        Index("ix_agent_messages_thread_sequence", "thread_id", "sequence"),
        Index("ix_agent_messages_user_thread", "user_id", "thread_id"),
        Index(
            "ix_agent_messages_user_role_created",
            "user_id", "role", "created_at",
        ),
        Index("ix_agent_messages_status_updated", "status", "updated_at"),
        Index("ix_agent_messages_reply_sequence", "reply_to_id", "sequence"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    thread_id = Column(
        UUID(as_uuid=True),
        ForeignKey("agent_threads.id", ondelete="CASCADE"),
        nullable=False,
    )
    user_id = Column(String, nullable=False, index=True)
    role = Column(String(16), nullable=False)          # user | assistant
    sequence = Column(Integer, nullable=False)
    content = Column(Text, nullable=False, default="")
    status = Column(String(16), nullable=False, default="completed")
    reply_to_id = Column(
        UUID(as_uuid=True),
        ForeignKey("agent_messages.id", ondelete="SET NULL"),
        nullable=True,
    )
    # Generated in the browser. Only user messages set it; the unique
    # constraint makes a double click or network retry safe.
    client_message_id = Column(String(64), nullable=True)
    error_code = Column(String(64), nullable=True)
    # Structured, allow-listed UI context captured with user messages.  It is
    # metadata rather than prompt text, and never grants access to a record:
    # every finance tool still scopes its query to ``user_id``.
    context_json = Column(JSON, nullable=True)
    created_at = Column(DateTime, nullable=False, server_default=func.now())
    updated_at = Column(
        DateTime,
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


class AgentAction(Base):
    """A user-confirmed mutation proposed by the financial assistant.

    The model can only create this inert proposal.  A separate authenticated
    endpoint re-validates ownership and current record state before applying
    it, which prevents a generated tool call from mutating finances directly.
    """

    __tablename__ = "agent_actions"
    __table_args__ = (
        UniqueConstraint(
            "assistant_message_id",
            "fingerprint",
            name="uq_agent_actions_message_fingerprint",
        ),
        Index("ix_agent_actions_user_status", "user_id", "status"),
        Index("ix_agent_actions_thread_created", "thread_id", "created_at"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    thread_id = Column(
        UUID(as_uuid=True),
        ForeignKey("agent_threads.id", ondelete="CASCADE"),
        nullable=False,
    )
    assistant_message_id = Column(
        UUID(as_uuid=True),
        ForeignKey("agent_messages.id", ondelete="CASCADE"),
        nullable=False,
    )
    user_id = Column(String, nullable=False, index=True)
    action_type = Column(String(48), nullable=False)
    payload_json = Column(JSON, nullable=False)
    expected_json = Column(JSON, nullable=True)
    summary = Column(String(240), nullable=False)
    description = Column(String(600), nullable=False)
    fingerprint = Column(String(64), nullable=False)
    status = Column(String(20), nullable=False, default="pending", index=True)
    result_json = Column(JSON, nullable=True)
    error_code = Column(String(64), nullable=True)
    error_message = Column(String(300), nullable=True)
    expires_at = Column(DateTime, nullable=False)
    resolved_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, nullable=False, server_default=func.now())
    updated_at = Column(
        DateTime,
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


class AgentResearchCache(Base):
    """Short-lived, user-scoped cache for cited alternative research.

    Current prices change, so this is deliberately not permanent financial
    data.  The fingerprint includes the tracked payment snapshot, market and
    user requirements; editing any of them forces fresh research.
    """

    __tablename__ = "agent_research_cache"
    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "fingerprint",
            name="uq_agent_research_cache_user_fingerprint",
        ),
        Index("ix_agent_research_cache_user_created", "user_id", "created_at"),
        Index("ix_agent_research_cache_expires", "expires_at"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(String, nullable=False, index=True)
    subscription_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    fingerprint = Column(String(64), nullable=False)
    market = Column(String(80), nullable=False)
    requirements = Column(String(500), nullable=True)
    result_json = Column(JSON, nullable=False)
    expires_at = Column(DateTime, nullable=False)
    created_at = Column(DateTime, nullable=False, server_default=func.now())
