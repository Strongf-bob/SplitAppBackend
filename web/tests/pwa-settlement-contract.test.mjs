import { existsSync, readFileSync } from "node:fs";
import test from "node:test";
import assert from "node:assert/strict";

const page = readFileSync(new URL("../src/app/page.tsx", import.meta.url), "utf8");
const api = readFileSync(new URL("../src/lib/splitapp-api.ts", import.meta.url), "utf8");
const sw = readFileSync(new URL("../public/sw.js", import.meta.url), "utf8");
const settlementPanelUrl = new URL("../src/components/settlement-panel.tsx", import.meta.url);
const settlementPanel = existsSync(settlementPanelUrl) ? readFileSync(settlementPanelUrl, "utf8") : "";
const settlementSource = `${page}\n${settlementPanel}`;

test("event settlement UI is extracted and embedded inside EventDetailScreen only", () => {
  assert.ok(settlementPanel, "expected focused web/src/components/settlement-panel.tsx component");
  assert.match(page, /import \{[\s\S]*SettlementPanel[\s\S]*\} from "@\/components\/settlement-panel"/);
  assert.match(page, /<SettlementPanel[\s\S]{0,800}event=\{event\}/);
  assert.match(page, /<ContentPanel title="Чеки">/);
  assert.match(page, /<SettlementPanel[\s\S]*<ContentPanel title="Чеки">/);
  assert.doesNotMatch(page, /id: "settlement"/);
  assert.doesNotMatch(page, /label: "Расчёты"/);
});

