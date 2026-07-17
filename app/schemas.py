from datetime import datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

PaymentPhoneVisibility = Literal["nobody", "event_members", "friends"]
SplitStrategy = Literal[
    "equal_default",
    "itemized_creator",
    "itemized_self_select",
    "agent_assisted",
]
ReceiptCreationPolicy = Literal["creator_only", "participants_can_add"]
ReceiptFinalizationPolicy = Literal[
    "creator_finalizes",
    "payer_finalizes",
    "all_involved_confirm",
]
ParticipantsInvitePolicy = Literal[
    "creator_only",
    "participants_can_invite_with_approval",
    "participants_can_invite_directly",
]
DebtDisplayMode = Literal["simplified_default", "raw_default", "show_both"]
SettlementDeadlinePolicy = Literal[
    "disabled",
    "soft_deadline",
    "strict_deadline_with_reliability_score",
]
SafetyPolicy = Literal["explicit_review"]
DisputeResourceType = Literal["receipt", "payment", "payment_request"]
SplitikMode = Literal["general", "event", "receipt", "member"]
ClientReportKind = Literal["automatic_error", "manual_feedback"]
ClientReportSeverity = Literal["info", "warning", "error", "critical"]
SettlementPlanStatus = Literal[
    "pending",
    "approved",
    "rejected",
    "stale",
    "expired",
    "executing",
    "partially_settled",
    "completed",
]
ClientReportScreen = Literal[
    "home",
    "events",
    "people",
    "notifications",
    "profile",
    "splitik",
    "receipts",
    "payments",
    "unknown",
]


class User(BaseModel):
    id: UUID
    name: str
    phone_number: str
    email: str | None = None
    first_name: str | None = None
    last_name: str | None = None
    sex: str | None = None
    birthday: str | None = None
    avatar_url: str | None = None
    public_handle: str | None = None
    discovery_enabled: bool = False
    payment_phone: str | None = None
    phone_verified: bool = False
    payment_phone_visibility: PaymentPhoneVisibility = "nobody"


class PublicUser(BaseModel):
    id: UUID
    name: str
    avatar_url: str | None = None
    public_handle: str | None = None


class UserPage(BaseModel):
    items: list[User]
    limit: int
    offset: int
    total: int


class UserFinancialStats(BaseModel):
    open_events_count: int
    closed_events_count: int
    outstanding_owed_kopecks: int
    outstanding_receivable_kopecks: int


class HomeMoneyBucket(BaseModel):
    owed_kopecks: int
    receivable_kopecks: int


class HomeSummary(BaseModel):
    confirmed: HomeMoneyBucket
    pending: HomeMoneyBucket
    disputed: HomeMoneyBucket


class FriendRequestCreate(BaseModel):
    user_id: UUID


class Friendship(BaseModel):
    id: UUID
    requester_id: UUID
    addressee_id: UUID
    status: str
    peer: User | None = None
    created_at: datetime
    updated_at: datetime


class FriendshipPage(BaseModel):
    items: list[Friendship]
    limit: int
    offset: int
    total: int


class FriendInvite(BaseModel):
    id: UUID
    creator: User
    token: str
    invite_url: str
    status: str
    expires_at: datetime
    created_at: datetime


class FriendInvitePreview(BaseModel):
    id: UUID
    creator: PublicUser
    expires_at: datetime


class FriendInviteTokenRequest(BaseModel):
    token: str = Field(min_length=43, max_length=43, pattern=r"^[A-Za-z0-9_-]+$")


class UserUpdate(BaseModel):
    name: str | None = Field(default=None, max_length=120)
    email: str | None = Field(default=None, max_length=254)
    avatar_url: str | None = Field(default=None, max_length=500)
    public_handle: str | None = None
    discovery_enabled: bool | None = None
    payment_phone: str | None = Field(default=None, max_length=32)
    payment_phone_visibility: PaymentPhoneVisibility | None = None


