"use client";

import { CSSProperties, FormEvent, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { AnimatePresence, motion } from "framer-motion";
import {
  ArrowLeft,
  ArrowDown,
  ArrowUp,
  Bell,
  Bot,
  CalendarCheck,
  Camera,
  ChevronDown,
  Home,
  Image as ImageIcon,
  Inbox,
  LogOut,
  MessageSquareWarning,
  Plus,
  ScanLine,
  Search,
  Send,
  Check,
  PencilLine,
  ExternalLink,
  ReceiptText,
  User,
  Users
} from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import {
  api,
  clearTokens,
  EventInvite,
  EventPage,
  Friendship,
  FriendshipPage,
  EventSummary,
  handleYandexOAuthCallback,
  HomeSummary,
  loadTokens,
  money,
  ReceiptPage,
  ReceiptSummary,
  ApiError,
  ClientReportScreen,
  reportClientIssue,
  SplitikAttachment,
  SplitikDraft,
  SplitikMessageResponse,
  SplitAppTokens,
  saveTokens,
  startYandexLogin,
  UserPage,
  UserProfile
} from "@/lib/splitapp-api";
import { cn } from "@/lib/utils";

type View = "home" | "events" | "people" | "notifications" | "profile" | "splitik";
type EventTab = "invites" | "active" | "closed";
type NotificationTab = "incoming" | "read";
type PermissionId = "contacts" | "camera" | "gallery" | "notifications";
type PermissionStatus = "pending" | "granted" | "unsupported" | "denied" | "skipped";
type PermissionState = Record<PermissionId, { status: PermissionStatus; detail: string }>;
type ChatMessage = {
  id: string;
  from: "user" | "splitik";
  text: string;
  drafts?: SplitikDraft[];
  questions?: Array<{ id: string; text: string }>;
};
type EventReceipts = Record<string, { loading: boolean; items: ReceiptSummary[] }>;
type MarkdownBlock = { type: "paragraph"; text: string } | { type: "list"; items: string[] };
type FriendOption = { id: string; initials: string; name: string; subtitle: string; amount: number; tone: string };
type ProblemReportState = {
  open: boolean;
  screen: ClientReportScreen;
  message: string;
  mode: "automatic_error" | "manual_feedback";
  requestId?: string;
  metadata?: Record<string, unknown>;
};

declare global {
  interface Navigator {
    contacts?: {
      select: (
        properties: Array<"name" | "email" | "tel" | "address" | "icon">,
        options?: { multiple?: boolean }
      ) => Promise<Array<Record<string, unknown>>>;
    };
  }

  interface Window {
    showOpenFilePicker?: (options?: {
      multiple?: boolean;
      types?: Array<{ description?: string; accept: Record<string, string[]> }>;
    }) => Promise<unknown[]>;
  }
}

const validViews: View[] = ["home", "events", "people", "notifications", "profile", "splitik"];

const navItems: Array<{ id: View; label: string; icon: React.ElementType }> = [
  { id: "home", label: "Главная", icon: Home },
  { id: "people", label: "Друзья", icon: Users },
  { id: "splitik", label: "Сплитик", icon: Bot },
  { id: "events", label: "События", icon: CalendarCheck },
  { id: "profile", label: "Профиль", icon: User }
];

const fallbackEvents: EventSummary[] = [
  { id: "demo-1", title: "Поездка в Карпаты", total_kopecks: 3840000, participants_count: 4, status: "active" },
  { id: "demo-2", title: "День рождения Кати", total_kopecks: 720000, participants_count: 5, status: "invite" },
  { id: "demo-3", title: "Новый год", total_kopecks: 295000, participants_count: 3, status: "closed" }
];

const fallbackFriends: FriendOption[] = [
  { id: "demo-alina", initials: "А", name: "Алина Табакеева", subtitle: "вы должны", amount: -1480, tone: "text-red-600" },
  { id: "demo-maxim", initials: "М", name: "Максим Демин", subtitle: "должен вам", amount: 1488, tone: "text-emerald-600" },
  { id: "demo-ivan", initials: "И", name: "Иван Соловьев", subtitle: "ровно", amount: 0, tone: "text-slate-500" }
];

const notifications = {
  incoming: [
    { title: "Максим вернул долг", detail: "Перевод ожидает подтверждения", badge: "+650 ₽" },
    { title: "Катя приглашает вас", detail: "День рождения Кати", badge: "invite" }
  ],
  read: [{ title: "Чек добавлен", detail: "Сплитик подготовил черновик", badge: "ok" }]
};

const initialPermissionState: PermissionState = {
  contacts: { status: "pending", detail: "Выберите контакт явно, без скрытого чтения адресной книги." },
  camera: { status: "pending", detail: "Откроем системный запрос камеры для фото чека." },
  gallery: { status: "pending", detail: "Откроем выбор изображения из Фото или файлов." },
  notifications: { status: "pending", detail: "Запросим уведомления после установки PWA на экран Домой." }
};

const permissions: Array<{ id: PermissionId; label: string; icon: React.ElementType; detail: string }> = [
  { id: "contacts", label: "Контакты", icon: Users, detail: "найти участников быстрее" },
  { id: "camera", label: "Камера", icon: Camera, detail: "снимать чеки сразу" },
  { id: "gallery", label: "Галерея", icon: ImageIcon, detail: "загрузить фото чека" },
  { id: "notifications", label: "Уведомления", icon: Bell, detail: "не забыть оплату" }
];

export default function SplitAppPage() {
  const [tokens, setTokens] = useState<SplitAppTokens | null>(null);
  const [view, setView] = useState<View>("home");
  const [activeView, setActiveView] = useState<View>("home");
  const [previousView, setPreviousView] = useState<View>("home");
  const [eventTab, setEventTab] = useState<EventTab>("active");
  const [notificationTab, setNotificationTab] = useState<NotificationTab>("incoming");
  const [summary, setSummary] = useState<HomeSummary | null>(null);
  const [currentUser, setCurrentUser] = useState<UserProfile | null>(null);
  const [events, setEvents] = useState<EventSummary[]>(fallbackEvents);
  const [selectedEventId, setSelectedEventId] = useState<string | null>(null);
  const [eventReceipts, setEventReceipts] = useState<EventReceipts>({});
  const [isCreatingEvent, setIsCreatingEvent] = useState(false);
  const [newEventName, setNewEventName] = useState("");
  const [friendships, setFriendships] = useState<Friendship[]>([]);
  const [selectedEventFriendIds, setSelectedEventFriendIds] = useState<string[]>([]);
  const [message, setMessage] = useState("");
  const [permissionState, setPermissionState] = useState<PermissionState>(initialPermissionState);
  const [chatMessages, setChatMessages] = useState<ChatMessage[]>([
    { id: "hello", from: "splitik", text: "Привет! Я Сплитик, чем могу помочь?" },
    { id: "hint", from: "splitik", text: "Могу разобрать чек, спросить кто что ел или напомнить кому вернуть долг." }
  ]);
  const [chatDraft, setChatDraft] = useState("");
  const [splitikAttachments, setSplitikAttachments] = useState<SplitikAttachment[]>([]);
  const [isSplitikAttachmentUploading, setIsSplitikAttachmentUploading] = useState(false);
  const [splitikSessionId, setSplitikSessionId] = useState<string | null>(null);
  const [isSplitikSending, setIsSplitikSending] = useState(false);
  const [problemReport, setProblemReport] = useState<ProblemReportState | null>(null);
  const [problemDraft, setProblemDraft] = useState("");
  const [isProblemSending, setIsProblemSending] = useState(false);
  const galleryInputRef = useRef<HTMLInputElement | null>(null);

  const navigate = useCallback((nextView: View) => {
    setPreviousView(view);
    setView(nextView);
    window.history.replaceState(null, "", `#${nextView}`);
  }, [view]);

  const clearExpiredSession = useCallback(() => {
    clearTokens();
    setTokens(null);
    setCurrentUser(null);
    setSummary(null);
    navigate("home");
    setMessage("Сессия истекла. Войдите через Яндекс еще раз.");
  }, [navigate]);

  const authedApi = useCallback(<T,>(path: string, init: RequestInit = {}) => {
    return api<T>(path, tokens, init, (nextTokens) => {
      setTokens(nextTokens);
      setCurrentUser(nextTokens.user ?? null);
    });
  }, [tokens]);

  const reportProblem = useCallback(
    async ({
      screen,
      message: reportMessage,
      mode = "automatic_error",
      requestId,
      metadata,
      userDescription
    }: {
      screen: ClientReportScreen;
      message: string;
      mode?: "automatic_error" | "manual_feedback";
      requestId?: string;
      metadata?: Record<string, unknown>;
      userDescription?: string;
    }) => {
      try {
        await reportClientIssue(
          {
            kind: mode,
            severity: mode === "automatic_error" ? "error" : "warning",
            screen,
            message: reportMessage,
            user_description: userDescription,
            request_id: requestId,
            contact_allowed: Boolean(userDescription && currentUser?.email),
            contact: currentUser?.email ?? currentUser?.phone_number,
            metadata
          },
          tokens
        );
      } catch {
        // Reporting must never block the user's main workflow or reveal internals.
      }
    },
    [currentUser?.email, currentUser?.phone_number, tokens]
  );

  const notifyProblem = useCallback(
    (error: unknown, screen: ClientReportScreen, fallbackMessage: string, metadata: Record<string, unknown> = {}) => {
      const requestId = error instanceof ApiError ? error.requestId : undefined;
      const errorName = error instanceof Error ? error.name : "UnknownError";
      const reportMetadata = {
        ...metadata,
        error_name: errorName,
        error_message: error instanceof Error ? error.message : String(error ?? "unknown")
      };
      void reportProblem({
        screen,
        message: fallbackMessage,
        mode: "automatic_error",
        requestId,
        metadata: reportMetadata
      });
      setProblemReport({
        open: true,
        screen,
        mode: "automatic_error",
        message: "Мы зафиксировали ошибку и отправили отчет.",
        requestId,
        metadata: reportMetadata
      });
      setMessage("Мы зафиксировали ошибку и отправили отчет. Исправим в ближайшее время.");
    },
    [reportProblem]
  );

  const openProblemReport = useCallback(
    (screen: ClientReportScreen = viewToReportScreen(view), mode: "automatic_error" | "manual_feedback" = "manual_feedback") => {
      setProblemReport({
        open: true,
        screen,
        mode,
        message: mode === "automatic_error" ? "Мы зафиксировали ошибку и отправили отчет." : "Расскажите, что пошло не так."
      });
      setProblemDraft("");
    },
    [view]
  );

  const handleInitialDataError = useCallback((error: unknown) => {
    setEvents(fallbackEvents);
    if (error instanceof ApiError && (error.status === 401 || error.status === 403)) {
      clearExpiredSession();
      return;
    }
    notifyProblem(error, "home", "Не удалось синхронизировать данные.", { action: "initial_sync" });
  }, [clearExpiredSession, notifyProblem]);

  useEffect(() => {
    const storedTokens = loadTokens();
    setTokens(storedTokens);
    setCurrentUser(storedTokens?.user ?? null);

    const hashView = parseHashView(window.location.hash);
    if (hashView) setView(hashView);

    const onHashChange = () => {
      const nextView = parseHashView(window.location.hash);
      if (nextView) setView(nextView);
    };

    window.addEventListener("hashchange", onHashChange);
    const onUnhandledError = (event: ErrorEvent) => {
      notifyProblem(event.error ?? event.message, "unknown", "В приложении произошла ошибка.", { component: "window" });
    };
    const onUnhandledRejection = (event: PromiseRejectionEvent) => {
      notifyProblem(event.reason, "unknown", "В приложении произошла ошибка.", { component: "promise" });
    };
    window.addEventListener("error", onUnhandledError);
    window.addEventListener("unhandledrejection", onUnhandledRejection);

    if ("serviceWorker" in navigator) {
      navigator.serviceWorker.register("/sw.js").catch(() => undefined);
    }

    handleYandexOAuthCallback()
      .then((nextTokens) => {
        if (nextTokens) {
          setTokens(nextTokens);
          setCurrentUser(nextTokens.user ?? null);
          setMessage("Вы вошли через Яндекс.");
        }
      })
      .catch((error) => setMessage(error instanceof Error ? error.message : "Не удалось войти."));

    return () => {
      window.removeEventListener("hashchange", onHashChange);
      window.removeEventListener("error", onUnhandledError);
      window.removeEventListener("unhandledrejection", onUnhandledRejection);
    };
  }, [notifyProblem]);

  useEffect(() => {
    if (!tokens) return;
    Promise.all([
      authedApi<HomeSummary>("/api/home/summary"),
      authedApi<EventPage>("/api/events"),
      authedApi<UserProfile>("/api/users/me"),
      authedApi<FriendshipPage>("/api/friends?status=accepted&limit=50")
    ])
      .then(([nextSummary, eventPage, user, friendshipPage]) => {
        setSummary(nextSummary);
        setCurrentUser(user);
        const nextEvents = pageItems(eventPage).map(normalizeEvent);
        setEvents(nextEvents.length ? nextEvents : fallbackEvents);
        setFriendships(pageItems(friendshipPage));
      })
      .catch(handleInitialDataError);
  }, [authedApi, handleInitialDataError, tokens]);

  useEffect(() => {
    if (!message) return;
    const timeout = setTimeout(() => setMessage(""), 3200);
    return () => clearTimeout(timeout);
  }, [message]);

  const owedToMe = summary?.confirmed?.receivable_kopecks ?? 720000;
  const iOwe = summary?.confirmed?.owed_kopecks ?? 295000;
  const friendOptions = useMemo(() => friendshipsToOptions(friendships), [friendships]);

  const goBack = () => navigate(previousView === view ? "home" : previousView);
  const goHome = () => navigate("home");

  const logout = () => {
    clearTokens();
    setTokens(null);
    setCurrentUser(null);
    setSummary(null);
    setMessage("Вы вышли. Локальная сессия очищена.");
  };

  const submitProblemReport = async (event?: FormEvent<HTMLFormElement>) => {
    event?.preventDefault();
    if (!problemReport || isProblemSending) return;
    setIsProblemSending(true);
    try {
      await reportProblem({
        screen: problemReport.screen,
        message: problemReport.message,
        mode: problemReport.mode,
        requestId: problemReport.requestId,
        metadata: problemReport.metadata,
        userDescription: problemDraft.trim() || undefined
      });
      setProblemReport(null);
      setProblemDraft("");
      setMessage("Спасибо. Мы получили сообщение и посмотрим его.");
    } finally {
      setIsProblemSending(false);
    }
  };

  const updatePermission = (id: PermissionId, status: PermissionStatus, detail: string) => {
    setPermissionState((current) => ({ ...current, [id]: { status, detail } }));
    setMessage(detail);
  };

  const requestCameraPermission = async () => {
    if (!navigator.mediaDevices?.getUserMedia) {
      updatePermission("camera", "unsupported", "Этот браузер не дает доступ к камере через PWA.");
      return;
    }

    try {
      const stream = await navigator.mediaDevices.getUserMedia({ video: { facingMode: { ideal: "environment" } }, audio: false });
      stream.getTracks().forEach((track) => track.stop());
      updatePermission("camera", "granted", "Камера разрешена. Можно снимать чеки из PWA.");
    } catch (error) {
      updatePermission("camera", "denied", permissionErrorMessage(error, "Камера не разрешена."));
    }
  };

  const requestGalleryPermission = async () => {
    if (window.showOpenFilePicker) {
      try {
        const files = await window.showOpenFilePicker({
          multiple: false,
          types: [{ description: "Receipt images", accept: { "image/*": [".png", ".jpg", ".jpeg", ".webp"] } }]
        });
        updatePermission("gallery", files.length ? "granted" : "skipped", files.length ? "Фото выбрано из галереи." : "Выбор фото отменен.");
        return;
      } catch (error) {
        if (galleryInputRef.current) {
          galleryInputRef.current.click();
          return;
        }
        updatePermission("gallery", "skipped", permissionErrorMessage(error, "Выбор фото отменен."));
        return;
      }
    }

    if (!galleryInputRef.current) {
      updatePermission("gallery", "unsupported", "Поле выбора фото не готово. Перезагрузите приложение.");
      return;
    }
    galleryInputRef.current.click();
  };

  const requestNotificationPermission = async () => {
    if (!("Notification" in window)) {
      updatePermission("notifications", "unsupported", "Этот браузер не поддерживает web-уведомления.");
      return;
    }
    if (Notification.permission === "denied") {
      updatePermission("notifications", "denied", "Уведомления уже запрещены в настройках браузера или сайта. Разрешите их в настройках Safari/браузера.");
      return;
    }
    if (isIosDevice() && !isStandalonePwa()) {
      updatePermission("notifications", "skipped", "Откройте SplitApp с ярлыка на домашнем экране, чтобы включить уведомления.");
      return;
    }

    try {
      const result = await Notification.requestPermission();
      if (result !== "granted") {
        updatePermission("notifications", result === "denied" ? "denied" : "skipped", "Уведомления не разрешены.");
        return;
      }
      const pushPublicKey = process.env.NEXT_PUBLIC_WEB_PUSH_PUBLIC_KEY;
      if ("serviceWorker" in navigator) {
        const registration = await navigator.serviceWorker.ready;
        if (registration.pushManager && pushPublicKey) {
          await registration.pushManager.subscribe({
            userVisibleOnly: true,
            applicationServerKey: urlBase64ToUint8Array(pushPublicKey)
          });
        }
      }
      updatePermission(
        "notifications",
        "granted",
        pushPublicKey
          ? "Уведомления разрешены и подписка создана."
          : "Уведомления разрешены. Push-подписка включится после добавления VAPID key."
      );
    } catch (error) {
      updatePermission("notifications", "denied", permissionErrorMessage(error, "Не удалось запросить уведомления."));
    }
  };

  const requestContactsPermission = async () => {
    if (!navigator.contacts?.select) {
      updatePermission("contacts", "unsupported", "Браузер не дает Web Contacts API. Используем ручное добавление или инвайт.");
      return;
    }

    try {
      const contacts = await navigator.contacts.select(["name", "tel", "email"], { multiple: false });
      updatePermission("contacts", contacts.length ? "granted" : "skipped", contacts.length ? "Контакт выбран." : "Выбор контакта отменен.");
    } catch (error) {
      updatePermission("contacts", "skipped", permissionErrorMessage(error, "Выбор контакта отменен."));
    }
  };

  const requestPermission = (id: PermissionId) => {
    const handlers: Record<PermissionId, () => Promise<void>> = {
      contacts: requestContactsPermission,
      camera: requestCameraPermission,
      gallery: requestGalleryPermission,
      notifications: requestNotificationPermission
    };
    void handlers[id]();
  };

  const showFriendCode = async () => {
    if (!tokens || !currentUser) {
      setMessage("Войдите, чтобы показать свой код друга.");
      return;
    }

    try {
      let user = currentUser;
      if (!user.public_handle || !user.discovery_enabled) {
        user = await authedApi<UserProfile>("/api/users/me", {
          method: "PATCH",
          body: JSON.stringify({
            public_handle: user.public_handle || defaultFriendHandle(user),
            discovery_enabled: true
          })
        });
        setCurrentUser(user);
        const nextTokens = { ...tokens, user };
        setTokens(nextTokens);
        saveTokens(nextTokens);
      }

      const code = friendCodeForUser(user);
      const copied = await copyText(code);
      setMessage(copied ? `Ваш код друга: ${code}. Код скопирован.` : `Ваш код друга: ${code}.`);
    } catch (error) {
      if (error instanceof ApiError && error.status === 401) {
        clearExpiredSession();
        return;
      }
      setMessage(error instanceof Error ? `Не удалось показать код: ${error.message}` : "Не удалось показать код друга.");
    }
  };

  const addFriendByCode = async (rawCode: string) => {
    if (!tokens) {
      setMessage("Войдите, чтобы добавить друга.");
      return false;
    }
    const code = normalizeFriendCode(rawCode);
    if (code.length < 3) {
      setMessage("Введите код друга.");
      return false;
    }

    try {
      const users = await authedApi<UserPage>(`/api/users/search?q=${encodeURIComponent(code)}&limit=10`);
      const peer = users.items.find((user) => normalizeFriendCode(user.public_handle ?? "") === code);
      if (!peer) {
        setMessage("Пользователь с таким кодом не найден.");
        return false;
      }
      if (peer.id === currentUser?.id) {
        setMessage("Это ваш код. Отправьте его другу.");
        return false;
      }

      const friendship = await authedApi<Friendship>("/api/friends", {
        method: "POST",
        body: JSON.stringify({ user_id: peer.id })
      });
      if (friendship.status === "accepted") {
        setFriendships((current) => upsertFriendship(current, friendship));
        setMessage(`${peer.name} уже у вас в друзьях.`);
      } else {
        setMessage(`Запрос дружбы отправлен: ${peer.name}.`);
      }
      return true;
    } catch (error) {
      if (error instanceof ApiError && error.status === 401) {
        clearExpiredSession();
        return false;
      }
      setMessage(error instanceof Error ? `Не удалось добавить друга: ${error.message}` : "Не удалось добавить друга.");
      return false;
    }
  };

  const openEvent = async (event: EventSummary) => {
    setSelectedEventId(event.id);
    if (!tokens || event.status === "invite" || eventReceipts[event.id]) return;
    setEventReceipts((current) => ({ ...current, [event.id]: { loading: true, items: [] } }));
    try {
      const page = await authedApi<ReceiptPage>(`/api/events/${event.id}/receipts`);
      setEventReceipts((current) => ({ ...current, [event.id]: { loading: false, items: page.items } }));
    } catch {
      setEventReceipts((current) => ({ ...current, [event.id]: { loading: false, items: [] } }));
      notifyProblem(undefined, "receipts", "Не удалось загрузить чеки события.", { action: "load_receipts", component: "EventsScreen" });
    }
  };

  const closeEvent = () => {
    setSelectedEventId(null);
  };

  const createEventInvite = async (event: EventSummary) => {
    if (!tokens || !isUuid(event.id)) {
      setMessage(`Код события: ${eventInviteDisplayCode(event.id)}`);
      return;
    }
    try {
      const invite = await authedApi<EventInvite>(`/api/events/${event.id}/invites`, {
        method: "POST",
        body: JSON.stringify({})
      });
      const url = `https://split-app.ru/app?invite=${invite.token}`;
      setMessage(`Код события закреплен: ${eventInviteDisplayCode(event.id)}. Ссылка: ${url}`);
    } catch (error) {
      notifyProblem(error, "events", "Не удалось создать код приглашения.", { action: "create_invite", component: "EventDetailScreen" });
    }
  };

  const startReceiptFromEvent = (event: EventSummary) => {
    setSelectedEventId(event.id);
    setChatDraft(`Добавь чек в событие "${eventTitle(event)}": `);
    navigate("splitik");
  };

  const createEvent = async (event?: FormEvent<HTMLFormElement>) => {
    event?.preventDefault();
    const name = newEventName.trim();
    if (!tokens || !name) return;
    try {
      const created = await authedApi<EventSummary>("/api/events", {
        method: "POST",
        body: JSON.stringify({ name })
      });
      const selectedUserIds = selectedEventFriendIds;
      let nextEvent = normalizeEvent(created);
      if (selectedUserIds.length) {
        await authedApi<UserProfile[]>(`/api/events/${created.id}/participants`, {
          method: "POST",
          body: JSON.stringify({ user_ids: selectedUserIds })
        });
        nextEvent = normalizeEvent(eventWithAddedParticipants(nextEvent, selectedUserIds));
      }
      setEvents((current) => [nextEvent, ...current.filter((item) => !item.id.startsWith("demo-"))]);
      setNewEventName("");
      setSelectedEventFriendIds([]);
      setIsCreatingEvent(false);
      setEventTab("active");
      setSelectedEventId(created.id);
      setMessage("Событие создано.");
      void openEvent(nextEvent);
    } catch (error) {
      if (error instanceof ApiError && error.status === 401) {
        clearExpiredSession();
        return;
      }
      notifyProblem(error, "events", "Не удалось создать событие.", { action: "create_event", component: "EventCreateScreen" });
    }
  };

  const decideInvite = async (event: EventSummary, decision: "accept" | "decline") => {
    if (!event.token) {
      setEvents((current) => current.filter((item) => item.id !== event.id));
      setSelectedEventId(null);
      setMessage(decision === "accept" ? "Приглашение принято." : "Приглашение отклонено.");
      return;
    }
    if (!tokens) return;
    try {
      await authedApi(`/api/invites/${event.token}/${decision}`, { method: "POST" });
      setEvents((current) => current.filter((item) => item.id !== event.id));
      setSelectedEventId(null);
      setMessage(decision === "accept" ? "Приглашение принято." : "Приглашение отклонено.");
    } catch {
      notifyProblem(undefined, "events", "Не удалось обработать приглашение.", { action: "decide_invite", component: "EventsScreen" });
    }
  };

  const sendSplitikMessage = async (event?: FormEvent<HTMLFormElement>) => {
    event?.preventDefault();
    const text = chatDraft.trim();
    if ((!text && !splitikAttachments.length) || !tokens || isSplitikSending || isSplitikAttachmentUploading) return;
    const splitikEventId = isUuid(selectedEventId) ? selectedEventId : null;
    const messageText = text || "Создай черновик чека по фото";
    const userMessage = {
      id: `u-${Date.now()}`,
      from: "user" as const,
      text: splitikAttachments.length
        ? `${messageText}\n\n${splitikAttachments.map((attachment) => `Фото: ${attachment.filename}`).join("\n")}`
        : messageText
    };
    setChatMessages((items) => [...items, userMessage]);
    setChatDraft("");
    setSplitikAttachments([]);
    setIsSplitikSending(true);
    try {
      const response = await authedApi<SplitikMessageResponse>("/api/splitik/messages", {
        method: "POST",
        body: JSON.stringify({
          session_id: splitikSessionId,
          mode: splitikEventId ? "event" : "general",
          message: messageText,
          entry_point: splitikEventId ? { type: "event", event_id: splitikEventId } : undefined,
          attachment_ids: splitikAttachments.map((attachment) => attachment.id)
        })
      });
      setSplitikSessionId(response.session_id);
      setChatMessages((items) => [
        ...items,
        {
          id: response.message_id || `s-${Date.now()}`,
          from: "splitik",
          text: response.assistant_message,
          drafts: response.drafts ?? [],
          questions: response.questions ?? []
        }
      ]);
    } catch (error) {
      const requestId = error instanceof ApiError ? error.requestId : undefined;
      void reportProblem({
        screen: "splitik",
        message: "Сплитик сейчас не смог ответить.",
        mode: "automatic_error",
        requestId,
        metadata: {
          action: "splitik_message",
          component: "SplitikScreen",
          error_name: error instanceof Error ? error.name : "UnknownError",
          error_message: error instanceof Error ? error.message : String(error ?? "unknown")
        }
      });
      setMessage("Сплитик сейчас не смог ответить. Попробуйте еще раз чуть позже.");
      setChatMessages((items) => [
        ...items,
        { id: `s-${Date.now()}`, from: "splitik", text: splitikErrorMessage(error) }
      ]);
    } finally {
      setIsSplitikSending(false);
    }
  };

  const confirmSplitikDraft = async (draftId: string) => {
    if (!tokens) return;
    try {
      await authedApi(`/api/splitik/drafts/${draftId}/commit`, { method: "POST" });
      setChatMessages((items) =>
        items.map((item) => ({
          ...item,
          drafts: item.drafts?.map((draft) => (draft.id === draftId ? { ...draft, status: "committed" } : draft))
        }))
      );
      const eventPage = await authedApi<EventPage>("/api/events");
      const nextEvents = pageItems(eventPage).map(normalizeEvent);
      setEvents(nextEvents.length ? nextEvents : fallbackEvents);
      setMessage("Черновик подтвержден.");
    } catch (error) {
      setMessage(splitikErrorMessage(error));
    }
  };

  const uploadSplitikAttachment = async (file: File) => {
    if (!tokens || isSplitikAttachmentUploading) return;
    setIsSplitikAttachmentUploading(true);
    const formData = new FormData();
    formData.append("file", file);
    try {
      const attachment = await authedApi<SplitikAttachment>("/api/splitik/attachments", {
        method: "POST",
        body: formData
      });
      setSplitikAttachments((items) => [...items, attachment]);
      setChatDraft((current) => current || "Создай черновик чека по фото");
      setMessage("Фото чека прикреплено.");
    } catch (error) {
      const requestId = error instanceof ApiError ? error.requestId : undefined;
      void reportProblem({
        screen: "splitik",
        message: "Не удалось прикрепить фото чека.",
        mode: "automatic_error",
        requestId,
        metadata: {
          action: "splitik_attachment",
          component: "SplitikScreen",
          error_name: error instanceof Error ? error.name : "UnknownError",
          error_message: error instanceof Error ? error.message : String(error ?? "unknown")
        }
      });
      setMessage("Не удалось прикрепить фото чека. Попробуйте еще раз.");
    } finally {
      setIsSplitikAttachmentUploading(false);
    }
  };

  return (
    <main className="min-h-dvh w-full overflow-x-hidden bg-[#f5f5f7] text-slate-950">
      {!tokens ? (
        <AuthScreen onLogin={startYandexLogin} />
      ) : (
        <PhoneShell
          view={activeView}
          title={viewTitle(view)}
          onBack={goBack}
          onHome={goHome}
          onNavigate={navigate}
          showHeader={view === "home"}
          showBack={view !== "home"}
          onNotifications={() => navigate("notifications")}
          onLogout={logout}
          loggedIn={Boolean(tokens)}
        >
          <WorkspaceScreen
            view={view}
            onViewSettled={setActiveView}
            events={events}
            friendOptions={friendOptions}
            eventTab={eventTab}
            onEventTab={setEventTab}
            selectedEventId={selectedEventId}
            eventReceipts={eventReceipts}
            onOpenEvent={openEvent}
            onCloseEvent={closeEvent}
            onInviteDecision={decideInvite}
            onCreateEventInvite={createEventInvite}
            onAddReceipt={startReceiptFromEvent}
            isCreatingEvent={isCreatingEvent}
            newEventName={newEventName}
            selectedEventFriendIds={selectedEventFriendIds}
            onSelectedEventFriendIds={setSelectedEventFriendIds}
            onCreateEventOpen={() => {
              setIsCreatingEvent(true);
              setSelectedEventId(null);
              setEventTab("active");
              navigate("events");
            }}
            onNewEventName={setNewEventName}
            onCreateEvent={createEvent}
            onCancelCreateEvent={() => setIsCreatingEvent(false)}
            notificationTab={notificationTab}
            onNotificationTab={setNotificationTab}
            owedToMe={owedToMe}
            iOwe={iOwe}
            currentUser={currentUser}
            permissionState={permissionState}
            onPermission={requestPermission}
            onReportProblem={() => openProblemReport("profile", "manual_feedback")}
            chatMessages={chatMessages}
            chatDraft={chatDraft}
            onChatDraft={setChatDraft}
            onSendChat={sendSplitikMessage}
            isSplitikSending={isSplitikSending}
            attachments={splitikAttachments}
            isAttachmentUploading={isSplitikAttachmentUploading}
            onAttachReceipt={uploadSplitikAttachment}
            onConfirmDraft={confirmSplitikDraft}
            onShowFriendCode={showFriendCode}
            onAddFriendByCode={addFriendByCode}
            onNavigate={navigate}
          />
        </PhoneShell>
      )}

      <div className="fixed bottom-4 left-1/2 z-50 w-[min(92vw,420px)] -translate-x-1/2" aria-live="polite">
        <AnimatePresence>
          {message ? (
            <motion.div
              className="rounded-lg border border-white/16 bg-white px-4 py-3 text-sm shadow-[0_20px_60px_rgba(0,0,0,0.24)]"
              initial={{ opacity: 0, y: 12 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: 12 }}
            >
              {message}
            </motion.div>
          ) : null}
        </AnimatePresence>
      </div>
      <ProblemReportSheet
        state={problemReport}
        draft={problemDraft}
        isSending={isProblemSending}
        onDraft={setProblemDraft}
        onSubmit={submitProblemReport}
        onClose={() => setProblemReport(null)}
      />
      <input
        ref={galleryInputRef}
        type="file"
        accept="image/*"
        className="hidden"
        onChange={(event) => {
          updatePermission(
            "gallery",
            event.currentTarget.files?.length ? "granted" : "skipped",
            event.currentTarget.files?.length ? "Фото выбрано из галереи." : "Выбор фото отменен."
          );
          event.currentTarget.value = "";
        }}
      />
    </main>
  );
}

function ProblemReportSheet({
  state,
  draft,
  isSending,
  onDraft,
  onSubmit,
  onClose
}: {
  state: ProblemReportState | null;
  draft: string;
  isSending: boolean;
  onDraft: (value: string) => void;
  onSubmit: (event?: FormEvent<HTMLFormElement>) => void;
  onClose: () => void;
}) {
  return (
    <AnimatePresence>
      {state?.open ? (
        <motion.div
          className="fixed inset-0 z-[60] grid items-end bg-slate-950/28 px-3 pb-[max(env(safe-area-inset-bottom),12px)] backdrop-blur-[2px]"
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
        >
          <motion.form
            onSubmit={onSubmit}
            className="mx-auto grid w-full max-w-[440px] gap-4 rounded-[28px] bg-white p-5 shadow-[0_24px_70px_rgba(15,23,42,0.28)]"
            initial={{ y: 24 }}
            animate={{ y: 0 }}
            exit={{ y: 24 }}
            transition={{ duration: 0.2 }}
          >
            <div className="flex items-start gap-3">
              <span className="grid h-12 w-12 shrink-0 place-items-center rounded-2xl bg-[#eef1f7] text-[#1f3d8f]">
                <MessageSquareWarning className="h-6 w-6" />
              </span>
              <div className="min-w-0">
                <h2 className="text-xl font-black leading-tight">
                  {state.mode === "automatic_error" ? "Мы зафиксировали ошибку" : "Сообщить о проблеме"}
                </h2>
                <p className="mt-1 text-sm font-semibold leading-5 text-slate-500">
                  {state.mode === "automatic_error"
                    ? "Отчет уже отправлен на сервер. Можно коротко описать, что вы делали перед этим."
                    : "Напишите, что не сработало или что было непонятно. Мы посмотрим это на сервере."}
                </p>
              </div>
            </div>
            <label className="grid gap-2 text-sm font-black text-slate-700">
              Описание
              <textarea
                value={draft}
                onChange={(event) => onDraft(event.target.value)}
                maxLength={2000}
                className="min-h-[112px] resize-none rounded-2xl border border-slate-200 bg-[#f8fafc] px-3 py-3 text-base font-semibold leading-6 text-slate-950 outline-none transition focus:border-[#1f3d8f] focus:ring-2 focus:ring-[#1f3d8f]/20"
                placeholder="Например: нажал создать событие, экран завис и данные не обновились"
              />
            </label>
            <div className="grid grid-cols-2 gap-2">
              <Button type="button" variant="secondary" onClick={onClose} className="min-h-12 rounded-2xl bg-[#eef1f7] text-sm font-black text-slate-700 hover:bg-[#e2e7f2]">
                Закрыть
              </Button>
              <Button type="submit" disabled={isSending} className="min-h-12 rounded-2xl bg-[#1f3d8f] text-sm font-black text-white hover:bg-[#1f3d8f]/90 disabled:opacity-60">
                {isSending ? "Отправляем..." : "Отправить"}
              </Button>
            </div>
          </motion.form>
        </motion.div>
      ) : null}
    </AnimatePresence>
  );
}

function PhoneShell({
  view,
  title,
  loggedIn,
  showHeader,
  showBack,
  children,
  onBack,
  onHome,
  onNavigate,
  onNotifications,
  onLogout
}: {
  view: View;
  title: string;
  loggedIn: boolean;
  showHeader: boolean;
  showBack: boolean;
  children: React.ReactNode;
  onBack: () => void;
  onHome: () => void;
  onNavigate: (view: View) => void;
  onNotifications: () => void;
  onLogout: () => void;
}) {
  return (
    <div className="min-h-dvh w-full overflow-x-hidden bg-[#f5f5f7]">
      {showHeader && loggedIn ? (
        <header className="sticky top-0 z-30 flex items-end justify-between gap-2 bg-[#1f3d8f] px-4 pb-4 pt-[max(env(safe-area-inset-top),16px)] text-white">
          <div className="flex min-w-0 items-center gap-2">
            {showBack ? (
              <Button
                type="button"
                aria-label="Назад"
                onClick={onBack}
                variant="ghost"
                size="sm"
                className="grid h-10 w-10 shrink-0 place-items-center rounded-full bg-white/14 p-0 text-white hover:bg-white/20 hover:text-white"
              >
                <ArrowLeft className="h-5 w-5" />
              </Button>
            ) : null}
            <h2 className="truncate text-3xl font-black tracking-normal">{title}</h2>
          </div>
          <div className="flex shrink-0 gap-2">
            <Button
              type="button"
              aria-label="На главную"
              onClick={onHome}
              variant="ghost"
              size="sm"
              className="grid h-10 w-10 place-items-center rounded-full bg-white/14 p-0 text-white hover:bg-white/20 hover:text-white"
            >
              <Home className="h-5 w-5" />
            </Button>
            <Button
              type="button"
              aria-label="Входящие"
              onClick={onNotifications}
              variant="ghost"
              size="sm"
              className="grid h-10 w-10 place-items-center rounded-full bg-white/14 p-0 text-white hover:bg-white/20 hover:text-white"
            >
              <Inbox className="h-5 w-5" />
            </Button>
            <Button
              type="button"
              aria-label="Выйти"
              onClick={onLogout}
              variant="ghost"
              size="sm"
              className="grid h-10 w-10 place-items-center rounded-full bg-white/14 p-0 text-white hover:bg-white/20 hover:text-white"
            >
              <LogOut className="h-5 w-5" />
            </Button>
          </div>
        </header>
      ) : null}

      <section className={cn("relative z-10", loggedIn && "pb-[var(--bottom-nav-reserve)]")}>{children}</section>

      {loggedIn ? (
        <nav
          data-platform-nav="ios-tab-bar"
          className="fixed bottom-0 left-1/2 z-30 w-[var(--nav-width)] -translate-x-1/2 rounded-[28px] border border-white/50 bg-white/72 p-1.5 pb-[max(env(safe-area-inset-bottom),12px)] shadow-[0_18px_46px_rgba(31,61,143,0.22)] backdrop-blur-[22px] supports-[backdrop-filter]:bg-white/62"
        >
          <div className="grid grid-cols-5 gap-1">
            {navItems.map((item) => (
              <BottomNavButton key={item.id} item={item} active={view === item.id} onNavigate={onNavigate} />
            ))}
          </div>
        </nav>
      ) : null}
    </div>
  );
}

function BottomNavButton({
  item,
  active,
  onNavigate
}: {
  item: { id: View; label: string; icon: React.ElementType };
  active: boolean;
  onNavigate: (view: View) => void;
}) {
  const Icon = item.icon;
  return (
    <Button
      asChild
      variant="ghost"
      className={cn(
        "grid min-h-[54px] place-items-center rounded-[18px] px-1 py-1 text-[10px] font-bold text-[#1f3d8f]/62 transition-all duration-200 active:scale-[0.97]",
        active
          ? "bg-white/72 text-[#1f3d8f] shadow-[0_8px_22px_rgba(31,61,143,0.18)] ring-1 ring-white/90"
          : "hover:bg-white/30 hover:text-[#1f3d8f]"
      )}
    >
      <a
        href={`#${item.id}`}
        aria-current={active ? "page" : undefined}
        onClick={(event) => {
          event.preventDefault();
          onNavigate(item.id);
        }}
      >
        <Icon className={cn("h-5 w-5", item.id === "splitik" && "h-8 w-8")} />
        {item.id !== "splitik" ? <span>{item.label}</span> : null}
      </a>
    </Button>
  );
}

function AuthScreen({ onLogin }: { onLogin: () => void }) {
  return (
    <section data-testid="svg-auth-screen" className="grid min-h-dvh bg-[#1f3d8f] px-[var(--page-x)] pb-[max(env(safe-area-inset-bottom),32px)] pt-[max(env(safe-area-inset-top),24px)] text-white">
      <div className="grid content-center gap-4 pb-[clamp(5rem,18dvh,9rem)] pt-[clamp(5rem,20dvh,10rem)]">
        <div>
          <h1 className="text-[clamp(4rem,20vw,5.5rem)] font-black leading-none tracking-normal">Split.</h1>
          <p className="mt-3 text-base font-bold text-[#d2daec]">Делите счета поровну</p>
        </div>
      </div>

      <div className="self-end">
        <Button
          type="button"
          onClick={onLogin}
          variant="secondary"
          size="lg"
          className="min-h-16 w-full rounded-[26px] bg-white px-4 text-xl font-black text-[#111111] shadow-[0_18px_40px_rgba(0,0,0,0.18)] hover:bg-white/92"
        >
          Войти через Яндекс
        </Button>
      </div>

    </section>
  );
}

function WorkspaceScreen({
  view,
  onViewSettled,
  events,
  friendOptions,
  eventTab,
  onEventTab,
  selectedEventId,
  eventReceipts,
  onOpenEvent,
  onCloseEvent,
  onInviteDecision,
  onCreateEventInvite,
  onAddReceipt,
  isCreatingEvent,
  newEventName,
  selectedEventFriendIds,
  onCreateEventOpen,
  onNewEventName,
  onSelectedEventFriendIds,
  onCreateEvent,
  onCancelCreateEvent,
  notificationTab,
  onNotificationTab,
  owedToMe,
  iOwe,
  currentUser,
  permissionState,
  onPermission,
  onReportProblem,
  chatMessages,
  chatDraft,
  onChatDraft,
  onSendChat,
  isSplitikSending,
  attachments,
  isAttachmentUploading,
  onAttachReceipt,
  onConfirmDraft,
  onShowFriendCode,
  onAddFriendByCode,
  onNavigate
}: {
  view: View;
  onViewSettled: (view: View) => void;
  events: EventSummary[];
  friendOptions: FriendOption[];
  eventTab: EventTab;
  onEventTab: (tab: EventTab) => void;
  selectedEventId: string | null;
  eventReceipts: EventReceipts;
  onOpenEvent: (event: EventSummary) => void;
  onCloseEvent: () => void;
  onInviteDecision: (event: EventSummary, decision: "accept" | "decline") => void;
  onCreateEventInvite: (event: EventSummary) => void;
  onAddReceipt: (event: EventSummary) => void;
  isCreatingEvent: boolean;
  newEventName: string;
  selectedEventFriendIds: string[];
  onCreateEventOpen: () => void;
  onNewEventName: (value: string) => void;
  onSelectedEventFriendIds: (ids: string[]) => void;
  onCreateEvent: (event?: FormEvent<HTMLFormElement>) => void;
  onCancelCreateEvent: () => void;
  notificationTab: NotificationTab;
  onNotificationTab: (tab: NotificationTab) => void;
  owedToMe: number;
  iOwe: number;
  currentUser: UserProfile | null;
  permissionState: PermissionState;
  onPermission: (id: PermissionId) => void;
  onReportProblem: () => void;
  chatMessages: ChatMessage[];
  chatDraft: string;
  onChatDraft: (value: string) => void;
  onSendChat: (event?: FormEvent<HTMLFormElement>) => void;
  isSplitikSending: boolean;
  attachments: SplitikAttachment[];
  isAttachmentUploading: boolean;
  onAttachReceipt: (file: File) => void;
  onConfirmDraft: (draftId: string) => void;
  onShowFriendCode: () => void;
  onAddFriendByCode: (code: string) => Promise<boolean>;
  onNavigate: (view: View) => void;
}) {
  return (
    <AnimatePresence mode="wait">
      <motion.div
        key={view}
        className="min-h-[calc(100dvh-74px)] w-full overflow-hidden rounded-t-[24px] bg-[#f5f5f7] pb-5 pt-3"
        initial={{ opacity: 0, y: 16 }}
        animate={{ opacity: 1, y: 0 }}
        exit={{ opacity: 0, y: -10 }}
        transition={{ duration: 0.2 }}
        onAnimationComplete={() => onViewSettled(view)}
      >
        {view === "home" ? (
          <HomeScreen events={events} owedToMe={owedToMe} iOwe={iOwe} onNavigate={onNavigate} onCreateEventOpen={onCreateEventOpen} />
        ) : null}
        {view === "people" ? (
          <PeopleScreen currentUser={currentUser} friendOptions={friendOptions} onShowFriendCode={onShowFriendCode} onAddFriendByCode={onAddFriendByCode} />
        ) : null}
        {view === "profile" ? (
          <ProfileScreen currentUser={currentUser} owedToMe={owedToMe} iOwe={iOwe} permissionState={permissionState} onPermission={onPermission} onReportProblem={onReportProblem} />
        ) : null}
        {view === "events" ? (
          <EventsScreen
            events={events}
            friendOptions={friendOptions}
            activeTab={eventTab}
            onTab={onEventTab}
            selectedEventId={selectedEventId}
            eventReceipts={eventReceipts}
            onOpenEvent={onOpenEvent}
            onCloseEvent={onCloseEvent}
            onInviteDecision={onInviteDecision}
            onCreateEventInvite={onCreateEventInvite}
            onAddReceipt={onAddReceipt}
            isCreatingEvent={isCreatingEvent}
            newEventName={newEventName}
            selectedEventFriendIds={selectedEventFriendIds}
            onNewEventName={onNewEventName}
            onSelectedEventFriendIds={onSelectedEventFriendIds}
            onCreateEvent={onCreateEvent}
            onCancelCreateEvent={onCancelCreateEvent}
          />
        ) : null}
        {view === "notifications" ? (
          <NotificationsScreen activeTab={notificationTab} onTab={onNotificationTab} />
        ) : null}
        {view === "splitik" ? (
          <SplitikScreen
            messages={chatMessages}
            draft={chatDraft}
            onDraft={onChatDraft}
            onSend={onSendChat}
            isSending={isSplitikSending}
            attachments={attachments}
            isAttachmentUploading={isAttachmentUploading}
            onAttachReceipt={onAttachReceipt}
            onConfirmDraft={onConfirmDraft}
          />
        ) : null}
      </motion.div>
    </AnimatePresence>
  );
}

function HomeScreen({
  events,
  owedToMe,
  iOwe,
  onNavigate,
  onCreateEventOpen
}: {
  events: EventSummary[];
  owedToMe: number;
  iOwe: number;
  onNavigate: (view: View) => void;
  onCreateEventOpen: () => void;
}) {
  const mainEvent = events?.[0] ?? fallbackEvents[0];
  const balance = (owedToMe || 0) - (iOwe || 0);
  return (
    <div data-testid="home-balance-screen" className="grid min-h-[calc(100dvh-92px)] w-full overflow-hidden content-start bg-[#1f3d8f] text-white">
      <section className="mx-auto grid w-[var(--content-width)] gap-[var(--home-hero-gap)] pb-[clamp(1.5rem,5dvh,2.25rem)] pt-[clamp(1.5rem,5dvh,2.25rem)]">
        <p className="break-words text-center font-black leading-none tracking-normal" style={{ fontSize: "var(--balance-font)" }}>{money(balance)}</p>
        <div className="flex flex-wrap justify-center gap-x-[clamp(1rem,5vw,1.75rem)] gap-y-3 text-[clamp(0.9375rem,4.7vw,1.25rem)] font-black leading-none">
          <span className="inline-flex items-center gap-2">
            <span className="grid h-8 w-8 place-items-center rounded-md bg-emerald-600 text-emerald-300">
              <ArrowUp className="h-6 w-6" strokeWidth={3.2} />
            </span>
            {money(owedToMe)}
          </span>
          <span className="inline-flex items-center gap-2">
            <span className="grid h-8 w-8 place-items-center rounded-md bg-red-700 text-red-500">
              <ArrowDown className="h-6 w-6" strokeWidth={3.2} />
            </span>
            {money(iOwe)}
          </span>
        </div>
        <Button
          data-testid="home-event-card"
          type="button"
          size={null}
          onClick={() => onNavigate("events")}
          className="grid h-auto w-full min-w-0 max-w-full justify-stretch gap-[clamp(0.875rem,3.6vw,1.25rem)] bg-[#111111] px-[clamp(1.25rem,6vw,2rem)] py-[clamp(1.125rem,5vw,1.5rem)] text-left text-white hover:bg-[#111111]/92"
          style={{ minHeight: "var(--home-event-min-height)", borderRadius: "var(--home-event-radius)" }}
        >
          <span className="break-words text-[clamp(1.125rem,5.6vw,1.625rem)] font-black leading-tight">{eventTitle(mainEvent)}</span>
          <span className="flex items-end justify-between gap-3">
            <AvatarStack count={mainEvent.participants_count ?? mainEvent.participants?.length ?? 0} />
            <span className="min-w-0 break-words pb-1 text-right font-black text-white/38" style={{ fontSize: "var(--home-total-font)" }}>{money(mainEvent.total_kopecks ?? 0)}</span>
          </span>
        </Button>
        <div className="grid grid-cols-[repeat(3,minmax(0,1fr))] gap-[clamp(0.5rem,3vw,1rem)]">
          <QuickAction icon={ScanLine} label="Сканировать чек" onClick={() => onNavigate("splitik")} />
          <QuickAction icon={Plus} label="Добавить платеж" onClick={onCreateEventOpen} />
          <QuickAction icon={Inbox} label="Входящие" onClick={() => onNavigate("notifications")} />
        </div>
      </section>

      <section className="rounded-t-[28px] bg-[#f5f5f7] pb-[var(--bottom-nav-reserve)] pt-[clamp(1.5rem,5vw,2rem)] text-slate-950">
        <div className="mx-auto w-[var(--content-width)]">
        <div className="mb-[clamp(1.25rem,5vw,1.75rem)] flex items-center justify-between gap-4">
          <h3 className="text-[clamp(1.625rem,7vw,1.875rem)] font-black leading-none">Активность</h3>
          <Badge className="rounded-full bg-[#d2d6e6] px-4 py-1.5 text-base font-black text-[#1f3d8f]">Все</Badge>
        </div>
        <div className="grid gap-0">
        {[
          ["Алина добавила Ужин", "Карпаты", "-1488 ₽", "text-red-600"],
          ["Максим вернул долг", "Перевод сегодня", "+650 ₽", "text-emerald-600"],
          ["Иван создал событие", "Новое событие 3 мин", "-", "text-slate-500"]
        ].map(([title, detail, amount, tone]) => (
          <div key={title} className="grid grid-cols-[var(--activity-avatar-size)_minmax(0,1fr)] items-center gap-3 border-b border-slate-200 py-4 last:border-b-0 sm:grid-cols-[var(--activity-avatar-size)_minmax(0,1fr)_auto]">
            <ActivityAvatar>{title[0]}</ActivityAvatar>
            <div className="min-w-0">
              <p className="break-words font-black leading-tight" style={{ fontSize: "var(--activity-title-font)" }}>{title}</p>
              <p className="break-words font-bold leading-tight text-slate-400" style={{ fontSize: "var(--activity-detail-font)" }}>{detail}</p>
            </div>
            <span className={cn("col-start-2 text-[clamp(1rem,5vw,1.375rem)] font-black sm:col-start-auto", tone)}>{amount}</span>
          </div>
        ))}
        </div>
        </div>
      </section>
    </div>
  );
}

function AvatarStack({ count }: { count: number }) {
  const visible = fallbackFriends.slice(0, 3);
  const overflow = Math.max(0, count - visible.length);
  return (
    <span className="flex items-center pl-1">
      {visible.map((friend, index) => (
        <span
          key={friend.id}
          className={cn(
            "-ml-2 grid place-items-center rounded-full border-2 border-[#111111] font-black",
            index === 0 && "ml-0 bg-[#bbb2d5] text-[#654da1]",
            index === 1 && "bg-[#d8d9e4] text-[#1f3d8f]",
            index === 2 && "bg-[#c9d0e2] text-[#0645d8]"
          )}
          style={{ width: "var(--avatar-stack-size)", height: "var(--avatar-stack-size)", fontSize: "var(--avatar-stack-font)" }}
        >
          {friend.initials}
        </span>
      ))}
      {overflow ? (
        <span className="-ml-2 grid place-items-center rounded-full border-2 border-[#111111] bg-slate-500 font-black text-white" style={{ width: "var(--avatar-stack-size)", height: "var(--avatar-stack-size)", fontSize: "var(--avatar-stack-font)" }}>
          +{overflow}
        </span>
      ) : null}
    </span>
  );
}

function QuickAction({
  icon: Icon,
  label,
  onClick,
  showBadge = false
}: {
  icon: React.ElementType;
  label: string;
  onClick: () => void;
  showBadge?: boolean;
}) {
  return (
    <Button type="button" onClick={onClick} variant="ghost" className="grid h-auto min-h-[var(--action-min-height)] min-w-0 place-items-center rounded-2xl p-0 text-center text-[clamp(0.75rem,3.9vw,1rem)] font-bold leading-tight text-white hover:bg-white/10 hover:text-white">
      <span className="relative grid place-items-center rounded-full bg-[#111111]" style={{ width: "var(--action-icon-size)", height: "var(--action-icon-size)" }}>
        <Icon style={{ width: "var(--action-icon-svg)", height: "var(--action-icon-svg)" }} strokeWidth={2.2} />
        {showBadge ? <span className="absolute right-5 top-5 h-4 w-4 rounded-full bg-red-500" /> : null}
      </span>
      <span>{label}</span>
    </Button>
  );
}

function ActivityAvatar({ children }: { children: React.ReactNode }) {
  return <span className="grid place-items-center rounded-full bg-[#c7cee0] text-[clamp(1.5rem,8vw,2.125rem)] font-black text-[#1f3d8f]" style={{ width: "var(--activity-avatar-size)", height: "var(--activity-avatar-size)" }}>{children}</span>;
}

function SvgScreenFrame({
  testId,
  title,
  action,
  hero,
  children,
  sheetClassName
}: {
  testId: string;
  title: string;
  action?: React.ReactNode;
  hero?: React.ReactNode;
  children: React.ReactNode;
  sheetClassName?: string;
}) {
  return (
    <div data-testid={testId} className="grid min-h-[calc(100dvh-92px)] bg-[#1f3d8f] text-white">
      <section className="mx-auto grid w-[var(--content-width)] gap-5 pb-8 pt-6">
        <div className="flex min-h-12 items-center justify-between gap-4">
          <h2 className="text-[32px] font-black leading-none tracking-normal">{title}</h2>
          {action}
        </div>
        {hero}
      </section>
      <section
        data-testid="svg-screen-sheet"
        className={cn("min-h-[58dvh] rounded-t-[28px] bg-[#f5f5f7] pb-[var(--bottom-nav-reserve)] pt-7 text-slate-950", sheetClassName)}
      >
        <div className="mx-auto flex min-h-0 w-[var(--content-width)] flex-1 flex-col">{children}</div>
      </section>
    </div>
  );
}

function PeopleScreen({
  currentUser,
  friendOptions,
  onShowFriendCode,
  onAddFriendByCode
}: {
  currentUser: UserProfile | null;
  friendOptions: FriendOption[];
  onShowFriendCode: () => void;
  onAddFriendByCode: (code: string) => Promise<boolean>;
}) {
  const [friendSearch, setFriendSearch] = useState("");
  const [friendCode, setFriendCode] = useState("");
  const [isFriendCodeOpen, setIsFriendCodeOpen] = useState(false);
  const [isAddingFriend, setIsAddingFriend] = useState(false);
  const visibleFriends = (friendOptions.length ? friendOptions : fallbackFriends).filter((friend) => friend.name.toLowerCase().includes(friendSearch.trim().toLowerCase()));
  const myCode = currentUser ? friendCodeForUser(currentUser) : "";
  const addFriend = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setIsAddingFriend(true);
    try {
      const added = await onAddFriendByCode(friendCode);
      if (added) setFriendCode("");
    } finally {
      setIsAddingFriend(false);
    }
  };

  return (
    <SvgScreenFrame
      testId="friends-screen"
      title="Друзья"
      action={
        <Button type="button" variant="ghost" className="grid h-14 w-14 place-items-center rounded-full bg-white/12 p-0 text-white hover:bg-white/20 hover:text-white">
          <Search className="h-7 w-7" />
        </Button>
      }
      hero={
        <div className="flex items-center gap-2 rounded-[22px] bg-white/12 p-2 backdrop-blur">
          <Search className="ml-3 h-5 w-5 text-white/80" />
          <Input
            aria-label="Поиск друзей"
            value={friendSearch}
            onChange={(event) => setFriendSearch(event.target.value)}
            className="min-h-12 flex-1 rounded-2xl border-0 bg-white/0 px-2 text-base font-bold text-white placeholder:text-white/58 focus-visible:ring-white/40"
            placeholder="Найти друга"
          />
        </div>
      }
    >
      <div className="grid gap-4">
        <Button
          data-testid="friend-code-toggle"
          type="button"
          variant="secondary"
          onClick={() => {
            setIsFriendCodeOpen((open) => !open);
            onShowFriendCode();
          }}
          className="flex min-h-12 w-fit items-center gap-2 justify-self-end rounded-full bg-[#d2d6e6] px-4 text-sm font-black text-[#1f3d8f] hover:bg-[#c5cadc]"
        >
          Добавить по коду
          <ChevronDown className={cn("h-4 w-4 transition-transform", isFriendCodeOpen && "rotate-180")} />
        </Button>
        {isFriendCodeOpen ? (
          <div data-testid="friend-code-panel" className="grid gap-3 rounded-[24px] bg-white p-4 shadow-sm">
            <div className="flex items-center justify-between gap-3">
              <div>
                <p className="text-base font-black">Добавить друга по коду</p>
                <p className="text-sm font-bold text-slate-500">{myCode ? `Ваш код: ${myCode}` : "Введите код друга или покажите свой."}</p>
              </div>
              <Badge className="rounded-full bg-[#eef1f7] px-3 py-2 text-xs font-black text-[#1f3d8f]">Мой код</Badge>
            </div>
            <form className="flex gap-2" onSubmit={addFriend}>
              <Input
                aria-label="Код друга"
                data-testid="friend-code-input"
                value={friendCode}
                onChange={(event) => setFriendCode(event.target.value)}
                className="min-h-12 flex-1 rounded-2xl border-slate-200 bg-white px-3 text-base font-bold text-slate-950 focus-visible:ring-[#1f3d8f]"
                placeholder="Например, ILYA-4821"
              />
              <Button type="submit" disabled={isAddingFriend} className="min-h-12 rounded-2xl bg-[#1f3d8f] px-4 text-sm font-black text-white hover:bg-[#1f3d8f]/90 disabled:opacity-60">
                {isAddingFriend ? "..." : "Добавить"}
              </Button>
            </form>
          </div>
        ) : null}
        <div className="grid gap-0">
        {visibleFriends.map((friend) => (
          <Button
            key={friend.name}
            type="button"
            variant="outline"
            className="grid h-auto w-full grid-cols-[64px_1fr_auto] items-center justify-stretch gap-3 rounded-none border-0 border-b border-slate-200 bg-transparent px-0 py-5 text-left shadow-none hover:bg-white/45 last:border-b-0"
          >
            <Avatar>{friend.initials}</Avatar>
            <div>
              <p className="text-[22px] font-black leading-tight">{friend.name}</p>
              <p className="text-lg font-bold leading-tight text-slate-400">{friend.subtitle}</p>
            </div>
            <span className={cn("text-[20px] font-black", friend.tone)}>{friend.amount > 0 ? "+" : ""}{friend.amount} ₽</span>
          </Button>
        ))}
          {!visibleFriends.length ? <p className="py-8 text-center text-base font-bold text-slate-500">Ничего не найдено</p> : null}
        </div>
      </div>
    </SvgScreenFrame>
  );
}

