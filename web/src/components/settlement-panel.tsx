"use client";

import { useMemo, useState } from "react";

import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import {
  ApiError,
  EventSummary,
  money,
  Payment,
  PaymentRequest,
  SettlementPlan,
  SettlementPlanEdge,
  SettlementPlanStatus,
  SettlementPreview
} from "@/lib/splitapp-api";
import { cn } from "@/lib/utils";

export type SettlementPerson = {
  id: string;
  initials: string;
  name: string;
  subtitle?: string;
};

export type SettlementEventState = {
  loading: boolean;
  preview?: SettlementPreview;
  plans: SettlementPlan[];
  paymentRequests: PaymentRequest[];
  error?: string;
  updatedAt?: number;
};

type ApiRequest = <T>(path: string, init?: RequestInit) => Promise<T>;

type SettlementPanelProps = {
  event: EventSummary;
  currentUserId?: string | null;
  people: SettlementPerson[];
  state?: SettlementEventState;
  apiRequest: ApiRequest;
  onRefresh: (event: EventSummary) => Promise<void>;
  onProblem?: (error: unknown, message: string, action: string) => void;
};

type ActionKey =
  | "create"
  | "approve"
  | "reject"
  | "execute"
  | `mark-paid:${string}`
  | `confirm:${string}`
  | null;

const activePlanStatuses = new Set<SettlementPlanStatus>(["pending", "approved", "executing", "partially_settled"]);
const completedPlanStatuses = new Set<SettlementPlanStatus>(["completed"]);
const terminalPlanStatuses = new Set<SettlementPlanStatus>(["stale", "expired", "rejected"]);