class LoginYandexRequest(BaseModel):
    yandex_token: str = Field(min_length=1)


class ContactImportItem(BaseModel):
    display_name: str = Field(min_length=1, max_length=120)
    phone_numbers: list[str] = Field(min_length=1, max_length=10)


class ContactImportRequest(BaseModel):
    contacts: list[ContactImportItem] = Field(min_length=1, max_length=1000)


class UserContactMatchedUser(User):
    display_name: str


class UserContact(BaseModel):
    id: UUID
    owner_user_id: UUID
    display_name: str
    phone_number: str
    phone_hash: str
    matched_user_id: UUID | None = None
    matched_user: UserContactMatchedUser | None = None
    created_at: datetime
    updated_at: datetime


class UserContactPage(BaseModel):
    items: list[UserContact]
    limit: int
    offset: int
    total: int


class ContactImportResponse(BaseModel):
    imported: int
    matched: int
    skipped: int
    items: list[UserContact]


class LoginResponse(BaseModel):
    user: User
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int = Field(description="Access token lifetime in seconds.")


class RefreshRequest(BaseModel):
    refresh_token: str = Field(min_length=1)


class RefreshResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int = Field(description="Access token lifetime in seconds.")


class EventCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    split_strategy: SplitStrategy = "equal_default"
    receipt_creation_policy: ReceiptCreationPolicy = "participants_can_add"
    receipt_finalization_policy: ReceiptFinalizationPolicy = "payer_finalizes"
    participants_invite_policy: ParticipantsInvitePolicy = "creator_only"
    debt_display_mode: DebtDisplayMode = "simplified_default"
    settlement_deadline_policy: SettlementDeadlinePolicy = "disabled"
    review_window_seconds: int = Field(default=60 * 60 * 24, ge=300, le=60 * 60 * 24 * 30)
    safety_policy: SafetyPolicy = "explicit_review"
    auto_confirm_on_timeout: bool = False


class EventUpdate(BaseModel):
    name: str | None = Field(default=None, max_length=120)
    is_closed: bool | None = None
    split_strategy: SplitStrategy | None = None
    receipt_creation_policy: ReceiptCreationPolicy | None = None
    receipt_finalization_policy: ReceiptFinalizationPolicy | None = None
    participants_invite_policy: ParticipantsInvitePolicy | None = None
    debt_display_mode: DebtDisplayMode | None = None
    settlement_deadline_policy: SettlementDeadlinePolicy | None = None
    review_window_seconds: int | None = Field(default=None, ge=300, le=60 * 60 * 24 * 30)
    safety_policy: SafetyPolicy | None = None
    auto_confirm_on_timeout: bool | None = None


class EventMembership(BaseModel):
    id: UUID
    event_id: UUID
    user_id: UUID
    role: str
    status: str
    joined_at: datetime
    removed_at: datetime | None = None


class Event(BaseModel):
    id: UUID
    creator_id: UUID
    name: str
    is_closed: bool
    split_strategy: SplitStrategy = "equal_default"
    receipt_creation_policy: ReceiptCreationPolicy = "participants_can_add"
    receipt_finalization_policy: ReceiptFinalizationPolicy = "payer_finalizes"
    participants_invite_policy: ParticipantsInvitePolicy = "creator_only"
    debt_display_mode: DebtDisplayMode = "simplified_default"
    settlement_deadline_policy: SettlementDeadlinePolicy = "disabled"
    review_window_seconds: int = 60 * 60 * 24
    safety_policy: SafetyPolicy = "explicit_review"
    auto_confirm_on_timeout: bool = False
    participants: list[EventMembership]
    created_at: datetime
    updated_at: datetime


class EventPage(BaseModel):
    items: list[Event]
    limit: int
    offset: int
    total: int


class AddParticipantsRequest(BaseModel):
    user_ids: list[UUID] = Field(min_length=1)