function EventsScreen({
  events,
  friendOptions,
  activeTab,
  onTab,
  selectedEventId,
  eventReceipts,
  onOpenEvent,
  onCloseEvent,
  onInviteDecision,
  onCreateEventInvite,
  onAddReceipt,
  isCreatingEvent,
  newEventName,
  selectedEventFriendIds,
  onNewEventName,
  onSelectedEventFriendIds,
  onCreateEvent,
  onCancelCreateEvent
}: {
  events: EventSummary[];
  friendOptions: FriendOption[];
  activeTab: EventTab;
  onTab: (tab: EventTab) => void;
  selectedEventId: string | null;
  eventReceipts: EventReceipts;
  onOpenEvent: (event: EventSummary) => void;
  onCloseEvent: () => void;
  onInviteDecision: (event: EventSummary, decision: "accept" | "decline") => void;
  onCreateEventInvite: (event: EventSummary) => void;
  onAddReceipt: (event: EventSummary) => void;
  isCreatingEvent: boolean;
  newEventName: string;
  selectedEventFriendIds: string[];
  onNewEventName: (value: string) => void;
  onSelectedEventFriendIds: (ids: string[]) => void;
  onCreateEvent: (event?: FormEvent<HTMLFormElement>) => void;
  onCancelCreateEvent: () => void;
}) {
  const filtered = (events ?? fallbackEvents).filter((event) => {
    if (activeTab === "active") return !event.is_closed && event.status !== "closed" && event.status !== "invite";
    if (activeTab === "closed") return event.is_closed || event.status === "closed";
    return event.status === "invite";
  });
  const visible = filtered.length ? filtered : activeTab === "closed" ? [fallbackEvents[2]] : [fallbackEvents[1]];
  const selectedEvent = selectedEventId ? (events ?? fallbackEvents).find((event) => event.id === selectedEventId) : null;

  if (isCreatingEvent) {
    return (
      <EventCreateScreen
        name={newEventName}
        friendOptions={friendOptions}
        selectedFriendIds={selectedEventFriendIds}
        onName={onNewEventName}
        onSelectedFriendIds={onSelectedEventFriendIds}
        onSubmit={onCreateEvent}
        onCancel={onCancelCreateEvent}
      />
    );
  }

  return selectedEvent ? (
    <EventDetailScreen
      event={selectedEvent}
      friendOptions={friendOptions}
      receipts={eventReceipts[selectedEvent.id]}
      onBack={onCloseEvent}
      onInviteDecision={onInviteDecision}
      onCreateEventInvite={onCreateEventInvite}
      onAddReceipt={onAddReceipt}
    />
  ) : (
    <SvgScreenFrame
      testId="events-screen"
      title="События"
      action={
        <Badge className="rounded-full bg-white/16 px-4 py-2 text-sm font-black text-white">{visible.length}</Badge>
      }
      hero={
      <SegmentedControl
        name="event-tab"
        items={[
          ["invites", "Приглашения"],
          ["active", "Активные"],
          ["closed", "Завершенные"]
        ]}
        active={activeTab}
        onChange={(tab) => onTab(tab as EventTab)}
      />
      }
    >
      <div className="grid gap-3">
      {visible.map((event) => (
        <Card key={event.id} className="overflow-hidden rounded-[28px] border-0 bg-white p-0 shadow-sm">
          <Button type="button" variant="ghost" onClick={() => onOpenEvent(event)} className="grid h-auto min-h-[112px] w-full justify-stretch gap-4 rounded-[28px] p-5 text-left hover:bg-white">
            <span className="flex items-center justify-between gap-3">
              <span className="text-[24px] font-black leading-tight">{eventTitle(event)}</span>
              <span className="rounded-full bg-[#eef1f7] px-4 py-2 text-xs font-black text-[#1f3d8f]">Открыть</span>
            </span>
            <span className="text-base font-bold text-slate-500">
              {event.participants_count ?? event.participants?.length ?? 0} участника · {money(event.total_kopecks ?? 0)}
            </span>
          </Button>
        </Card>
      ))}
      </div>
    </SvgScreenFrame>
  );
}

