"use client";

import { CSSProperties, FormEvent, useEffect, useMemo, useRef, useState } from "react";
import { AnimatePresence, motion } from "framer-motion";
import {
  ArrowLeft,
  Bell,
  Bot,
  CalendarCheck,
  Camera,
  CheckCircle2,
  Home,
  Image as ImageIcon,
  Inbox,
  LogOut,
  Plus,
  Search,
  Send,
  User,
  Users
} from "lucide-react";

import { Badge } from "@/components/ui/badge";
import {
  api,
  clearTokens,
  EventPage,
  EventSummary,
  handleYandexOAuthCallback,
  HomeSummary,
  loadTokens,
  money,
  ReceiptPage,
  ReceiptSummary,
  SplitikMessageResponse,
  SplitAppTokens,
  startYandexLogin,
  UserProfile
} from "@/lib/splitapp-api";
import { cn } from "@/lib/utils";

type View = "home" | "events" | "people" | "notifications" | "profile" | "splitik";
type EventTab = "invites" | "active" | "closed";
type NotificationTab = "incoming" | "read";
type PermissionId = "contacts" | "camera" | "gallery" | "notifications";
type PermissionStatus = "pending" | "granted" | "unsupported" | "denied" | "skipped";
type PermissionState = Record<PermissionId, { status: PermissionStatus; detail: string }>;
type ChatMessage = { id: string; from: "user" | "splitik"; text: string };
type EventReceipts = Record<string, { loading: boolean; items: ReceiptSummary[] }>;

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