class CreateEventInviteRequest(BaseModel):
    expires_in_seconds: int = Field(default=60 * 60 * 24 * 7, ge=60, le=60 * 60 * 24 * 30)
    addressee_id: UUID | None = None


class EventInvite(BaseModel):
    id: UUID
    event_id: UUID
    token: str
    invite_url: str
    status: str
    created_by: UUID
    expires_at: datetime
    created_at: datetime
    accepted_by: UUID | None = None
    accepted_at: datetime | None = None
    revoked_at: datetime | None = None


class EventInvitePreview(BaseModel):
    event_id: UUID
    event_name: str
    creator_id: UUID
    expires_at: datetime
    participant_count: int
    actor_decision: str | None = None


class EventInvitationInboxItem(BaseModel):
    id: UUID
    token: str
    event_id: UUID
    event_name: str
    created_by: UUID
    creator_name: str
    expires_at: datetime
    created_at: datetime


class EventInvitationInboxPage(BaseModel):
    items: list[EventInvitationInboxItem]
    limit: int
    offset: int
    total: int


class CreateShareItemRequest(BaseModel):
    user_id: UUID
    share_value: Decimal = Field(gt=0, le=1)


class ShareItem(BaseModel):
    id: UUID
    receipt_item_id: UUID
    user_id: UUID
    share_value: Decimal = Field(gt=0, le=1)


class CreateReceiptItemRequest(BaseModel):
    name: str = Field(default="", max_length=160)
    cost_kopecks: int = Field(gt=0)
    split_mode: str = "custom"
    share_items: list[CreateShareItemRequest] = Field(min_length=1)


class ReceiptItem(BaseModel):
    id: UUID
    receipt_id: UUID
    name: str = ""
    cost_kopecks: int
    split_mode: str = "custom"
    share_items: list[UUID]


class CreateReceiptRequest(BaseModel):
    payer_id: UUID
    title: str = Field(default="", max_length=160)
    category: str | None = None
    total_amount_kopecks: int = Field(gt=0)
    items: list[CreateReceiptItemRequest] = Field(min_length=1)
    discount_amount_kopecks: int = 0
    service_fee_amount_kopecks: int = 0
    delivery_fee_amount_kopecks: int = 0
    tip_amount_kopecks: int = 0
    rounding_adjustment_kopecks: int = 0
    fiscal_total_amount_kopecks: int | None = None
    vat_amount_kopecks: int | None = None


class ReceiptAIDraftRequest(BaseModel):
    source_text: str = Field(min_length=1, max_length=12000)
    payer_id: UUID | None = None
    locale: str = "ru-RU"
    timezone: str = "Europe/Moscow"


class ReceiptAIModelResult(BaseModel):
    model_role: str
    model_id: str
    payload: CreateReceiptRequest | None = None
    warnings: list[str] = []


class ReceiptAIDraftResponse(BaseModel):
    id: UUID
    event_id: UUID
    owner_user_id: UUID
    status: str
    model_status: str
    needs_human_review: bool
    draft_payload: CreateReceiptRequest
    primary_result: ReceiptAIModelResult
    verification_result: ReceiptAIModelResult
    escalation_result: ReceiptAIModelResult | None = None
    disagreements: list[str] = []
    created_at: datetime
    updated_at: datetime


class UpdateReceiptRequest(BaseModel):
    title: str | None = Field(default=None, max_length=160)
    category: str | None = None
    total_amount_kopecks: int | None = Field(default=None, gt=0)
    items: list[CreateReceiptItemRequest] | None = None
    expected_version: int | None = Field(default=None, ge=1)
    discount_amount_kopecks: int | None = None
    service_fee_amount_kopecks: int | None = None
    delivery_fee_amount_kopecks: int | None = None
    tip_amount_kopecks: int | None = None
    rounding_adjustment_kopecks: int | None = None
    fiscal_total_amount_kopecks: int | None = None
    vat_amount_kopecks: int | None = None