function EventCreateScreen({
  name,
  friendOptions,
  selectedFriendIds,
  onName,
  onSelectedFriendIds,
  onSubmit,
  onCancel
}: {
  name: string;
  friendOptions: FriendOption[];
  selectedFriendIds: string[];
  onName: (value: string) => void;
  onSelectedFriendIds: (ids: string[]) => void;
  onSubmit: (event?: FormEvent<HTMLFormElement>) => void;
  onCancel: () => void;
}) {
  const availableFriends = friendOptions;
  const toggleFriend = (friendId: string, checked: boolean) => {
    onSelectedFriendIds(
      checked
        ? Array.from(new Set([...selectedFriendIds, friendId]))
        : selectedFriendIds.filter((selectedId) => selectedId !== friendId)
    );
  };

  return (
    <SvgScreenFrame
      testId="event-create-screen"
      title="Новое событие"
      action={<BackPill onBack={onCancel} />}
      hero={<p className="max-w-[280px] text-base font-bold leading-6 text-white/72">Название, участники и правила дележки в одном месте.</p>}
    >
    <form onSubmit={onSubmit} className="grid gap-4">
      <Card className="rounded-2xl border-0 bg-white p-0 shadow-sm">
        <CardHeader className="p-4">
          <CardTitle className="text-2xl font-black">Создание события</CardTitle>
          <p className="mt-1 text-sm font-semibold text-slate-500">Сразу добавьте друзей, которые участвуют в расходах.</p>
        </CardHeader>
      </Card>
      <Card className="grid gap-2 rounded-2xl border-0 bg-white p-3 shadow-sm">
        <label className="text-xs font-black text-slate-500" htmlFor="event-name">Название события</label>
        <Input
          id="event-name"
          value={name}
          onChange={(event) => onName(event.target.value)}
          className="min-h-12 rounded-xl border-slate-200 bg-white px-3 text-sm font-semibold text-slate-950 focus-visible:ring-[#1f3d8f]"
          placeholder="Например, ужин с друзьями"
        />
      </Card>
      <Card className="grid gap-3 rounded-2xl border-0 bg-white p-3 shadow-sm">
        <p className="text-sm font-black">Добавить участников</p>
        <div className="grid gap-2">
          {availableFriends.map((friend) => (
            <label key={friend.name} className="flex min-h-12 items-center gap-3 rounded-xl bg-[#f5f5f7] px-3">
              <input
                type="checkbox"
                checked={selectedFriendIds.includes(friend.id)}
                onChange={(event) => toggleFriend(friend.id, event.currentTarget.checked)}
                className="h-5 w-5 accent-[#1f3d8f]"
              />
              <Avatar>{friend.initials}</Avatar>
              <span className="text-sm font-bold">{friend.name}</span>
            </label>
          ))}
          {!availableFriends.length ? <p className="rounded-xl bg-[#f5f5f7] p-3 text-sm font-semibold text-slate-500">Пока нет друзей для добавления. Пригласите друга по коду после создания события.</p> : null}
        </div>
        <Button type="button" variant="outline" className="min-h-11 rounded-xl border-[#c6cbdc] text-sm font-black text-[#1f3d8f]">Пригласить по коду после создания</Button>
      </Card>
      <div className="grid grid-cols-2 gap-2">
        <Button type="button" variant="secondary" onClick={onCancel} className="min-h-12 rounded-xl bg-white text-sm font-black text-slate-700 hover:bg-white/90">Отмена</Button>
        <Button type="submit" className="min-h-12 rounded-xl bg-[#1f3d8f] px-4 text-sm font-black text-white hover:bg-[#1f3d8f]/90">Создать событие</Button>
      </div>
    </form>
    </SvgScreenFrame>
  );
}