const friends = [
  { initials: "А", name: "Алина Табакеева", subtitle: "вы должны", amount: -1480, tone: "text-red-600" },
  { initials: "М", name: "Максим Демин", subtitle: "должен вам", amount: 1488, tone: "text-emerald-600" },
  { initials: "И", name: "Иван Соловьев", subtitle: "ровно", amount: 0, tone: "text-slate-500" }
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
  const [message, setMessage] = useState("");
  const [permissionState, setPermissionState] = useState<PermissionState>(initialPermissionState);
  const [chatMessages, setChatMessages] = useState<ChatMessage[]>([
    { id: "hello", from: "splitik", text: "Привет! Я Сплитик, чем могу помочь?" },
    { id: "hint", from: "splitik", text: "Могу разобрать чек, спросить кто что ел или напомнить кому вернуть долг." }
  ]);
  const [chatDraft, setChatDraft] = useState("");
  const [splitikSessionId, setSplitikSessionId] = useState<string | null>(null);
  const [isSplitikSending, setIsSplitikSending] = useState(false);
  const galleryInputRef = useRef<HTMLInputElement | null>(null);

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
    };
  }, []);

  useEffect(() => {
    if (!tokens) return;
    Promise.all([
      api<HomeSummary>("/api/home/summary", tokens),
      api<EventPage>("/api/events", tokens),
      api<UserProfile>("/api/users/me", tokens)
    ])
      .then(([nextSummary, eventPage, user]) => {
        setSummary(nextSummary);
        setCurrentUser(user);
        setEvents(eventPage.items.length ? eventPage.items.map(normalizeEvent) : fallbackEvents);
      })
      .catch(() => {
        setEvents(fallbackEvents);
        setMessage("Backend недоступен, показан локальный срез PWA.");
      });
  }, [tokens]);

  useEffect(() => {
    if (!message) return;
    const timeout = setTimeout(() => setMessage(""), 3200);
    return () => clearTimeout(timeout);
  }, [message]);

  const owedToMe = summary?.confirmed?.receivable_kopecks ?? 720000;
  const iOwe = summary?.confirmed?.owed_kopecks ?? 295000;

  const navigate = (nextView: View) => {
    setPreviousView(view);
    setView(nextView);
    window.history.replaceState(null, "", `#${nextView}`);
  };

  const goBack = () => navigate(previousView === view ? "home" : previousView);
  const goHome = () => navigate("home");

  const logout = () => {
    clearTokens();
    setTokens(null);
    setCurrentUser(null);
    setSummary(null);
    setMessage("Вы вышли. Локальная сессия очищена.");
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

  const openEvent = async (event: EventSummary) => {
    setSelectedEventId((current) => (current === event.id ? null : event.id));
    if (!tokens || event.status === "invite" || eventReceipts[event.id]) return;
    setEventReceipts((current) => ({ ...current, [event.id]: { loading: true, items: [] } }));
    try {
      const page = await api<ReceiptPage>(`/api/events/${event.id}/receipts`, tokens);
      setEventReceipts((current) => ({ ...current, [event.id]: { loading: false, items: page.items } }));
    } catch {
      setEventReceipts((current) => ({ ...current, [event.id]: { loading: false, items: [] } }));
      setMessage("Не удалось загрузить чеки события.");
    }
  };

  const createEvent = async (event?: FormEvent<HTMLFormElement>) => {
    event?.preventDefault();
    const name = newEventName.trim();
    if (!tokens || !name) return;
    try {
      const created = await api<EventSummary>("/api/events", tokens, {
        method: "POST",
        body: JSON.stringify({ name })
      });
      setEvents((current) => [normalizeEvent(created), ...current.filter((item) => !item.id.startsWith("demo-"))]);
      setNewEventName("");
      setIsCreatingEvent(false);
      setEventTab("active");
      setSelectedEventId(created.id);
      setMessage("Событие создано.");
    } catch {
      setMessage("Не удалось создать событие.");
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
      await api(`/api/invites/${event.token}/${decision}`, tokens, { method: "POST" });
      setEvents((current) => current.filter((item) => item.id !== event.id));
      setSelectedEventId(null);
      setMessage(decision === "accept" ? "Приглашение принято." : "Приглашение отклонено.");
    } catch {
      setMessage("Не удалось обработать приглашение.");
    }
  };

  const sendSplitikMessage = async (event?: FormEvent<HTMLFormElement>) => {
    event?.preventDefault();
    const text = chatDraft.trim();
    if (!text || !tokens || isSplitikSending) return;
    const userMessage = { id: `u-${Date.now()}`, from: "user" as const, text };
    setChatMessages((items) => [...items, userMessage]);
    setChatDraft("");
    setIsSplitikSending(true);
    try {
      const response = await api<SplitikMessageResponse>("/api/splitik/messages", tokens, {
        method: "POST",
        body: JSON.stringify({
          session_id: splitikSessionId,
          mode: selectedEventId ? "event" : "general",
          message: text,
          entry_point: selectedEventId ? { type: "event", event_id: selectedEventId } : undefined
        })
      });
      setSplitikSessionId(response.session_id);
      setChatMessages((items) => [
        ...items,
        { id: response.message_id || `s-${Date.now()}`, from: "splitik", text: response.assistant_message }
      ]);
    } catch {
      setChatMessages((items) => [
        ...items,
        { id: `s-${Date.now()}`, from: "splitik", text: "Не смог достучаться до Сплитика. Попробуйте еще раз." }
      ]);
    } finally {
      setIsSplitikSending(false);
    }
  };

  return (
    <main className="min-h-dvh bg-[#f5f5f7] text-slate-950">
      {!tokens ? (
        <AuthScreen onLogin={startYandexLogin} />
      ) : (
        <PhoneShell
          view={view}
          title={viewTitle(view)}
          onBack={goBack}
          onHome={goHome}
          showBack={view !== "home"}
          onNotifications={() => navigate("notifications")}
          onLogout={logout}
          loggedIn={Boolean(tokens)}
        >
          <WorkspaceScreen
            view={view}
            events={events}
            eventTab={eventTab}
            onEventTab={setEventTab}
            selectedEventId={selectedEventId}
            eventReceipts={eventReceipts}
            onOpenEvent={openEvent}
            onInviteDecision={decideInvite}
            isCreatingEvent={isCreatingEvent}
            newEventName={newEventName}
            onCreateEventOpen={() => {
              setIsCreatingEvent(true);
              setEventTab("active");
              navigate("events");
            }}
            onNewEventName={setNewEventName}
            onCreateEvent={createEvent}
            notificationTab={notificationTab}
            onNotificationTab={setNotificationTab}
            owedToMe={owedToMe}
            iOwe={iOwe}
            currentUser={currentUser}
            permissionState={permissionState}
            onPermission={requestPermission}
            chatMessages={chatMessages}
            chatDraft={chatDraft}
            onChatDraft={setChatDraft}
            onSendChat={sendSplitikMessage}
            isSplitikSending={isSplitikSending}
            onNavigate={navigate}
            onMessage={setMessage}
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

function PhoneShell({
  view,
  title,
  loggedIn,
  showBack,
  children,
  onBack,
  onHome,
  onNotifications,
  onLogout
}: {
  view: View;
  title: string;
  loggedIn: boolean;
  showBack: boolean;
  children: React.ReactNode;
  onBack: () => void;
  onHome: () => void;
  onNotifications: () => void;
  onLogout: () => void;
}) {
  return (
    <div className="min-h-dvh bg-[#f5f5f7]">
      {loggedIn ? (
        <header className="sticky top-0 z-30 flex items-end justify-between gap-2 bg-[#1f3d8f] px-4 pb-4 pt-[max(env(safe-area-inset-top),16px)] text-white">
          <div className="flex min-w-0 items-center gap-2">
            {showBack ? (
              <button
                type="button"
                aria-label="Назад"
                onClick={onBack}
                className="grid h-10 w-10 shrink-0 place-items-center rounded-full bg-white/14 text-white"
              >
                <ArrowLeft className="h-5 w-5" />
              </button>
            ) : null}
            <h2 className="truncate text-3xl font-black tracking-normal">{title}</h2>
          </div>
          <div className="flex shrink-0 gap-2">
            <button
              type="button"
              aria-label="На главную"
              onClick={onHome}
              className="grid h-10 w-10 place-items-center rounded-full bg-white/14 text-white"
            >
              <Home className="h-5 w-5" />
            </button>
            <button
              type="button"
              aria-label="Входящие"
              onClick={onNotifications}
              className="grid h-10 w-10 place-items-center rounded-full bg-white/14 text-white"
            >
              <Inbox className="h-5 w-5" />
            </button>
            <button
              type="button"
              aria-label="Выйти"
              onClick={onLogout}
              className="grid h-10 w-10 place-items-center rounded-full bg-white/14 text-white"
            >
              <LogOut className="h-5 w-5" />
            </button>
          </div>
        </header>
      ) : null}

      <section className={cn("relative z-10", loggedIn && "pb-[calc(120px+env(safe-area-inset-bottom))]")}>{children}</section>

      {loggedIn ? (
        <nav className="fixed inset-x-3 bottom-0 z-30 rounded-t-[24px] bg-[#6f7888]/96 p-1.5 pb-[max(env(safe-area-inset-bottom),12px)] shadow-[0_14px_40px_rgba(15,23,42,0.25)] backdrop-blur">
          <div className="grid grid-cols-5 gap-1">
            {navItems.map((item) => (
              <BottomNavButton key={item.id} item={item} active={view === item.id} />
            ))}
          </div>
        </nav>
      ) : null}
    </div>
  );
}

function BottomNavButton({ item, active }: { item: { id: View; label: string; icon: React.ElementType }; active: boolean }) {
  const Icon = item.icon;
  return (
    <a
      href={`#${item.id}`}
      className={cn(
        "grid min-h-[54px] place-items-center rounded-[18px] px-1 text-[10px] font-bold text-white/86 transition-colors",
        active && "bg-white/22 text-white"
      )}
    >
      <Icon className={cn("h-5 w-5", item.id === "splitik" && "h-8 w-8")} />
      {item.id !== "splitik" ? <span>{item.label}</span> : null}
    </a>
  );
}

function AuthScreen({ onLogin }: { onLogin: () => void }) {
  return (
    <section className="grid min-h-dvh content-between bg-[#1f3d8f] px-6 pb-[max(env(safe-area-inset-bottom),28px)] pt-[max(env(safe-area-inset-top),72px)] text-white">
      <div className="grid content-center gap-4 pt-[18dvh]">
        <div>
          <h1 className="text-7xl font-black leading-none tracking-normal">Split.</h1>
          <p className="mt-3 text-base font-bold text-[#d2daec]">Делите счета поровну</p>
        </div>
      </div>

      <div className="grid gap-3">
        <button
          type="button"
          onClick={onLogin}
          className="min-h-14 rounded-2xl bg-white px-4 text-sm font-black text-[#111111] shadow-[0_18px_40px_rgba(0,0,0,0.18)]"
        >
          Войти через Яндекс
        </button>
        <p className="text-center text-[11px] font-semibold leading-4 text-white/62">Войдите, чтобы открыть события, друзей, чеки и Сплитика.</p>
      </div>

    </section>
  );
}

function WorkspaceScreen({
  view,
  events,
  eventTab,
  onEventTab,
  selectedEventId,
  eventReceipts,
  onOpenEvent,
  onInviteDecision,
  isCreatingEvent,
  newEventName,
  onCreateEventOpen,
  onNewEventName,
  onCreateEvent,
  notificationTab,
  onNotificationTab,
  owedToMe,
  iOwe,
  currentUser,
  permissionState,
  onPermission,
  chatMessages,
  chatDraft,
  onChatDraft,
  onSendChat,
  isSplitikSending,
  onNavigate,
  onMessage
}: {
  view: View;
  events: EventSummary[];
  eventTab: EventTab;
  onEventTab: (tab: EventTab) => void;
  selectedEventId: string | null;
  eventReceipts: EventReceipts;
  onOpenEvent: (event: EventSummary) => void;
  onInviteDecision: (event: EventSummary, decision: "accept" | "decline") => void;
  isCreatingEvent: boolean;
  newEventName: string;
  onCreateEventOpen: () => void;
  onNewEventName: (value: string) => void;
  onCreateEvent: (event?: FormEvent<HTMLFormElement>) => void;
  notificationTab: NotificationTab;
  onNotificationTab: (tab: NotificationTab) => void;
  owedToMe: number;
  iOwe: number;
  currentUser: UserProfile | null;
  permissionState: PermissionState;
  onPermission: (id: PermissionId) => void;
  chatMessages: ChatMessage[];
  chatDraft: string;
  onChatDraft: (value: string) => void;
  onSendChat: (event?: FormEvent<HTMLFormElement>) => void;
  isSplitikSending: boolean;
  onNavigate: (view: View) => void;
  onMessage: (message: string) => void;
}) {
  return (
    <AnimatePresence mode="wait">
      <motion.div
        key={view}
        className="min-h-[calc(100dvh-74px)] rounded-t-[24px] bg-[#f5f5f7] px-3 pb-5 pt-3"
        initial={{ opacity: 0, y: 16 }}
        animate={{ opacity: 1, y: 0 }}
        exit={{ opacity: 0, y: -10 }}
        transition={{ duration: 0.2 }}
      >
        {view === "home" ? (
          <HomeScreen events={events} owedToMe={owedToMe} iOwe={iOwe} onNavigate={onNavigate} onMessage={onMessage} onCreateEventOpen={onCreateEventOpen} />
        ) : null}
        {view === "people" ? <PeopleScreen /> : null}
        {view === "profile" ? (
          <ProfileScreen currentUser={currentUser} owedToMe={owedToMe} iOwe={iOwe} permissionState={permissionState} onPermission={onPermission} />
        ) : null}
        {view === "events" ? (
          <EventsScreen
            events={events}
            activeTab={eventTab}
            onTab={onEventTab}
            selectedEventId={selectedEventId}
            eventReceipts={eventReceipts}
            onOpenEvent={onOpenEvent}
            onInviteDecision={onInviteDecision}
            isCreatingEvent={isCreatingEvent}
            newEventName={newEventName}
            onNewEventName={onNewEventName}
            onCreateEvent={onCreateEvent}
          />
        ) : null}
        {view === "notifications" ? (
          <NotificationsScreen activeTab={notificationTab} onTab={onNotificationTab} />
        ) : null}
        {view === "splitik" ? (
          <SplitikScreen messages={chatMessages} draft={chatDraft} onDraft={onChatDraft} onSend={onSendChat} isSending={isSplitikSending} />
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
  onMessage,
  onCreateEventOpen
}: {
  events: EventSummary[];
  owedToMe: number;
  iOwe: number;
  onNavigate: (view: View) => void;
  onMessage: (message: string) => void;
  onCreateEventOpen: () => void;
}) {
  const mainEvent = events?.[0] ?? fallbackEvents[0];
  return (
    <div className="grid gap-4">
      <section className="-mx-3 -mt-3 rounded-b-[24px] bg-[#1f3d8f] px-5 pb-5 pt-2 text-white">
        <p className="text-center text-4xl font-black">{money((owedToMe || 0) - (iOwe || 0))}</p>
        <div className="mt-2 flex justify-center gap-4 text-xs font-bold">
          <span className="text-emerald-300">■ {money(owedToMe)}</span>
          <span className="text-rose-300">■ {money(iOwe)}</span>
        </div>
        <button
          type="button"
          onClick={() => onNavigate("events")}
          className="mt-4 grid w-full gap-2 rounded-2xl bg-[#111111] p-4 text-left"
        >
          <span className="font-black">{eventTitle(mainEvent)}</span>
          <span className="flex items-center justify-between text-xs text-white/60">
            <span>{mainEvent.participants_count ?? 0} участника</span>
            <span>{money(mainEvent.total_kopecks ?? 0)}</span>
          </span>
        </button>
        <div className="mt-4 grid grid-cols-3 gap-3">
          <QuickAction icon={CheckCircle2} label="Синхрониз." onClick={() => onMessage("Данные синхронизированы.")} />
          <QuickAction icon={Plus} label="Добавить" onClick={onCreateEventOpen} />
          <QuickAction icon={Inbox} label="Входящие" onClick={() => onNavigate("notifications")} />
        </div>
      </section>

      <ContentPanel title="Активность" action="Все">
        {[
          ["Алина добавила Ужин", "Карпаты", "-1488 ₽", "text-red-600"],
          ["Максим вернул долг", "Перевод сегодня", "+650 ₽", "text-emerald-600"],
          ["Иван создал событие", "Новое событие 3 мин", "-", "text-slate-500"]
        ].map(([title, detail, amount, tone]) => (
          <div key={title} className="grid grid-cols-[40px_1fr_auto] items-center gap-2 rounded-xl p-2">
            <Avatar>{title[0]}</Avatar>
            <div>
              <p className="text-sm font-black">{title}</p>
              <p className="text-xs text-slate-500">{detail}</p>
            </div>
            <span className={cn("text-xs font-black", tone)}>{amount}</span>
          </div>
        ))}
      </ContentPanel>
    </div>
  );
}

function QuickAction({ icon: Icon, label, onClick }: { icon: React.ElementType; label: string; onClick: () => void }) {
  return (
    <button type="button" onClick={onClick} className="grid min-h-[74px] place-items-center rounded-2xl text-xs font-bold text-white">
      <span className="grid h-11 w-11 place-items-center rounded-full bg-[#111111]">
        <Icon className="h-5 w-5" />
      </span>
      {label}
    </button>
  );
}

function PeopleScreen() {
  const [friendSearch, setFriendSearch] = useState("");
  const visibleFriends = friends.filter((friend) => friend.name.toLowerCase().includes(friendSearch.trim().toLowerCase()));

  return (
    <div className="grid gap-4">
      <div className="flex items-center gap-2 rounded-2xl bg-white p-2">
        <Search className="ml-2 h-5 w-5 text-[#1f3d8f]" />
        <input
          aria-label="Поиск друзей"
          value={friendSearch}
          onChange={(event) => setFriendSearch(event.target.value)}
          className="min-h-11 flex-1 rounded-xl bg-[#f5f5f7] px-3 text-sm font-semibold outline-none focus-visible:ring-2 focus-visible:ring-[#1f3d8f]"
          placeholder="Найти друга"
        />
      </div>
      <ContentPanel title="Друзья">
        {visibleFriends.map((friend) => (
          <button
            key={friend.name}
            type="button"
            className="grid w-full grid-cols-[40px_1fr_auto] items-center gap-2 rounded-xl border border-[#c6cbdc] bg-white p-2 text-left"
          >
            <Avatar>{friend.initials}</Avatar>
            <div>
              <p className="text-sm font-black">{friend.name}</p>
              <p className="text-xs text-slate-500">{friend.subtitle}</p>
            </div>
            <span className={cn("text-xs font-black", friend.tone)}>{friend.amount > 0 ? "+" : ""}{friend.amount} ₽</span>
          </button>
        ))}
        {!visibleFriends.length ? <p className="py-4 text-center text-sm font-semibold text-slate-500">Ничего не найдено</p> : null}
      </ContentPanel>
    </div>
  );
}

function EventsScreen({
  events,
  activeTab,
  onTab,
  selectedEventId,
  eventReceipts,
  onOpenEvent,
  onInviteDecision,
  isCreatingEvent,
  newEventName,
  onNewEventName,
  onCreateEvent
}: {
  events: EventSummary[];
  activeTab: EventTab;
  onTab: (tab: EventTab) => void;
  selectedEventId: string | null;
  eventReceipts: EventReceipts;
  onOpenEvent: (event: EventSummary) => void;
  onInviteDecision: (event: EventSummary, decision: "accept" | "decline") => void;
  isCreatingEvent: boolean;
  newEventName: string;
  onNewEventName: (value: string) => void;
  onCreateEvent: (event?: FormEvent<HTMLFormElement>) => void;
}) {
  const filtered = (events ?? fallbackEvents).filter((event) => {
    if (activeTab === "active") return !event.is_closed && event.status !== "closed" && event.status !== "invite";
    if (activeTab === "closed") return event.is_closed || event.status === "closed";
    return event.status === "invite";
  });
  const visible = filtered.length ? filtered : activeTab === "closed" ? [fallbackEvents[2]] : [fallbackEvents[1]];

  return (
    <div className="grid gap-4">
      {isCreatingEvent ? (
        <form onSubmit={onCreateEvent} className="grid gap-2 rounded-2xl bg-white p-3">
          <label className="text-xs font-black text-slate-500" htmlFor="event-name">Новое событие</label>
          <input
            id="event-name"
            value={newEventName}
            onChange={(event) => onNewEventName(event.target.value)}
            className="min-h-12 rounded-xl border border-slate-200 px-3 text-sm font-semibold outline-none focus-visible:ring-2 focus-visible:ring-[#1f3d8f]"
            placeholder="Например, ужин или поездка"
          />
          <button type="submit" className="min-h-12 rounded-xl bg-[#1f3d8f] px-4 text-sm font-black text-white">Создать событие</button>
        </form>
      ) : null}
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
      {visible.map((event) => (
        <div key={event.id} className="overflow-hidden rounded-xl bg-white shadow-sm">
          <button type="button" onClick={() => onOpenEvent(event)} className="grid min-h-[98px] w-full gap-3 p-4 text-left">
            <span className="flex items-center justify-between gap-3">
              <span className="text-lg font-black">{eventTitle(event)}</span>
              <span className="text-xl text-slate-400">{selectedEventId === event.id ? "−" : "+"}</span>
            </span>
            <span className="text-xs text-slate-500">
              {event.participants_count ?? event.participants?.length ?? 0} участника · {money(event.total_kopecks ?? 0)}
            </span>
          </button>
          {selectedEventId === event.id ? (
            <div className="grid gap-2 border-t border-slate-100 p-3">
              {activeTab === "invites" ? (
                <>
                  <p className="text-sm font-semibold text-slate-600">Предпросмотр приглашения: участники, сумма и событие будут открыты после принятия.</p>
                  <div className="grid grid-cols-2 gap-2">
                    <button type="button" onClick={() => onInviteDecision(event, "decline")} className="min-h-11 rounded-xl bg-slate-100 text-sm font-black text-slate-700">Отказаться</button>
                    <button type="button" onClick={() => onInviteDecision(event, "accept")} className="min-h-11 rounded-xl bg-[#1f3d8f] text-sm font-black text-white">Согласиться</button>
                  </div>
                </>
              ) : (
                <EventReceiptList receipts={eventReceipts[event.id]} />
              )}
            </div>
          ) : null}
        </div>
      ))}
    </div>
  );
}

function EventReceiptList({ receipts }: { receipts?: { loading: boolean; items: ReceiptSummary[] } }) {
  if (!receipts || receipts.loading) {
    return <p className="py-3 text-sm font-semibold text-slate-500">Загружаем чеки...</p>;
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
    <div className="grid gap-4">
      <SegmentedControl
        name="notification-tab"
        items={[
          ["incoming", "Входящие"],
          ["read", "Прочитанные"]
        ]}
        active={activeTab}
        onChange={(tab) => onTab(tab as NotificationTab)}
      />
      <ContentPanel title={activeTab === "incoming" ? "Новые действия" : "История"}>
        {notifications[activeTab].map((item) => (
          <div key={item.title} className="grid grid-cols-[1fr_auto] gap-2 rounded-xl bg-white p-3">
            <div>
              <p className="text-sm font-black">{item.title}</p>
              <p className="text-xs text-slate-500">{item.detail}</p>
            </div>
            <Badge variant="outline">{item.badge}</Badge>
          </div>
        ))}
      </ContentPanel>
    </div>
  );
}

function ProfileScreen({
  currentUser,
  owedToMe,
  iOwe,
  permissionState,
  onPermission
}: {
  currentUser: UserProfile | null;
  owedToMe: number;
  iOwe: number;
  permissionState: PermissionState;
  onPermission: (id: PermissionId) => void;
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
    <div className="grid gap-4">
      <div className="-mx-3 -mt-3 grid justify-items-center rounded-b-[24px] bg-[#1f3d8f] px-5 pb-8 pt-4 text-white">
        <div className="grid h-28 w-28 place-items-center overflow-hidden rounded-full bg-[#bbb2d5] text-4xl font-black text-[#654da1]">
          {currentUser?.avatar_url ? (
            // eslint-disable-next-line @next/next/no-img-element
            <img src={currentUser.avatar_url} alt="" className="h-full w-full object-cover" />
          ) : (
            initials
          )}
        </div>
      </div>
      <ContentPanel title={profileName}>
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
            <button
              key={item.id}
              type="button"
              onClick={() => onPermission(item.id)}
              className="grid grid-cols-[40px_1fr_auto] items-center gap-2 rounded-xl bg-white p-3 text-left"
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
            </button>
          );
        })}
      </ContentPanel>
    </div>
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
  isSending
}: {
  messages: ChatMessage[];
  draft: string;
  onDraft: (value: string) => void;
  onSend: (event?: FormEvent<HTMLFormElement>) => void;
  isSending: boolean;
}) {
  return (
    <div className="grid min-h-[690px] grid-rows-[1fr_auto] gap-3">
      <div className="grid content-end gap-3 overflow-hidden rounded-2xl bg-white p-3">
        <div className="grid justify-items-center gap-2 pb-3">
          <div className="grid h-24 w-24 place-items-center rounded-3xl border-4 border-[#111111] bg-[#f5f5f7] text-[#111111]">
            <Bot className="h-14 w-14" />
          </div>
        </div>
        {messages.map((item) => (
          <div
            key={item.id}
            className={cn(
              "max-w-[86%] rounded-2xl px-3 py-2 text-sm font-semibold leading-5",
              item.from === "user" ? "ml-auto bg-[#1f3d8f] text-white" : "mr-auto bg-[#eef1f7] text-slate-900"
            )}
          >
            {item.text}
          </div>
        ))}
      </div>
      <form onSubmit={onSend} className="flex gap-2 rounded-2xl bg-white p-2">
        <input
          aria-label="Сообщение Сплитику"
          data-testid="splitik-message-input"
          className="min-h-12 flex-1 rounded-xl border border-slate-200 px-3 text-sm outline-none focus-visible:ring-2 focus-visible:ring-[#1f3d8f]"
          placeholder="Напишите сообщение..."
          value={draft}
          onChange={(event) => onDraft(event.target.value)}
        />
        <button
          type="submit"
          aria-label="Отправить Сплитику"
          disabled={isSending}
          className="grid h-12 w-12 place-items-center rounded-xl bg-[#1f3d8f] text-white disabled:opacity-60"
        >
          {isSending ? <span className="h-4 w-4 animate-spin rounded-full border-2 border-white/40 border-t-white" /> : <Send className="h-5 w-5" />}
        </button>
      </form>
    </div>
  );
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
        <button
          key={id}
          type="button"
          onClick={() => onChange(id)}
          className={cn("min-h-10 rounded-xl px-2 text-xs font-black text-slate-500", active === id && "bg-[#f5f5f7] text-[#111111] shadow-sm")}
        >
          {label}
        </button>
      ))}
    </div>
  );
}

function ContentPanel({ title, action, children }: { title: string; action?: string; children: React.ReactNode }) {
  return (
    <section className="rounded-2xl bg-white p-3 shadow-sm">
      <div className="mb-2 flex items-center justify-between">
        <h3 className="text-sm font-black">{title}</h3>
        {action ? <span className="rounded-full bg-[#d2daec] px-3 py-1 text-[10px] font-black text-[#1f3d8f]">{action}</span> : null}
      </div>
      <div className="grid gap-2">{children}</div>
    </section>
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

function parseHashView(hash: string): View | null {
  const value = hash.replace("#", "");
  return validViews.includes(value as View) ? (value as View) : null;
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