test("settlement API contract uses exact backend types, endpoints and idempotent actions", () => {
  for (const expectedType of [
    "export type EventBalanceExplanation",
    "export type SettlementNetPosition",
    "export type SettlementTransfer",
    "export type SettlementPreview",
    "export type SettlementPlanStatus",
    "export type SettlementPlanEdge",
    "export type SettlementPlanApproval",
    "export type SettlementPlan",
    "export type SettlementPlanPage",
    "export type PaymentRequest",
    "export type PaymentRequestPage",
    "export type Payment"
  ]) {
    assert.match(api, new RegExp(expectedType), `missing API type: ${expectedType}`);
  }

  for (const endpoint of [
    "`/api/events/${event.id}/settlement-preview`",
    "`/api/events/${event.id}/settlement-plans?limit=50`",
    "`/api/events/${event.id}/payment-requests?limit=100`",
    "`/api/events/${event.id}/settlement-plans`",
    "`/api/settlement-plans/${plan.id}/approve`",
    "`/api/settlement-plans/${plan.id}/reject`",
    "`/api/settlement-plans/${plan.id}/execute`",
    "`/api/payment-requests/${request.id}/mark-paid`",
    "`/api/payments/${paymentId}/confirm`"
  ]) {
    assert.match(settlementSource, new RegExp(endpoint.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")), `missing endpoint: ${endpoint}`);
  }

  assert.match(settlementSource, /"Idempotency-Key": crypto\.randomUUID\(\)/);
  assert.match(settlementSource, /method: "POST"[\s\S]{0,120}"Idempotency-Key": crypto\.randomUUID\(\)[\s\S]{0,200}settlement-plans/);
  assert.match(settlementSource, /executeSettlementPlan[\s\S]{0,500}"Idempotency-Key": crypto\.randomUUID\(\)/);
  assert.match(settlementSource, /markPaymentRequestPaid[\s\S]{0,500}"Idempotency-Key": crypto\.randomUUID\(\)/);
});

test("opening a real event loads receipts and settlement data in one parallel cached pass", () => {
  assert.match(page, /type EventSettlementCache = Record<string, SettlementEventState>/);
  assert.match(page, /const \[eventSettlements, setEventSettlements\] = useState<EventSettlementCache>\(\{\}\)/);
  assert.match(page, /Promise\.allSettled\(\[\s*authedApi<ReceiptPage>\(`\/api\/events\/\$\{event\.id\}\/receipts`\),\s*authedApi<SettlementPreview>\(`\/api\/events\/\$\{event\.id\}\/settlement-preview`\),\s*authedApi<SettlementPlanPage>\(`\/api\/events\/\$\{event\.id\}\/settlement-plans\?limit=50`\),\s*authedApi<PaymentRequestPage>\(`\/api\/events\/\$\{event\.id\}\/payment-requests\?limit=100`\)\s*\]\)/);
  assert.match(page, /eventSettlements\[event\.id\] && eventReceipts\[event\.id\]/);
  assert.doesNotMatch(page, /const page = await authedApi<ReceiptPage>\(`\/api\/events\/\$\{event\.id\}\/receipts`\)/);
});

test("settlement panel copy separates approval from payment without exposing implementation details", () => {
  for (const copy of [
    "Упростить расчёты",
    "Все рассчитались",
    "Расчёты уже простые",
    "Можно сократить",
    "Предложить план",
    "Согласиться с планом",
    "Не согласен",
    "Согласие с планом не означает оплату.",
    "Создать запросы на оплату",
    "Запросы не отмечают деньги оплаченными.",
    "Я оплатил",
    "Подтвердить получение",
    "Все переводы подтверждены",
    "Устаревший план",
    "План истёк",
    "План отклонён",
    "Обновить расчёты"
  ]) {
    assert.match(settlementPanel, new RegExp(copy), `missing settlement copy: ${copy}`);
  }
  assert.match(settlementPanel, /\{approvedCount\} из \{requiredCount\} согласились/);
  assert.match(settlementPanel, /Покажем понятный план: кто, кому и сколько переводит/);
  for (const internalCopy of [
    "без обещания абсолютного минимума",
    "Backend подтвердил",
    "старый snapshot",
    "TTL плана",
    "Обновите preview",
    "Связанный запрос:",
    "статус: {request.status}"
  ]) {
    assert.doesNotMatch(settlementPanel, new RegExp(internalCopy), `technical copy leaked into the UI: ${internalCopy}`);
  }
});

test("settlement edge actions respect roles, event closure, request statuses and payment linkage", () => {
  assert.match(settlementPanel, /payment_request_id/);
  assert.match(settlementPanel, /settlement_edge_id/);
  assert.match(settlementPanel, /request\.status === "requested"/);
  assert.match(settlementPanel, /request\.status === "paid" && paymentId/);
  assert.match(settlementPanel, /currentUserId === edge\.debtor_id/);
  assert.match(settlementPanel, /currentUserId === edge\.creditor_id/);
  assert.match(settlementPanel, /<PlanEdges[\s\S]{0,350}isClosed=\{isClosed\}/);
  assert.match(settlementPanel, /!isClosed && request && currentUserId === edge\.debtor_id/);
  assert.match(settlementPanel, /!isClosed && request && currentUserId === edge\.creditor_id/);
  assert.match(settlementPanel, /onMarkPaid\(request\)/);
  assert.match(settlementPanel, /onConfirmReceived\(paymentId\)/);
  assert.match(settlementPanel, /requestStatusText/);
});

test("an active plan replaces the duplicate recommendation list and action errors stay generic", () => {
  assert.match(settlementPanel, /preview && !selectedPlan/);
  assert.match(settlementPanel, /actionInFlight\.current/);
  assert.doesNotMatch(settlementPanel, /Не удалось выполнить действие: \$\{error\.message\}/);
  assert.match(page, /<SettlementPanel[\s\S]{0,100}key=\{event\.id\}/);
});

test("settlement errors and controls are accessible, touch-safe and on-brand", () => {
  assert.match(settlementPanel, /role="alert"/);
  assert.match(settlementPanel, /aria-live="polite"/);
  assert.match(settlementPanel, /min-h-11|min-h-12/);
  assert.match(settlementPanel, /focus-visible:ring-\[#1f3d8f\]/);
  assert.match(settlementPanel, /overflow-x-hidden|min-w-0/);
  assert.match(settlementPanel, /bg-\[#1f3d8f\]/);
  assert.match(settlementPanel, /bg-white/);
  assert.doesNotMatch(settlementPanel, /emerald|green|#16a34a|#22c55e/i);
  assert.doesNotMatch(settlementPanel, /[💸💰✅❌⚠️]/u);
});

test("settlement shell cache version is bumped after UI change", () => {
  assert.match(sw, /splitapp-next-pwa-v35/);
  assert.match(page, /const clientShellVersion = "splitapp-next-pwa-v35"/);
});