function EventDetailScreen({
  event,
  friendOptions,
  receipts,
  onBack,
  onInviteDecision,
  onCreateEventInvite,
  onAddReceipt
}: {
  event: EventSummary;
  friendOptions: FriendOption[];
  receipts?: { loading: boolean; items: ReceiptSummary[] };
  onBack: () => void;
  onInviteDecision: (event: EventSummary, decision: "accept" | "decline") => void;
  onCreateEventInvite: (event: EventSummary) => void;
  onAddReceipt: (event: EventSummary) => void;
}) {
  const participantItems = eventParticipants(event, friendOptions);
  const participantCount = event.participants_count ?? event.participants?.length ?? participantItems.length;
  const inviteCode = eventInviteDisplayCode(event.id);

  if (event.status === "invite") {
    return (
      <SvgScreenFrame testId="event-detail-screen" title="Приглашение" action={<BackPill onBack={onBack} />}>
        <Card className="grid gap-4 rounded-[28px] border-0 bg-white p-5 shadow-sm">
          <p className="text-[28px] font-black leading-tight">{eventTitle(event)}</p>
          <p className="text-base font-bold text-slate-500">Предпросмотр приглашения. После принятия событие появится в активных.</p>
          <div className="grid grid-cols-2 gap-2">
            <Button type="button" variant="secondary" onClick={() => onInviteDecision(event, "decline")} className="min-h-12 rounded-2xl bg-slate-100 text-sm font-black text-slate-700">Отказаться</Button>
            <Button type="button" onClick={() => onInviteDecision(event, "accept")} className="min-h-12 rounded-2xl bg-[#1f3d8f] text-sm font-black text-white hover:bg-[#1f3d8f]/90">Согласиться</Button>
          </div>
        </Card>
      </SvgScreenFrame>
    );
  }

  return (
    <SvgScreenFrame testId="event-detail-screen" title="Событие" action={<BackPill onBack={onBack} />}>
      <div className="grid gap-4">
      <Card className="grid gap-4 rounded-[28px] border-0 bg-white p-5 shadow-sm">
        <div>
          <p className="text-[28px] font-black leading-tight">{eventTitle(event)}</p>
          <p className="text-base font-bold text-slate-500">{participantCount} участника · {money(event.total_kopecks ?? 0)}</p>
        </div>
        <div className="grid gap-2 rounded-[24px] bg-[#eef1f7] p-4">
          <span className="text-xs font-black uppercase text-slate-500">Код события</span>
          <span className="text-[32px] font-black tracking-[0.18em] text-[#1f3d8f]">{inviteCode}</span>
        </div>
        <div className="grid grid-cols-2 gap-2">
          <Button type="button" onClick={() => onCreateEventInvite(event)} className="min-h-12 rounded-2xl bg-[#1f3d8f] text-sm font-black text-white hover:bg-[#1f3d8f]/90">Добавить друзей</Button>
          <Button type="button" onClick={() => onAddReceipt(event)} className="min-h-12 rounded-2xl bg-[#111111] text-sm font-black text-white hover:bg-[#111111]/90">Добавить чек</Button>
        </div>
      </Card>
      <ContentPanel title="Участники">
        {eventParticipants(event, friendOptions).map((participant) => (
          <div key={participant.id} className="grid grid-cols-[40px_1fr] items-center gap-2 rounded-xl bg-[#f5f5f7] p-2">
            <Avatar>{participant.initials}</Avatar>
            <div>
              <p className="text-sm font-black">{participant.name}</p>
              <p className="text-xs text-slate-500">{participant.subtitle}</p>
            </div>
          </div>
        ))}
      </ContentPanel>
      <ContentPanel title="Чеки">
        <EventReceiptList receipts={receipts} />
      </ContentPanel>
      </div>
    </SvgScreenFrame>
  );
}

