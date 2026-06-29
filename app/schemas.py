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


class UserPage(BaseModel):
    items: list[User]
    limit: int
    offset: int
    total: int


class UserUpdate(BaseModel):
    name: str | None = None
    email: str | None = None
    avatar_url: str | None = None


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


class EventUpdate(BaseModel):
    name: str | None = None
    is_closed: bool | None = None


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
    share_items: list[CreateShareItemRequest] = Field(min_length=1)


class ReceiptItem(BaseModel):
    id: UUID
    receipt_id: UUID
    name: str = ""
    cost_kopecks: int
    share_items: list[UUID]


class CreateReceiptRequest(BaseModel):
    payer_id: UUID
    title: str = ""
    total_amount_kopecks: int = Field(gt=0)
    items: list[CreateReceiptItemRequest] = Field(min_length=1)


class UpdateReceiptRequest(BaseModel):
    title: str | None = None
    total_amount_kopecks: int | None = Field(default=None, gt=0)
    items: list[CreateReceiptItemRequest] | None = None


class Receipt(BaseModel):
    id: UUID
    event_id: UUID
    payer_id: UUID
    title: str = ""
    status: str
    total_amount_kopecks: int
    created_at: datetime
    updated_at: datetime
    items: list[ReceiptItem]
    image_url: str | None = None


class ReceiptPage(BaseModel):
    items: list[Receipt]
    limit: int
    offset: int
    total: int


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
