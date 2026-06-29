from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, Field


class User(BaseModel):
    id: UUID
    name: str
    phone_number: str
    email: str | None = None
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


class EventUpdate(BaseModel):
    name: str | None = None
    is_closed: bool | None = None
    split_strategy: str | None = None
    receipt_creation_policy: str | None = None
    receipt_finalization_policy: str | None = None
    participants_invite_policy: str | None = None
    debt_display_mode: str | None = None
    settlement_deadline_policy: str | None = None


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


class CreateNearbyInviteCodeRequest(BaseModel):
    expires_in_seconds: int = Field(default=180, ge=60, le=300)


class NearbyInviteCode(BaseModel):
    id: UUID
    event_id: UUID
    code: str
    status: str
    created_by: UUID
    expires_at: datetime
    created_at: datetime


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
    total_amount_kopecks: int = Field(gt=0)
    items: list[CreateReceiptItemRequest] = Field(min_length=1)
    discount_amount_kopecks: int = 0
    service_fee_amount_kopecks: int = 0
    delivery_fee_amount_kopecks: int = 0
    tip_amount_kopecks: int = 0
    rounding_adjustment_kopecks: int = 0
    fiscal_total_amount_kopecks: int | None = None
    vat_amount_kopecks: int | None = None


class UpdateReceiptRequest(BaseModel):
    title: str | None = None
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


class ReceiptPage(BaseModel):
    items: list[Receipt]
    limit: int
    offset: int
    total: int


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


class PaymentRequestPage(BaseModel):
    items: list[PaymentRequest]
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