function BackPill({ onBack }: { onBack: () => void }) {
  return (
    <Button type="button" variant="ghost" onClick={onBack} className="min-h-11 rounded-full bg-white/14 px-4 text-sm font-black text-white hover:bg-white/22 hover:text-white">
      Назад
    </Button>
  );
}

function EventReceiptList({ receipts }: { receipts?: { loading: boolean; items: ReceiptSummary[] } }) {
  if (!receipts || receipts.loading) {
    return <p className="py-3 text-sm font-semibold text-slate-500">Обновляем чеки...</p>;
  }
  if (!receipts.items.length) {
    return <p className="py-3 text-sm font-semibold text-slate-500">Чеков пока нет. Добавьте первый чек через Сплитика или событие.</p>;
  }
  return (
    <div className="grid gap-2">
      {receipts.items.map((receipt) => (
        <div key={receipt.id} className="grid grid-cols-[1fr_auto] gap-2 rounded-xl bg-[#f5f5f7] p-3">
          <span>
            <span className="block text-sm font-black">{receipt.title || "Чек"}</span>
            <span className="block text-xs text-slate-500">{receipt.category || receipt.status || "расход"}</span>
          </span>
          <span className="text-sm font-black">{money(receipt.total_amount_kopecks ?? 0)}</span>
        </div>
      ))}
    </div>
  );
}