class Receipt(BaseModel):
    id: UUID
    event_id: UUID
    payer_id: UUID
    title: str = ""
    category: str | None = None
    status: str
    version: int
    total_amount_kopecks: int
    discount_amount_kopecks: int = 0
    service_fee_amount_kopecks: int = 0
    delivery_fee_amount_kopecks: int = 0
    tip_amount_kopecks: int = 0
    rounding_adjustment_kopecks: int = 0
    fiscal_total_amount_kopecks: int | None = None
    vat_amount_kopecks: int | None = None
    created_at: datetime
    updated_at: datetime
    items: list[ReceiptItem]
    image_url: str | None = None
    corrected_from_receipt_id: UUID | None = None
    review_window_expires_at: datetime | None = None


class ReceiptPage(BaseModel):
    items: list[Receipt]
    limit: int
    offset: int
    total: int


class ReceiptShareReview(BaseModel):
    id: UUID
    event_id: UUID
    receipt_id: UUID
    user_id: UUID
    status: str
    reason: str = ""
    created_at: datetime
    updated_at: datetime
    decided_at: datetime | None = None


class ReceiptShareReviewPage(BaseModel):
    items: list[ReceiptShareReview]
    limit: int
    offset: int
    total: int


class ReceiptShareReviewDispute(BaseModel):
    reason: str = Field(min_length=1, max_length=1000)


class ConfirmationSummary(BaseModel):
    resource_type: str
    resource_id: UUID
    action: str
    title: str
    amount_kopecks: int | None = None
    status: str
    actor_user_id: UUID
    requires_explicit_confirmation: bool = True
    warnings: list[str] = []


class AllocationSession(BaseModel):
    id: UUID
    event_id: UUID
    receipt_id: UUID
    status: str
    created_by: UUID
    created_at: datetime
    updated_at: datetime


class ReceiptItemClaimRequest(BaseModel):
    receipt_item_id: UUID


class ReceiptItemClaim(BaseModel):
    id: UUID
    session_id: UUID
    receipt_id: UUID
    receipt_item_id: UUID
    user_id: UUID
    status: str
    created_at: datetime


class AllocationSessionState(BaseModel):
    session: AllocationSession
    claims: list[ReceiptItemClaim]


class ReceiptImageUploadResponse(BaseModel):
    image_url: str


class ReceiptImagePresignedUrlResponse(BaseModel):
    image_url: str


class PaymentCreate(BaseModel):
    sender_id: UUID
    receiver_id: UUID
    amount_kopecks: int = Field(gt=0)


class PaymentUpdate(BaseModel):
    confirmed: bool


class Payment(BaseModel):
    id: UUID
    event_id: UUID
    sender_id: UUID
    receiver_id: UUID
    amount_kopecks: int
    status: str
    confirmed: bool
    created_at: datetime
    payment_request_id: UUID | None = None
    rejected_at: datetime | None = None


class PaymentPage(BaseModel):
    items: list[Payment]
    limit: int
    offset: int
    total: int


class PaymentRequestCreate(BaseModel):
    debtor_id: UUID
    creditor_id: UUID
    amount_kopecks: int = Field(gt=0)
    note: str = Field(default="", max_length=500)
    deadline_at: datetime | None = None


class PaymentRequest(BaseModel):
    id: UUID
    event_id: UUID
    debtor_id: UUID
    creditor_id: UUID
    amount_kopecks: int
    note: str = ""
    status: str
    created_by: UUID
    created_at: datetime
    updated_at: datetime
    payment_id: UUID | None = None
    deadline_at: datetime | None = None
    acknowledged_at: datetime | None = None
    cancelled_at: datetime | None = None
    disputed_at: datetime | None = None
    extension_requested_at: datetime | None = None
    origin: str | None = None
    settlement_plan_id: UUID | None = None
    settlement_edge_id: UUID | None = None