export function SettlementPanel({
  event,
  currentUserId,
  people,
  state,
  apiRequest,
  onRefresh,
  onProblem
}: SettlementPanelProps) {
  const [actionKey, setActionKey] = useState<ActionKey>(null);
  const [actionError, setActionError] = useState("");
  const [isRejectOpen, setIsRejectOpen] = useState(false);
  const [rejectReason, setRejectReason] = useState("");
  const preview = state?.preview;
  const plans = useMemo(() => state?.plans ?? [], [state?.plans]);
  const paymentRequests = state?.paymentRequests ?? [];
  const selectedPlan = useMemo(() => selectLatestRelevantPlan(plans), [plans]);
  const peopleById = useMemo(() => new Map(people.map((person) => [person.id, person])), [people]);
  const isClosed = Boolean(event.is_closed || event.status === "closed");
  const canProposePlan =
    Boolean(preview?.transfer_count_reduced) &&
    !isClosed &&
    (!selectedPlan || terminalPlanStatuses.has(selectedPlan.status) || completedPlanStatuses.has(selectedPlan.status));

  const runAction = async (nextActionKey: Exclude<ActionKey, null>, action: () => Promise<void>) => {
    setActionError("");
    setActionKey(nextActionKey);
    try {
      await action();
      await onRefresh(event);
    } catch (error) {
      const message = settlementActionErrorMessage(error);
      setActionError(message);
      onProblem?.(error, message, nextActionKey.split(":")[0]);
    } finally {
      setActionKey(null);
    }
  };

  const createSettlementPlan = () =>
    runAction("create", async () => {
      await apiRequest<SettlementPlan>(`/api/events/${event.id}/settlement-plans`, {
        method: "POST",
        headers: { "Idempotency-Key": crypto.randomUUID() },
        body: JSON.stringify({})
      });
    });

  const approveSettlementPlan = (plan: SettlementPlan) =>
    runAction("approve", async () => {
      await apiRequest<SettlementPlan>(`/api/settlement-plans/${plan.id}/approve`, { method: "POST" });
    });

  const rejectSettlementPlan = (plan: SettlementPlan) =>
    runAction("reject", async () => {
      const reason = rejectReason.trim();
      if (!reason) throw new Error("Укажите причину, чтобы участники поняли, что исправить.");
      await apiRequest<SettlementPlan>(`/api/settlement-plans/${plan.id}/reject`, {
        method: "POST",
        body: JSON.stringify({ reason })
      });
      setIsRejectOpen(false);
      setRejectReason("");
    });

  const executeSettlementPlan = (plan: SettlementPlan) =>
    runAction("execute", async () => {
      await apiRequest<SettlementPlan>(`/api/settlement-plans/${plan.id}/execute`, {
        method: "POST",
        headers: { "Idempotency-Key": crypto.randomUUID() }
      });
    });

  const markPaymentRequestPaid = (request: PaymentRequest) =>
    runAction(`mark-paid:${request.id}`, async () => {
      await apiRequest<Payment>(`/api/payment-requests/${request.id}/mark-paid`, {
        method: "POST",
        headers: { "Idempotency-Key": crypto.randomUUID() }
      });
    });

  const confirmReceived = (paymentId: string) =>
    runAction(`confirm:${paymentId}`, async () => {
      await apiRequest<Payment>(`/api/payments/${paymentId}/confirm`, { method: "POST" });
    });

  return (
    <section data-testid="settlement-panel" className="grid gap-3 overflow-x-hidden rounded-2xl bg-white p-3 shadow-sm">
      <div className="flex min-w-0 items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="text-xs font-black uppercase tracking-[0.12em] text-[#1f3d8f]">Упростить расчёты</p>
          <h3 className="mt-1 text-xl font-black leading-tight text-slate-950">План переводов внутри события</h3>
          <p className="mt-1 text-sm font-semibold leading-5 text-slate-500">
            Покажем, кто кому переводит, без обещания абсолютного минимума.
          </p>
        </div>
        {isClosed ? (
          <span className="shrink-0 rounded-full bg-[#eef1f7] px-3 py-1 text-xs font-black text-[#1f3d8f]">только просмотр</span>
        ) : null}
      </div>

      {state?.loading && !preview ? <SettlementSkeleton /> : null}

      {state?.error ? (
        <div role="alert" aria-live="polite" className="grid gap-3 rounded-2xl bg-[#fff3f3] p-4 text-sm font-bold text-[#8a1c1c]">
          <p>{state.error}</p>
          <Button
            type="button"
            variant="secondary"
            onClick={() => onRefresh(event)}
            className="min-h-11 rounded-xl bg-white text-sm font-black text-[#1f3d8f] hover:bg-white/90 focus-visible:ring-[#1f3d8f]"
          >
            Повторить загрузку
          </Button>
        </div>
      ) : null}

      {actionError ? (
        <div role="alert" aria-live="polite" className="rounded-2xl bg-[#fff3f3] p-4 text-sm font-bold text-[#8a1c1c]">
          {actionError}
        </div>
      ) : null}

      {preview ? (
        <PreviewBlock
          preview={preview}
          isClosed={isClosed}
          peopleById={peopleById}
          canProposePlan={canProposePlan}
          isCreating={actionKey === "create"}
          onCreate={createSettlementPlan}
        />
      ) : null}

      {selectedPlan ? (
        <PlanBlock
          plan={selectedPlan}
          preview={preview}
          paymentRequests={paymentRequests}
          peopleById={peopleById}
          currentUserId={currentUserId}
          isClosed={isClosed}
          isRejectOpen={isRejectOpen}
          rejectReason={rejectReason}
          actionKey={actionKey}
          canProposePlan={canProposePlan}
          onRejectOpen={() => setIsRejectOpen(true)}
          onRejectCancel={() => {
            setIsRejectOpen(false);
            setRejectReason("");
          }}
          onRejectReason={setRejectReason}
          onApprove={approveSettlementPlan}
          onReject={rejectSettlementPlan}
          onExecute={executeSettlementPlan}
          onMarkPaid={markPaymentRequestPaid}
          onConfirmReceived={confirmReceived}
          onRefresh={() => onRefresh(event)}
          onCreate={createSettlementPlan}
        />
      ) : null}

      {!state?.loading && !preview && !state?.error ? (
        <p className="rounded-2xl bg-[#f5f5f7] p-4 text-sm font-semibold text-slate-500">
          Расчёты пока не загружены. Обновите событие, чтобы увидеть рекомендации.
        </p>
      ) : null}
    </section>
  );
}

function SettlementSkeleton() {
  return (
    <div className="grid gap-3" aria-label="Загружаем расчёты">
      <div className="h-20 animate-pulse rounded-2xl bg-[#eef1f7]" />
      <div className="grid grid-cols-2 gap-2">
        <div className="h-16 animate-pulse rounded-2xl bg-[#eef1f7]" />
        <div className="h-16 animate-pulse rounded-2xl bg-[#eef1f7]" />
      </div>
    </div>
  );
}

function PreviewBlock({
  preview,
  isClosed,
  peopleById,
  canProposePlan,
  isCreating,
  onCreate
}: {
  preview: SettlementPreview;
  isClosed: boolean;
  peopleById: Map<string, SettlementPerson>;
  canProposePlan: boolean;
  isCreating: boolean;
  onCreate: () => void;
}) {
  const summaryText = previewSummaryText(preview);

  return (
    <Card className="rounded-2xl border-0 bg-[#f5f5f7] shadow-none">
      <CardContent className="grid gap-4 p-4">
        <div className="grid gap-1">
          <p className="text-base font-black text-slate-950">{summaryText}</p>
          <p className="text-sm font-semibold leading-5 text-slate-500">
            Исходных переводов: {preview.original_transfer_count}. Рекомендуемых: {preview.recommended_transfer_count}.
          </p>
          {isClosed ? (
            <p className="text-sm font-semibold leading-5 text-slate-500">Событие завершено: расчёты доступны только для просмотра.</p>
          ) : null}
        </div>

        {preview.net_positions.length ? (
          <div className="grid gap-2">
            <p className="text-xs font-black uppercase text-slate-500">Итоговые позиции</p>
            {preview.net_positions.map((position) => (
              <div key={`${position.user_id}-${position.direction}`} className="grid min-w-0 grid-cols-[1fr_auto] gap-2 rounded-xl bg-white p-3">
                <span className="min-w-0 text-sm font-bold text-slate-700">
                  {personName(peopleById, position.user_id)} {position.direction === "owes" ? "должен" : "получит"}
                </span>
                <span className="text-sm font-black text-slate-950">{money(position.amount_kopecks)}</span>
              </div>
            ))}
          </div>
        ) : null}

        {preview.recommended_transfers.length ? (
          <div className="grid gap-2">
            <p className="text-xs font-black uppercase text-slate-500">Рекомендуемые переводы</p>
            {preview.recommended_transfers.map((transfer) => (
              <div key={`${transfer.debtor_id}-${transfer.creditor_id}-${transfer.amount_kopecks}`} className="grid min-w-0 gap-1 rounded-xl bg-white p-3">
                <span className="min-w-0 text-sm font-black text-slate-950">
                  {personName(peopleById, transfer.debtor_id)} → {personName(peopleById, transfer.creditor_id)}
                </span>
                <span className="text-sm font-semibold text-slate-500">{money(transfer.amount_kopecks)}</span>
              </div>
            ))}
          </div>
        ) : null}

        {canProposePlan ? (
          <Button
            type="button"
            onClick={onCreate}
            disabled={isCreating}
            className="min-h-12 rounded-2xl bg-[#1f3d8f] text-sm font-black text-white hover:bg-[#1f3d8f]/90 focus-visible:ring-[#1f3d8f] disabled:bg-slate-300"
          >
            {isCreating ? "Создаём план..." : "Предложить план"}
          </Button>
        ) : null}
      </CardContent>
    </Card>
  );
}

function PlanBlock({
  plan,
  preview,
  paymentRequests,
  peopleById,
  currentUserId,
  isClosed,
  isRejectOpen,
  rejectReason,
  actionKey,
  canProposePlan,
  onRejectOpen,
  onRejectCancel,
  onRejectReason,
  onApprove,
  onReject,
  onExecute,
  onMarkPaid,
  onConfirmReceived,
  onRefresh,
  onCreate
}: {
  plan: SettlementPlan;
  preview?: SettlementPreview;
  paymentRequests: PaymentRequest[];
  peopleById: Map<string, SettlementPerson>;
  currentUserId?: string | null;
  isClosed: boolean;
  isRejectOpen: boolean;
  rejectReason: string;
  actionKey: ActionKey;
  canProposePlan: boolean;
  onRejectOpen: () => void;
  onRejectCancel: () => void;
  onRejectReason: (value: string) => void;
  onApprove: (plan: SettlementPlan) => void;
  onReject: (plan: SettlementPlan) => void;
  onExecute: (plan: SettlementPlan) => void;
  onMarkPaid: (request: PaymentRequest) => void;
  onConfirmReceived: (paymentId: string) => void;
  onRefresh: () => void;
  onCreate: () => void;
}) {
  const approvedCount = plan.approvals.length;
  const requiredCount = plan.required_approver_ids.length;
  const hasCurrentUserApproved = Boolean(currentUserId && plan.approvals.some((approval) => approval.user_id === currentUserId));
  const canCurrentUserApprove = Boolean(
    currentUserId && plan.required_approver_ids.includes(currentUserId) && !hasCurrentUserApproved && !isClosed
  );

  return (
    <Card className="rounded-2xl border-0 bg-white shadow-none ring-1 ring-[#dfe5f2]">
      <CardContent className="grid gap-4 p-4">
        <div className="grid gap-1">
          <p className="text-xs font-black uppercase text-slate-500">Текущий план</p>
          <p className="text-base font-black text-slate-950">{planStatusTitle(plan.status)}</p>
          <p className="text-sm font-semibold leading-5 text-slate-500">{planStatusDescription(plan, preview)}</p>
        </div>

        {plan.status === "pending" ? (
          <div className="grid gap-3 rounded-2xl bg-[#eef1f7] p-3">
            <p className="text-sm font-black text-[#1f3d8f]">{approvedCount} из {requiredCount} согласились</p>
            <p className="text-sm font-semibold leading-5 text-slate-600">Согласие с планом не означает оплату.</p>
            {hasCurrentUserApproved ? <p className="text-sm font-bold text-slate-600">Вы уже согласились с этим планом.</p> : null}
            {canCurrentUserApprove ? (
              <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
                <Button
                  type="button"
                  onClick={() => onApprove(plan)}
                  disabled={actionKey === "approve"}
                  className="min-h-12 rounded-2xl bg-[#1f3d8f] text-sm font-black text-white hover:bg-[#1f3d8f]/90 focus-visible:ring-[#1f3d8f] disabled:bg-slate-300"
                >
                  {actionKey === "approve" ? "Сохраняем..." : "Согласиться с планом"}
                </Button>
                <Button
                  type="button"
                  variant="secondary"
                  onClick={onRejectOpen}
                  className="min-h-12 rounded-2xl bg-white text-sm font-black text-slate-700 hover:bg-white/90 focus-visible:ring-[#1f3d8f]"
                >
                  Не согласен
                </Button>
              </div>
            ) : null}
            {isRejectOpen ? (
              <div className="grid gap-2">
                <label className="text-xs font-black uppercase text-slate-500" htmlFor="settlement-reject-reason">Причина несогласия</label>
                <textarea
                  id="settlement-reject-reason"
                  value={rejectReason}
                  onChange={(event) => onRejectReason(event.currentTarget.value)}
                  className="min-h-24 rounded-2xl border border-[#c6cbdc] bg-white p-3 text-sm font-semibold text-slate-950 outline-none focus-visible:ring-2 focus-visible:ring-[#1f3d8f]"
                  placeholder="Например, чек ещё не добавлен или сумма спорная"
                />
                <div className="grid grid-cols-2 gap-2">
                  <Button
                    type="button"
                    variant="secondary"
                    onClick={onRejectCancel}
                    className="min-h-11 rounded-xl bg-white text-sm font-black text-slate-700 hover:bg-white/90 focus-visible:ring-[#1f3d8f]"
                  >
                    Отмена
                  </Button>
                  <Button
                    type="button"
                    onClick={() => onReject(plan)}
                    disabled={actionKey === "reject" || !rejectReason.trim()}
                    className="min-h-11 rounded-xl bg-[#8a1c1c] text-sm font-black text-white hover:bg-[#8a1c1c]/90 focus-visible:ring-[#1f3d8f] disabled:bg-slate-300"
                  >
                    {actionKey === "reject" ? "Отклоняем..." : "Отклонить план"}
                  </Button>
                </div>
              </div>
            ) : null}
          </div>
        ) : null}

        {plan.status === "approved" && !isClosed ? (
          <div className="grid gap-2 rounded-2xl bg-[#eef1f7] p-3">
            <p className="text-sm font-semibold leading-5 text-slate-600">Запросы не отмечают деньги оплаченными.</p>
            <Button
              type="button"
              onClick={() => onExecute(plan)}
              disabled={actionKey === "execute"}
              className="min-h-12 rounded-2xl bg-[#1f3d8f] text-sm font-black text-white hover:bg-[#1f3d8f]/90 focus-visible:ring-[#1f3d8f] disabled:bg-slate-300"
            >
              {actionKey === "execute" ? "Создаём запросы..." : "Создать запросы на оплату"}
            </Button>
          </div>
        ) : null}

        {plan.status === "completed" ? (
          <p className="rounded-2xl bg-[#eef1f7] p-3 text-sm font-black text-[#1f3d8f]">Все переводы подтверждены</p>
        ) : null}

        {terminalPlanStatuses.has(plan.status) ? (
          <TerminalPlanActions
            plan={plan}
            canProposePlan={canProposePlan}
            isCreating={actionKey === "create"}
            onRefresh={onRefresh}
            onCreate={onCreate}
          />
        ) : null}

        <PlanEdges
          plan={plan}
          requests={paymentRequests}
          peopleById={peopleById}
          currentUserId={currentUserId}
          actionKey={actionKey}
          onMarkPaid={onMarkPaid}
          onConfirmReceived={onConfirmReceived}
        />
      </CardContent>
    </Card>
  );
}

function TerminalPlanActions({
  plan,
  canProposePlan,
  isCreating,
  onRefresh,
  onCreate
}: {
  plan: SettlementPlan;
  canProposePlan: boolean;
  isCreating: boolean;
  onRefresh: () => void;
  onCreate: () => void;
}) {
  return (
    <div className="grid gap-2 rounded-2xl bg-[#f5f5f7] p-3">
      <p className="text-sm font-semibold leading-5 text-slate-600">
        {plan.status === "stale"
          ? "Баланс события изменился после создания плана. Обновите расчёты и предложите новый план."
          : plan.status === "expired"
            ? "План истёк. Если preview всё ещё сокращает переводы, можно предложить новый план."
            : `План отклонён${plan.rejection_reason ? `: ${plan.rejection_reason}` : "."}`}
      </p>
      <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
        <Button
          type="button"
          variant="secondary"
          onClick={onRefresh}
          className="min-h-11 rounded-xl bg-white text-sm font-black text-[#1f3d8f] hover:bg-white/90 focus-visible:ring-[#1f3d8f]"
        >
          Обновить расчёты
        </Button>
        {canProposePlan ? (
          <Button
            type="button"
            onClick={onCreate}
            disabled={isCreating}
            className="min-h-11 rounded-xl bg-[#1f3d8f] text-sm font-black text-white hover:bg-[#1f3d8f]/90 focus-visible:ring-[#1f3d8f] disabled:bg-slate-300"
          >
            {isCreating ? "Создаём..." : "Предложить план"}
          </Button>
        ) : null}
      </div>
    </div>
  );
}

function PlanEdges({
  plan,
  requests,
  peopleById,
  currentUserId,
  actionKey,
  onMarkPaid,
  onConfirmReceived
}: {
  plan: SettlementPlan;
  requests: PaymentRequest[];
  peopleById: Map<string, SettlementPerson>;
  currentUserId?: string | null;
  actionKey: ActionKey;
  onMarkPaid: (request: PaymentRequest) => void;
  onConfirmReceived: (paymentId: string) => void;
}) {
  return (
    <div className="grid gap-2">
      <p className="text-xs font-black uppercase text-slate-500">Переводы плана</p>
      {plan.edges.map((edge) => {
        const request = findRequestForEdge(requests, plan, edge);
        const paymentId = request?.payment_id;
        const canMarkPaid = Boolean(request && currentUserId === edge.debtor_id && request.status === "requested");
        const canConfirmReceived = Boolean(request && currentUserId === edge.creditor_id && request.status === "paid" && paymentId);
        return (
          <div key={edge.edge_id} className="grid min-w-0 gap-2 rounded-2xl bg-[#f5f5f7] p-3">
            <div className="grid min-w-0 grid-cols-[1fr_auto] gap-2">
              <span className="min-w-0 text-sm font-black text-slate-950">
                {personName(peopleById, edge.debtor_id)} → {personName(peopleById, edge.creditor_id)}
              </span>
              <span className="text-sm font-black text-slate-950">{money(edge.amount_kopecks)}</span>
            </div>
            <p className="text-sm font-semibold leading-5 text-slate-600">{requestStatusText(request, edge)}</p>
            {request ? (
              <p className="text-xs font-bold text-slate-500">
                Связанный запрос: {request.id.slice(0, 8)} · статус: {request.status}
              </p>
            ) : null}
            {canMarkPaid && request ? (
              <Button
                type="button"
                onClick={() => onMarkPaid(request)}
                disabled={actionKey === `mark-paid:${request.id}`}
                className="min-h-11 rounded-xl bg-[#1f3d8f] text-sm font-black text-white hover:bg-[#1f3d8f]/90 focus-visible:ring-[#1f3d8f] disabled:bg-slate-300"
              >
                {actionKey === `mark-paid:${request.id}` ? "Отмечаем..." : "Я оплатил"}
              </Button>
            ) : null}
            {canConfirmReceived && paymentId ? (
              <Button
                type="button"
                onClick={() => onConfirmReceived(paymentId)}
                disabled={actionKey === `confirm:${paymentId}`}
                className="min-h-11 rounded-xl bg-[#111111] text-sm font-black text-white hover:bg-[#111111]/90 focus-visible:ring-[#1f3d8f] disabled:bg-slate-300"
              >
                {actionKey === `confirm:${paymentId}` ? "Подтверждаем..." : "Подтвердить получение"}
              </Button>
            ) : null}
          </div>
        );
      })}
    </div>
  );
}

function selectLatestRelevantPlan(plans: SettlementPlan[]) {
  return [...plans].sort(compareSettlementPlans)[0] ?? null;
}

function compareSettlementPlans(left: SettlementPlan, right: SettlementPlan) {
  const priorityDelta = planPriority(left.status) - planPriority(right.status);
  if (priorityDelta !== 0) return priorityDelta;
  return new Date(right.updated_at || right.created_at).getTime() - new Date(left.updated_at || left.created_at).getTime();
}

function planPriority(status: SettlementPlanStatus) {
  if (activePlanStatuses.has(status)) return 0;
  if (completedPlanStatuses.has(status)) return 1;
  return 2;
}

function previewSummaryText(preview: SettlementPreview) {
  if (preview.original_transfer_count === 0 && preview.recommended_transfer_count === 0) return "Все рассчитались";
  if (!preview.transfer_count_reduced) return "Расчёты уже простые";
  return `Можно сократить ${preview.original_transfer_count} переводов до ${preview.recommended_transfer_count}`;
}

function planStatusTitle(status: SettlementPlanStatus) {
  const titles: Record<SettlementPlanStatus, string> = {
    pending: "План ждёт согласования",
    approved: "План согласован",
    executing: "Запросы на оплату созданы",
    partially_settled: "Часть переводов подтверждена",
    completed: "План завершён",
    stale: "Устаревший план",
    expired: "План истёк",
    rejected: "План отклонён"
  };
  return titles[status];
}

function planStatusDescription(plan: SettlementPlan, preview?: SettlementPreview) {
  if (plan.status === "pending") return "Участники подтверждают, что согласны с предложенной схемой.";
  if (plan.status === "approved") return "Можно создать запросы на оплату. Это ещё не оплата.";
  if (plan.status === "executing") return "Следите за каждым запросом: кто должен оплатить и кто подтверждает получение.";
  if (plan.status === "partially_settled") return "Некоторые переводы уже в процессе или подтверждены, остальные остаются видимыми.";
  if (plan.status === "completed") return "Backend подтвердил все переводы по плану.";
  if (plan.status === "stale") return "Состояние события изменилось, старый snapshot нельзя исполнять.";
  if (plan.status === "expired") return "TTL плана истёк. Обновите preview перед новым предложением.";
  if (plan.status === "rejected") return plan.rejection_reason ? `Причина: ${plan.rejection_reason}` : "Один из участников отклонил план.";
  return preview?.transfer_count_reduced ? "Preview всё ещё можно использовать для нового плана." : "План больше не активен.";
}

function findRequestForEdge(requests: PaymentRequest[], plan: SettlementPlan, edge: SettlementPlanEdge) {
  return requests.find(
    (request) =>
      request.id === edge.payment_request_id ||
      (request.settlement_plan_id === plan.id && request.settlement_edge_id === edge.edge_id)
  );
}

function requestStatusText(request: PaymentRequest | undefined, edge: SettlementPlanEdge) {
  if (!request) {
    if (edge.status) return `Запрос ещё не связан. Статус перевода: ${edge.status}.`;
    return "Запрос ещё не создан.";
  }
  const labels: Record<string, string> = {
    requested: "Запрос отправлен — ждём оплату от должника.",
    paid: "Должник отметил оплату — получатель должен подтвердить получение.",
    confirmed: "Получение подтверждено, перевод закрыт.",
    cancelled: "Запрос отменён и остаётся видимым в истории.",
    disputed: "По запросу открыт спор, он остаётся видимым до решения.",
    rejected: "Оплата отклонена получателем.",
    acknowledged: "Должник видел запрос, оплаты ещё нет."
  };
  return labels[request.status] ?? `Статус запроса: ${request.status}.`;
}

function personName(peopleById: Map<string, SettlementPerson>, userId: string) {
  return peopleById.get(userId)?.name ?? `Участник ${userId.slice(0, 8)}`;
}

function settlementActionErrorMessage(error: unknown) {
  if (error instanceof ApiError) {
    if (error.status === 401 || error.status === 403) return "Не удалось выполнить действие: проверьте доступ к событию.";
    if (error.status === 409) return "Состояние расчётов изменилось. Обновите расчёты и попробуйте снова.";
    if (error.message) return `Не удалось выполнить действие: ${error.message}`;
  }
  if (error instanceof Error && error.message) return error.message;
  return "Не удалось выполнить действие. Проверьте сеть и попробуйте снова.";
}

export function settlementLoadErrorMessage(error: unknown) {
  if (error instanceof ApiError && (error.status === 401 || error.status === 403)) {
    return "Не удалось загрузить расчёты: нет доступа к событию.";
  }
  return "Не удалось загрузить расчёты. Попробуйте ещё раз.";
}

export function settlementStateFromData({
  preview,
  plans,
  paymentRequests
}: {
  preview: SettlementPreview;
  plans: SettlementPlan[];
  paymentRequests: PaymentRequest[];
}): SettlementEventState {
  return {
    loading: false,
    preview,
    plans,
    paymentRequests,
    updatedAt: Date.now()
  };
}