function NotificationsScreen({
  activeTab,
  onTab
}: {
  activeTab: NotificationTab;
  onTab: (tab: NotificationTab) => void;
}) {
  return (
    <SvgScreenFrame
      testId="notifications-screen"
      title="Входящие"
      action={<Badge className="rounded-full bg-white/16 px-4 py-2 text-sm font-black text-white">{notifications.incoming.length}</Badge>}
      hero={
      <SegmentedControl
        name="notification-tab"
        items={[
          ["incoming", "Входящие"],
          ["read", "Прочитанные"]
        ]}
        active={activeTab}
        onChange={(tab) => onTab(tab as NotificationTab)}
      />
      }
    >
      <div className="grid gap-4">
        <h3 className="text-[30px] font-black leading-none">{activeTab === "incoming" ? "Новые действия" : "История"}</h3>
        <div className="grid gap-0 rounded-[28px] bg-white px-4 shadow-sm">
        {notifications[activeTab].map((item) => (
          <div key={item.title} className="grid grid-cols-[1fr_auto] gap-4 border-b border-slate-200 py-5 last:border-b-0">
            <div>
              <p className="text-[22px] font-black leading-tight">{item.title}</p>
              <p className="text-lg font-bold leading-tight text-slate-400">{item.detail}</p>
            </div>
            <Badge className="h-fit rounded-full bg-[#eef1f7] px-3 py-2 text-xs font-black text-[#1f3d8f]">{item.badge}</Badge>
          </div>
        ))}
        </div>
      </div>
    </SvgScreenFrame>
  );
}