class PaymentRequestPage(BaseModel):
    items: list[PaymentRequest]
    limit: int
    offset: int
    total: int


class DisputeCreate(BaseModel):
    resource_type: DisputeResourceType
    resource_id: UUID
    reason: str = Field(min_length=1, max_length=1000)


class DisputeResolve(BaseModel):
    resolution_note: str = Field(default="", max_length=1000)


class Dispute(BaseModel):
    id: UUID
    event_id: UUID
    resource_type: str
    resource_id: UUID
    reason: str
    status: str
    created_by: UUID
    created_at: datetime
    updated_at: datetime
    resolved_by: UUID | None = None
    resolved_at: datetime | None = None
    resolution_note: str = ""


class DisputePage(BaseModel):
    items: list[Dispute]
    limit: int
    offset: int
    total: int


class AuditEvent(BaseModel):
    id: UUID
    action: str
    resource_type: str
    resource_id: str
    actor_user_id: UUID
    created_at: datetime


class AuditEventPage(BaseModel):
    items: list[AuditEvent]
    limit: int
    offset: int
    total: int


class ClientReportCreate(BaseModel):
    kind: ClientReportKind
    severity: ClientReportSeverity = "warning"
    screen: ClientReportScreen = "unknown"
    message: str = Field(min_length=1, max_length=500)
    user_description: str | None = Field(default=None, max_length=2000)
    request_id: str | None = Field(default=None, max_length=120)
    client_trace_id: str | None = Field(default=None, max_length=120)
    app_version: str | None = Field(default=None, max_length=80)
    url_path: str | None = Field(default=None, max_length=240)
    user_agent: str | None = Field(default=None, max_length=500)
    online: bool | None = None
    contact_allowed: bool = False
    contact: str | None = Field(default=None, max_length=160)
    metadata: dict = Field(default_factory=dict)


class ClientReport(BaseModel):
    id: UUID
    kind: ClientReportKind
    severity: ClientReportSeverity
    screen: ClientReportScreen
    message: str
    user_description: str | None = None
    request_id: str | None = None
    client_trace_id: str | None = None
    app_version: str | None = None
    url_path: str | None = None
    user_agent: str | None = None
    online: bool | None = None
    contact_allowed: bool
    contact: str | None = None
    metadata: dict
    actor_user_id: UUID | None = None
    client_ip: str | None = None
    source: str
    status: str
    created_at: datetime


class ClientReportCreateResponse(BaseModel):
    id: UUID
    status: str
    friendly_message: str


class EventBalance(BaseModel):
    event_id: UUID
    debitor_id: UUID
    creditor_id: UUID
    amount_kopecks: int


class BalanceContribution(BaseModel):
    source_type: str
    source_id: UUID
    debitor_id: UUID
    creditor_id: UUID
    amount_kopecks: int
    description: str


class EventBalanceExplanation(EventBalance):
    contributions: list[BalanceContribution]


class SettlementNetPosition(BaseModel):
    user_id: UUID
    direction: Literal["owes", "receives"]
    amount_kopecks: int = Field(gt=0)


class SettlementTransfer(BaseModel):
    debtor_id: UUID
    creditor_id: UUID
    amount_kopecks: int = Field(gt=0)


class SettlementPreview(BaseModel):
    event_id: UUID
    raw_debts: list[EventBalanceExplanation]
    net_positions: list[SettlementNetPosition]
    recommended_transfers: list[SettlementTransfer]
    source_participant_ids: list[UUID]
    original_transfer_count: int = Field(ge=0)
    recommended_transfer_count: int = Field(ge=0)
    original_gross_kopecks: int = Field(ge=0)
    recommended_total_kopecks: int = Field(ge=0)
    transfer_count_reduced: bool


class SettlementPlanApproval(BaseModel):
    user_id: UUID
    approved_at: datetime


class SettlementPlanEdge(BaseModel):
    edge_id: UUID
    debtor_id: UUID
    creditor_id: UUID
    amount_kopecks: int = Field(gt=0)
    payment_request_id: UUID | None = None
    status: str | None = None


