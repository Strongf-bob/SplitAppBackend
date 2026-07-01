from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, Field


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
    payment_phone_visibility: str = "nobody"


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
    created_at: datetime
    updated_at: datetime


class FriendshipPage(BaseModel):
    items: list[Friendship]
    limit: int
    offset: int
    total: int


class UserUpdate(BaseModel):
    name: str | None = None
    email: str | None = None
    avatar_url: str | None = None
    public_handle: str | None = None
    discovery_enabled: bool | None = None
    payment_phone: str | None = None
    payment_phone_visibility: str | None = None


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


class NotificationDeviceRegister(BaseModel):
    platform: str = Field(pattern="^ios$")
    provider: str = Field(default="apns", pattern="^apns$")
    token: str = Field(min_length=16, max_length=4096)
    environment: str = Field(default="sandbox", pattern="^(sandbox|production)$")


class NotificationDevice(BaseModel):
    id: UUID
    user_id: UUID
    platform: str
    provider: str
    environment: str
    enabled: bool
    created_at: datetime
    updated_at: datetime
    last_seen_at: datetime


class NotificationDevicePage(BaseModel):
    items: list[NotificationDevice]
    limit: int
    offset: int
    total: int


class NotificationTestRequest(BaseModel):
    title: str = Field(default="SplitApp", min_length=1, max_length=120)
    body: str = Field(default="Тестовое уведомление", min_length=1, max_length=240)
    data: dict[str, str] = Field(default_factory=dict)


class NotificationDeliveryResult(BaseModel):
    device_id: UUID
    provider: str
    status: str
    error: str | None = None


class NotificationSendResponse(BaseModel):
    attempted: int
    sent: int
    failed: int
    results: list[NotificationDeliveryResult]


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
    name: str
    split_strategy: str = "equal_default"
    receipt_creation_policy: str = "participants_can_add"
    receipt_finalization_policy: str = "payer_finalizes"
    participants_invite_policy: str = "creator_only"
    debt_display_mode: str = "simplified_default"
    settlement_deadline_policy: str = "disabled"
    review_window_seconds: int = Field(default=60 * 60 * 24, ge=300, le=60 * 60 * 24 * 30)
    safety_policy: str = "explicit_review"
    auto_confirm_on_timeout: bool = False


class EventUpdate(BaseModel):
    name: str | None = None
    is_closed: bool | None = None
    split_strategy: str | None = None
    receipt_creation_policy: str | None = None
    receipt_finalization_policy: str | None = None
    participants_invite_policy: str | None = None
    debt_display_mode: str | None = None
    settlement_deadline_policy: str | None = None
    review_window_seconds: int | None = Field(default=None, ge=300, le=60 * 60 * 24 * 30)
    safety_policy: str | None = None
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
    split_strategy: str = "equal_default"
    receipt_creation_policy: str = "participants_can_add"
    receipt_finalization_policy: str = "payer_finalizes"
    participants_invite_policy: str = "creator_only"
    debt_display_mode: str = "simplified_default"
    settlement_deadline_policy: str = "disabled"
    review_window_seconds: int = 60 * 60 * 24
    safety_policy: str = "explicit_review"
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


class CreateShareItemRequest(BaseModel):
    user_id: UUID
    share_value: Decimal = Field(gt=0, le=1)


class ShareItem(BaseModel):
    id: UUID
    receipt_item_id: UUID
    user_id: UUID
    share_value: Decimal = Field(gt=0, le=1)


class CreateReceiptItemRequest(BaseModel):
    name: str = ""
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
    title: str = ""
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
    title: str | None = None
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
    reason: str = Field(min_length=1)


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
    note: str = ""
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


class PaymentRequestPage(BaseModel):
    items: list[PaymentRequest]
    limit: int
    offset: int
    total: int


class DisputeCreate(BaseModel):
    resource_type: str
    resource_id: UUID
    reason: str = Field(min_length=1)


class DisputeResolve(BaseModel):
    resolution_note: str = ""


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


class SplitikEntryPoint(BaseModel):
    type: str = "general"
    event_id: UUID | None = None
    receipt_id: UUID | None = None
    target_user_id: UUID | None = None


class SplitikMessageRequest(BaseModel):
    session_id: UUID | None = None
    mode: str = "general"
    message: str = Field(min_length=1)
    entry_point: SplitikEntryPoint | None = None
    locale: str = "ru-RU"
    timezone: str = "Europe/Moscow"


class SplitikContextChip(BaseModel):
    type: str
    label: str
    value: str


class SplitikDraft(BaseModel):
    id: UUID
    type: str
    status: str
    payload: dict
    created_at: datetime
    committed_at: datetime | None = None
    committed_resource_id: UUID | None = None


class SplitikMessageResponse(BaseModel):
    session_id: UUID
    message_id: UUID
    assistant_message: str
    mode: str
    context_chips: list[SplitikContextChip]
    capabilities: list[str]
    drafts: list[SplitikDraft] = []


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