function ProfileScreen({
  currentUser,
  owedToMe,
  iOwe,
  permissionState,
  onPermission,
  onReportProblem
}: {
  currentUser: UserProfile | null;
  owedToMe: number;
  iOwe: number;
  permissionState: PermissionState;
  onPermission: (id: PermissionId) => void;
  onReportProblem: () => void;
}) {
  const profileName = currentUser?.name || "Профиль";
  const profileEmail = currentUser?.email || currentUser?.phone_number || "Войдите через Яндекс";
  const initials = profileName
    .split(" ")
    .filter(Boolean)
    .slice(0, 2)
    .map((part) => part[0])
    .join("")
    .toUpperCase() || "S";

  return (
    <SvgScreenFrame
      testId="profile-screen"
      title="Профиль"
      hero={
      <div className="grid justify-items-center gap-4 py-2 text-center">
        <div className="grid place-items-center overflow-hidden rounded-full bg-[#bbb2d5] text-[clamp(1.75rem,9vw,2.25rem)] font-black text-[#654da1]" style={{ width: "var(--profile-avatar-size)", height: "var(--profile-avatar-size)" }}>
          {currentUser?.avatar_url ? (
            // eslint-disable-next-line @next/next/no-img-element
            <img src={currentUser.avatar_url} alt="" className="h-full w-full object-cover" />
          ) : (
            initials
          )}
        </div>
        <div>
          <p className="text-[30px] font-black leading-tight">{profileName}</p>
          <p className="text-base font-bold text-white/68">{profileEmail}</p>
        </div>
      </div>
      }
    >
      <div className="grid gap-4">
      <ContentPanel title="Баланс">
        <ProfileRow label="Аккаунт" value={profileEmail} tone="text-slate-700" />
        <ProfileRow label="Мне должны" value={money(owedToMe)} tone="text-emerald-600" />
        <ProfileRow label="Я должен" value={money(iOwe)} tone="text-red-600" />
        <ProfileRow label="Активных событий" value="3" tone="text-[#1f3d8f]" />
      </ContentPanel>
      <ContentPanel title="Разрешения">
        {permissions.map((item) => {
          const Icon = item.icon;
          const state = permissionState[item.id];
          return (
            <Button
              key={item.id}
              type="button"
              onClick={() => onPermission(item.id)}
              variant="ghost"
              className="grid h-auto w-full grid-cols-[40px_1fr_auto] items-center justify-stretch gap-2 rounded-xl bg-white p-3 text-left hover:bg-[#f5f5f7]"
            >
              <span className="grid h-10 w-10 place-items-center rounded-full bg-[#d2daec] text-[#1f3d8f]">
                <Icon className="h-5 w-5" />
              </span>
              <span>
                <span className="block text-sm font-black">{item.label}</span>
                <span className="block text-xs text-slate-500">{state.status === "pending" ? item.detail : state.detail}</span>
              </span>
              <Badge variant="outline" className="text-[10px]">
                {permissionLabel(state.status)}
              </Badge>
            </Button>
          );
        })}
      </ContentPanel>
      <ContentPanel title="Помощь">
        <Button
          type="button"
          onClick={onReportProblem}
          variant="ghost"
          className="grid h-auto w-full grid-cols-[40px_1fr_auto] items-center justify-stretch gap-2 rounded-xl bg-white p-3 text-left hover:bg-[#f5f5f7]"
        >
          <span className="grid h-10 w-10 place-items-center rounded-full bg-[#d2daec] text-[#1f3d8f]">
            <MessageSquareWarning className="h-5 w-5" />
          </span>
          <span>
            <span className="block text-sm font-black">Сообщить о проблеме</span>
            <span className="block text-xs text-slate-500">Опишите, что пошло не так. Мы получим экран и состояние приложения.</span>
          </span>
          <Badge variant="outline" className="text-[10px]">
            Помощь
          </Badge>
        </Button>
      </ContentPanel>
      </div>
    </SvgScreenFrame>
  );
}

function ProfileRow({ label, value, tone }: { label: string; value: string; tone: string }) {
  return (
    <div className="flex items-center justify-between rounded-xl bg-white p-3">
      <span className="text-sm font-bold text-slate-600">{label}</span>
      <span className={cn("text-sm font-black", tone)}>{value}</span>
    </div>
  );
}

function SplitikScreen({
  messages,
  draft,
  onDraft,
  onSend,
  isSending,
  attachments,
  isAttachmentUploading,
  onAttachReceipt,
  onConfirmDraft
}: {
  messages: ChatMessage[];
  draft: string;
  onDraft: (value: string) => void;
  onSend: (event?: FormEvent<HTMLFormElement>) => void;
  isSending: boolean;
  attachments: SplitikAttachment[];
  isAttachmentUploading: boolean;
  onAttachReceipt: (file: File) => void;
  onConfirmDraft: (draftId: string) => void;
}) {
  return (
    <SvgScreenFrame
      testId="splitik-screen"
      title="Сплитик"
      sheetClassName="flex min-h-[calc(100dvh-148px)] flex-col pt-4"
      hero={
        <div className="grid justify-items-center py-1">
          <div className="grid h-24 w-24 place-items-center rounded-[28px] border-4 border-white/90 bg-white/8 text-white">
            <Bot className="h-12 w-12" strokeWidth={2.5} />
          </div>
        </div>
      }
    >
      <div data-testid="splitik-chat-shell" className="flex min-h-0 flex-1 flex-col pb-[112px]">
        <div data-testid="splitik-message-list" className="flex min-h-0 flex-1 flex-col justify-end gap-3 overflow-y-auto px-1 pb-3 pt-2">
          <div data-testid="splitik-intro-card" className="mb-1 grid justify-items-center gap-3 rounded-[28px] bg-white px-4 py-5">
            <div className="grid h-20 w-20 place-items-center rounded-[24px] border-4 border-[#111111] bg-[#f5f5f7] text-[#111111]">
              <Bot className="h-10 w-10" strokeWidth={2.6} />
            </div>
            <div className="mr-auto grid gap-3">
              <div className="w-fit max-w-[92%] rounded-[18px] bg-[#eef1f7] px-4 py-3 text-base font-black leading-6 text-slate-900">Привет! Я Сплитик, чем могу помочь?</div>
              <div className="w-fit max-w-[92%] rounded-[18px] bg-[#eef1f7] px-4 py-3 text-base font-black leading-6 text-slate-900">Могу разобрать чек, спросить кто что ел или напомнить кому вернуть долг.</div>
            </div>
          </div>
          {messages.slice(2).map((item) => (
            <div key={item.id} className={cn("grid gap-2", item.from === "user" ? "justify-items-end" : "justify-items-start")}>
              <div
                className={cn(
                  "max-w-[86%] rounded-2xl px-3 py-2 text-[15px] leading-6",
                  item.from === "user" ? "ml-auto bg-[#1f3d8f] font-bold text-white" : "mr-auto bg-[#eef1f7] font-medium text-slate-900"
                )}
              >
                {item.from === "splitik" ? <MarkdownMessage text={item.text} /> : item.text}
              </div>
              {item.from === "splitik" && item.drafts?.length ? (
                <div className="grid w-full max-w-[92%] gap-2">
                  {item.drafts.map((draftItem) => (
                    <SplitikDraftCard key={draftItem.id} draft={draftItem} onConfirm={onConfirmDraft} onEdit={onDraft} />
                  ))}
                </div>
              ) : null}
              {item.from === "splitik" && item.questions?.length ? (
                <div className="grid w-full max-w-[92%] gap-1 rounded-2xl border border-[#d8dfeb] bg-white px-3 py-3 text-sm font-bold text-slate-700">
                  <span className="text-[11px] font-black uppercase tracking-wide text-[#1f3d8f]">Нужно уточнить</span>
                  {item.questions.map((question) => (
                    <button key={question.id} type="button" className="text-left leading-5" onClick={() => onDraft(question.text)}>
                      {question.text}
                    </button>
                  ))}
                </div>
              ) : null}
            </div>
          ))}
        </div>
        {attachments.length ? (
          <div className="fixed inset-x-4 bottom-[calc(150px+env(safe-area-inset-bottom))] z-40 mx-auto flex max-w-[calc(100vw-2rem)] flex-wrap gap-2">
            {attachments.map((attachment) => (
              <span key={attachment.id} className="rounded-full bg-white px-3 py-1.5 text-xs font-black text-[#1f3d8f] shadow-sm">
                {attachment.filename}
              </span>
            ))}
          </div>
        ) : null}
        <form
          onSubmit={onSend}
          data-testid="splitik-composer"
          className="fixed inset-x-4 bottom-[calc(86px+env(safe-area-inset-bottom))] z-40 mx-auto flex max-w-[calc(100vw-2rem)] gap-2 rounded-2xl bg-white p-2 shadow-[0_14px_36px_rgba(15,23,42,0.18)]"
        >
          <Button
            asChild
            type="button"
            aria-label="Прикрепить фото чека"
            variant="ghost"
            className="grid h-12 w-12 shrink-0 place-items-center rounded-xl bg-[#eef1f7] p-0 text-[#1f3d8f] hover:bg-[#dfe5f1]"
          >
            <label>
              {isAttachmentUploading ? <span className="h-4 w-4 animate-spin rounded-full border-2 border-[#1f3d8f]/30 border-t-[#1f3d8f]" /> : <ImageIcon className="h-5 w-5" />}
              <input
                data-testid="splitik-attachment-input"
                type="file"
                accept="image/*"
                className="hidden"
                disabled={isAttachmentUploading || isSending}
                onChange={(event) => {
                  const file = event.currentTarget.files?.[0];
                  if (file) onAttachReceipt(file);
                  event.currentTarget.value = "";
                }}
              />
            </label>
          </Button>
          <Input
            aria-label="Сообщение Сплитику"
            data-testid="splitik-message-input"
            className="min-h-12 flex-1 rounded-xl border-slate-200 bg-white px-3 text-sm text-slate-950 focus-visible:ring-[#1f3d8f]"
            placeholder="Напишите сообщение..."
            value={draft}
            onChange={(event) => onDraft(event.target.value)}
          />
          <Button
            type="submit"
            aria-label="Отправить Сплитику"
            disabled={isSending || isAttachmentUploading || (!draft.trim() && !attachments.length)}
            className="grid h-12 w-12 place-items-center rounded-xl bg-[#1f3d8f] p-0 text-white hover:bg-[#1f3d8f]/90 disabled:opacity-60"
          >
            {isSending ? <span className="h-4 w-4 animate-spin rounded-full border-2 border-white/40 border-t-white" /> : <Send className="h-5 w-5" />}
          </Button>
        </form>
      </div>
    </SvgScreenFrame>
  );
}

function MarkdownMessage({ text }: { text: string }) {
  return (
    <div className="space-y-2">
      {parseMarkdownMessage(text).map((block, index) => {
        if (block.type === "list") {
          return (
            <ul key={index} className="ml-4 list-disc space-y-1">
              {block.items.map((item, itemIndex) => (
                <li key={itemIndex}>{renderInlineMarkdown(item)}</li>
              ))}
            </ul>
          );
        }
        return <p key={index}>{renderInlineMarkdown(block.text)}</p>;
      })}
    </div>
  );
}