class SettlementPlan(BaseModel):
    id: UUID
    event_id: UUID
    status: SettlementPlanStatus
    algorithm_version: Literal["greedy-net-v1"]
    preview: SettlementPreview
    edges: list[SettlementPlanEdge]
    required_approver_ids: list[UUID]
    approvals: list[SettlementPlanApproval]
    created_by: UUID
    expires_at: datetime
    created_at: datetime
    updated_at: datetime
    rejected_by: UUID | None = None
    rejection_reason: str | None = None
    rejected_at: datetime | None = None


class SettlementPlanPage(BaseModel):
    items: list[SettlementPlan]
    limit: int
    offset: int
    total: int


class SettlementPlanReject(BaseModel):
    reason: str = Field(min_length=1, max_length=500)


class SplitikEntryPoint(BaseModel):
    type: SplitikMode = "general"
    event_id: UUID | None = None
    receipt_id: UUID | None = None
    target_user_id: UUID | None = None


class SplitikAttachmentProcessing(BaseModel):
    status: str
    selected_variant: str
    source_width: int | None = None
    source_height: int | None = None
    width: int | None = None
    height: int | None = None
    quality_flags: list[str] = []
    operations: list[str] = []
    brightness: float | None = None
    contrast: float | None = None
    sharpness: float | None = None
    duration_ms: float | None = None


class SplitikAttachment(BaseModel):
    id: UUID
    filename: str
    content_type: str
    size_bytes: int
    processing: SplitikAttachmentProcessing | None = None
    created_at: datetime


class SplitikMessageRequest(BaseModel):
    session_id: UUID | None = None
    mode: SplitikMode = "general"
    message: str = Field(min_length=1, max_length=8000)
    entry_point: SplitikEntryPoint | None = None
    attachment_ids: list[UUID] = Field(default_factory=list)
    locale: str = "ru-RU"
    timezone: str = "Europe/Moscow"


class SplitikContextChip(BaseModel):
    type: str
    label: str
    value: str


class SplitikGuardrailDecision(BaseModel):
    allowed: bool
    reason: str
    message: str = ""


class SplitikQuestion(BaseModel):
    id: str
    text: str
    required: bool = True


class SplitikSuggestedAction(BaseModel):
    type: str
    label: str
    draft_id: UUID | None = None


class SplitikDraft(BaseModel):
    id: UUID
    type: str
    status: str
    payload: dict
    event_id: UUID | None = None
    session_id: UUID | None = None
    version: int = 1
    source: str = "text"
    attachment_ids: list[UUID] = Field(default_factory=list)
    questions: list[dict] = Field(default_factory=list)
    model_metadata: dict = Field(default_factory=dict)
    created_at: datetime
    updated_at: datetime | None = None
    committed_at: datetime | None = None
    committed_resource_id: UUID | None = None


class SplitikDraftUpdateRequest(BaseModel):
    payload: dict = Field(default_factory=dict)


class SplitikMessageResponse(BaseModel):
    session_id: UUID
    message_id: UUID
    assistant_message: str
    mode: str
    intent: str = "chat"
    guardrail_decision: SplitikGuardrailDecision = Field(
        default_factory=lambda: SplitikGuardrailDecision(allowed=True, reason="allowed")
    )
    context_chips: list[SplitikContextChip]
    capabilities: list[str]
    drafts: list[SplitikDraft] = []
    questions: list[SplitikQuestion] = []
    suggested_actions: list[SplitikSuggestedAction] = []


class SplitikSession(BaseModel):
    id: UUID
    owner_user_id: UUID
    mode: str
    locale: str
    timezone: str
    messages: list[dict]
    created_at: datetime
    updated_at: datetime


class SplitikDraftCommitResponse(BaseModel):
    draft: SplitikDraft
    resource: dict