function SplitikDraftCard({
  draft,
  onConfirm,
  onEdit
}: {
  draft: SplitikDraft;
  onConfirm: (draftId: string) => void;
  onEdit: (value: string) => void;
}) {
  const title = splitikDraftTitle(draft);
  const details = splitikDraftDetails(draft);
  const isCommitted = draft.status === "committed";
  return (
    <Card data-testid="splitik-draft-card" className="overflow-hidden rounded-2xl border-[#d8dfeb] bg-white shadow-sm">
      <CardHeader className="grid gap-2 p-3 pb-2">
        <div className="flex items-start justify-between gap-3">
          <div className="flex min-w-0 items-center gap-2">
            <span className="grid h-10 w-10 shrink-0 place-items-center rounded-xl bg-[#eef1f7] text-[#1f3d8f]">
              {draft.type === "create_receipt" ? <ReceiptText className="h-5 w-5" /> : <CalendarCheck className="h-5 w-5" />}
            </span>
            <div className="min-w-0">
              <CardTitle className="truncate text-sm font-black text-slate-950">{title}</CardTitle>
              <p className="text-xs font-bold text-slate-500">{splitikDraftKind(draft)}</p>
            </div>
          </div>
          <Badge className={cn("rounded-full px-2.5 py-1 text-[10px] font-black", isCommitted ? "bg-emerald-100 text-emerald-700" : "bg-[#d2daec] text-[#1f3d8f]")}>
            {isCommitted ? "Подтвержден" : "Черновик"}
          </Badge>
        </div>
      </CardHeader>
      <CardContent className="grid gap-3 p-3 pt-0">
        <div className="grid gap-1.5 rounded-xl bg-[#f5f7fb] p-3">
          {details.map(([label, value]) => (
            <div key={label} className="flex items-start justify-between gap-3 text-xs">
              <span className="font-bold text-slate-500">{label}</span>
              <span className="max-w-[62%] text-right font-black text-slate-900">{value}</span>
            </div>
          ))}
        </div>
        {draft.questions?.length ? (
          <div className="rounded-xl border border-amber-200 bg-amber-50 px-3 py-2 text-xs font-bold text-amber-800">
            Нужно уточнить: {draft.questions.map((question) => question.text).join(" · ")}
          </div>
        ) : null}
        <div className="grid grid-cols-3 gap-2">
          <Button type="button" variant="ghost" className="h-10 rounded-xl bg-[#eef1f7] px-2 text-xs font-black text-[#1f3d8f]" onClick={() => onEdit(`Покажи подробнее черновик ${draft.id}`)}>
            <ExternalLink className="mr-1 h-4 w-4" />
            Открыть
          </Button>
          <Button type="button" variant="ghost" className="h-10 rounded-xl bg-[#eef1f7] px-2 text-xs font-black text-[#1f3d8f]" onClick={() => onEdit(`Измени черновик ${draft.id}: `)}>
            <PencilLine className="mr-1 h-4 w-4" />
            Изменить
          </Button>
          <Button data-testid="splitik-draft-confirm" type="button" disabled={isCommitted} className="h-10 rounded-xl bg-[#1f3d8f] px-2 text-xs font-black text-white hover:bg-[#1f3d8f]/90 disabled:bg-slate-300" onClick={() => onConfirm(draft.id)}>
            <Check className="mr-1 h-4 w-4" />
            OK
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}

function splitikDraftKind(draft: SplitikDraft) {
  if (draft.type === "create_event") return "Черновик события";
  if (draft.type === "create_receipt") return "Черновик чека";
  return "Черновик";
}

function splitikDraftTitle(draft: SplitikDraft) {
  const payload = draft.payload;
  if (draft.type === "create_event") return stringValue(payload.name) || "Новое событие";
  if (draft.type === "create_receipt") return stringValue(payload.title) || "Новый чек";
  return "Черновик";
}

function splitikDraftDetails(draft: SplitikDraft): Array<[string, string]> {
  const payload = draft.payload;
  if (draft.type === "create_event") {
    return [
      ["Название", stringValue(payload.name) || "Без названия"],
      ["Статус", draft.status === "committed" ? "подтвержден" : "ожидает подтверждения"]
    ];
  }
  if (draft.type === "create_receipt") {
    const items = Array.isArray(payload.items) ? payload.items : [];
    return [
      ["Сумма", money(numberValue(payload.total_amount_kopecks))],
      ["Плательщик", shortId(stringValue(payload.payer_id))],
      ["Позиции", items.length ? `${items.length}` : "не указаны"]
    ];
  }
  return [["Статус", draft.status]];
}

function stringValue(value: unknown) {
  return typeof value === "string" ? value : "";
}

function numberValue(value: unknown) {
  return typeof value === "number" && Number.isFinite(value) ? value : 0;
}

function shortId(value: string) {
  return value ? `${value.slice(0, 8)}...` : "не указан";
}

function parseMarkdownMessage(text: string): MarkdownBlock[] {
  const blocks: MarkdownBlock[] = [];
  let paragraph: string[] = [];
  let listItems: string[] = [];

  const flushParagraph = () => {
    if (!paragraph.length) return;
    blocks.push({ type: "paragraph", text: paragraph.join(" ") });
    paragraph = [];
  };
  const flushList = () => {
    if (!listItems.length) return;
    blocks.push({ type: "list", items: listItems });
    listItems = [];
  };

  for (const rawLine of text.split(/\r?\n/)) {
    const line = rawLine.trim();
    if (!line) {
      flushParagraph();
      flushList();
      continue;
    }
    if (line.startsWith("- ")) {
      flushParagraph();
      listItems.push(line.slice(2).trim());
      continue;
    }
    flushList();
    paragraph.push(line);
  }

  flushParagraph();
  flushList();
  return blocks.length ? blocks : [{ type: "paragraph", text }];
}

function renderInlineMarkdown(text: string) {
  const parts = text.split(/(\*\*[^*]+\*\*)/g);
  return parts.map((part, index) => {
    if (part.startsWith("**") && part.endsWith("**")) {
      return <strong key={index}>{part.slice(2, -2)}</strong>;
    }
    return part;
  });
}

function SegmentedControl({
  name,
  items,
  active,
  onChange
}: {
  name: string;
  items: Array<[string, string]>;
  active: string;
  onChange: (value: string) => void;
}) {
  return (
    <div data-testid={name} className="grid grid-cols-[repeat(var(--items),minmax(0,1fr))] gap-1 rounded-2xl bg-white p-1" style={{ "--items": items.length } as CSSProperties}>
      {items.map(([id, label]) => (
        <Button
          key={id}
          type="button"
          onClick={() => onChange(id)}
          variant="ghost"
          className={cn("min-h-10 rounded-xl px-2 text-xs font-black text-slate-500 hover:bg-[#f5f5f7]", active === id && "bg-[#f5f5f7] text-[#111111] shadow-sm")}
        >
          {label}
        </Button>
      ))}
    </div>
  );
}

function ContentPanel({ title, action, children }: { title: string; action?: string; children: React.ReactNode }) {
  return (
    <Card data-slot="content-panel" className="rounded-2xl border-0 bg-white p-0 shadow-sm">
      <CardHeader className="flex-row items-center justify-between gap-3 p-3 pb-2">
        <CardTitle className="text-sm font-black">{title}</CardTitle>
        {action ? <Badge className="rounded-full bg-[#d2daec] px-3 py-1 text-[10px] font-black text-[#1f3d8f]">{action}</Badge> : null}
      </CardHeader>
      <CardContent className="grid gap-2 p-3 pt-0">{children}</CardContent>
    </Card>
  );
}

function Avatar({ children }: { children: React.ReactNode }) {
  return <span className="grid h-9 w-9 place-items-center rounded-full bg-[#c6cbdc] text-sm font-black text-[#1f3d8f]">{children}</span>;
}

function viewTitle(view: View) {
  const titles: Record<View, string> = {
    home: "Главная",
    events: "События",
    people: "Друзья",
    notifications: "Уведомления",
    profile: "Профиль",
    splitik: "Сплитик"
  };
  return titles[view];
}

function splitikErrorMessage(error: unknown) {
  if (error instanceof ApiError) {
    if (error.status === 401) return "Сессия истекла. Войдите через Яндекс еще раз.";
    return "Сплитик сейчас не смог ответить. Мы уже получили отчет, попробуйте еще раз чуть позже.";
  }
  return "Не смог достучаться до Сплитика. Проверьте сеть и попробуйте еще раз.";
}

function parseHashView(hash: string): View | null {
  const value = hash.replace("#", "");
  return validViews.includes(value as View) ? (value as View) : null;
}

function viewToReportScreen(view: View): ClientReportScreen {
  return view;
}

function pageItems<T>(page: { items?: T[] } | null | undefined) {
  return Array.isArray(page?.items) ? page.items : [];
}

function isUuid(value: string | null): value is string {
  return Boolean(value?.match(/^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i));
}

function eventInviteDisplayCode(rawCode: string) {
  let numericCode = 0;
  for (const character of rawCode) {
    numericCode = (numericCode * 31 + character.charCodeAt(0)) % 1000000;
  }
  return String(numericCode).padStart(6, "0");
}

function friendshipsToOptions(friendships: Friendship[]): FriendOption[] {
  return friendships
    .map((friendship) => friendship.peer)
    .filter((peer): peer is UserProfile => Boolean(peer?.id && peer.name))
    .map((peer) => ({
      id: peer.id,
      initials: initialsFor(peer.name),
      name: peer.name,
      subtitle: "участник",
      amount: 0,
      tone: "text-slate-500"
    }));
}

function normalizeFriendCode(code: string) {
  return code.trim().replace(/^@+/, "").replace(/\s+/g, "_").toLowerCase();
}

function defaultFriendHandle(user: UserProfile) {
  return `split_${user.id.replace(/-/g, "").slice(0, 8)}`;
}

function friendCodeForUser(user: UserProfile) {
  return normalizeFriendCode(user.public_handle || defaultFriendHandle(user));
}

async function copyText(value: string) {
  if (navigator.clipboard?.writeText) {
    await navigator.clipboard.writeText(value);
    return true;
  }
  return false;
}

function upsertFriendship(friendships: Friendship[], friendship: Friendship) {
  return [friendship, ...friendships.filter((item) => item.id !== friendship.id)];
}

function eventWithAddedParticipants(event: EventSummary, userIds: string[]): EventSummary {
  const existing = event.participants ?? [];
  const existingUserIds = new Set(existing.map((participant) => participant.user_id));
  const added = userIds
    .filter((userId) => !existingUserIds.has(userId))
    .map((userId) => ({ user_id: userId, role: "member", status: "active" }));
  const participants = [...existing, ...added];
  return { ...event, participants, participants_count: participants.length };
}

function eventParticipants(event: EventSummary, friendOptions: FriendOption[]): FriendOption[] {
  const byUserId = new Map(friendOptions.map((friend) => [friend.id, friend]));
  const participants = event.participants ?? [];
  if (!participants.length) {
    return fallbackFriends.slice(0, Math.max(1, Math.min(event.participants_count ?? 1, fallbackFriends.length)));
  }
  return participants.map((participant, index) => {
    const friend = byUserId.get(participant.user_id);
    if (friend) return { ...friend, subtitle: participant.role === "creator" ? "создатель" : "участник" };
    const name = participant.role === "creator" ? "Вы" : `Участник ${index + 1}`;
    return {
      id: participant.user_id,
      initials: initialsFor(name),
      name,
      subtitle: participant.role === "creator" ? "создатель" : "участник",
      amount: 0,
      tone: "text-slate-500"
    };
  });
}

function initialsFor(name: string) {
  return name.trim().slice(0, 1).toUpperCase() || "•";
}

function normalizeEvent(event: EventSummary): EventSummary {
  return {
    ...event,
    title: event.title || event.name || "Событие",
    status: event.status || (event.is_closed ? "closed" : "active"),
    participants_count: event.participants_count ?? event.participants?.length ?? 0
  };
}

function eventTitle(event: EventSummary) {
  return event.title || event.name || "Событие";
}

function permissionLabel(status: PermissionStatus) {
  const labels: Record<PermissionStatus, string> = {
    pending: "запросить",
    granted: "разрешено",
    unsupported: "недоступно",
    denied: "запрещено",
    skipped: "позже"
  };
  return labels[status];
}

function isIosDevice() {
  if (typeof navigator === "undefined") return false;
  return /iphone|ipad|ipod/i.test(navigator.userAgent);
}

function isStandalonePwa() {
  if (typeof window === "undefined") return false;
  const navigatorWithStandalone = navigator as Navigator & { standalone?: boolean };
  return window.matchMedia?.("(display-mode: standalone)").matches || navigatorWithStandalone.standalone === true;
}

function permissionErrorMessage(error: unknown, fallback: string) {
  if (error instanceof DOMException && error.name === "NotAllowedError") {
    return `${fallback} Проверьте системные настройки Safari/SplitApp.`;
  }
  if (error instanceof Error && error.message) {
    return `${fallback} ${error.message}`;
  }
  return fallback;
}

function urlBase64ToUint8Array(value: string) {
  const padding = "=".repeat((4 - (value.length % 4)) % 4);
  const base64 = `${value}${padding}`.replace(/-/g, "+").replace(/_/g, "/");
  const rawData = window.atob(base64);
  const output = new Uint8Array(rawData.length);

  for (let index = 0; index < rawData.length; index += 1) {
    output[index] = rawData.charCodeAt(index);
  }

  return output;
}
