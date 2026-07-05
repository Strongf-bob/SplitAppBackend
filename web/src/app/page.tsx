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
  Share2,
  Smartphone,
  User,
  Users
} from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  api,
  clearTokens,
  handleYandexOAuthCallback,
  HomeSummary,
  loadTokens,
  money,
  SplitAppTokens,
  startYandexLogin
} from "@/lib/splitapp-api";
import { cn } from "@/lib/utils";

type View = "home" | "events" | "people" | "notifications" | "profile" | "splitik";
type EventTab = "invites" | "active" | "closed";
type NotificationTab = "incoming" | "read";
type PermissionId = "contacts" | "camera" | "gallery" | "notifications";
type PermissionStatus = "pending" | "granted" | "unsupported" | "denied" | "skipped";
type PermissionState = Record<PermissionId, { status: PermissionStatus; detail: string }>;
type ChatMessage = { id: string; from: "user" | "splitik"; text: string };

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

const fallbackEvents = [
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
  const [isOnline, setIsOnline] = useState(true);
  const [message, setMessage] = useState("Готов к работе");
  const [installPrompt, setInstallPrompt] = useState<Event | null>(null);
  const [isIos, setIsIos] = useState(false);
  const [isStandalone, setIsStandalone] = useState(false);
  const [permissionState, setPermissionState] = useState<PermissionState>(initialPermissionState);
  const [chatMessages, setChatMessages] = useState<ChatMessage[]>([
    { id: "hello", from: "splitik", text: "Привет! Я Сплитик, чем могу помочь?" },
    { id: "hint", from: "splitik", text: "Могу разобрать чек, спросить кто что ел или напомнить кому вернуть долг." }
  ]);
  const [chatDraft, setChatDraft] = useState("");
  const galleryInputRef = useRef<HTMLInputElement | null>(null);

  useEffect(() => {
    setTokens(loadTokens());
    setIsOnline(navigator.onLine);
    setIsIos(isIosDevice());
    setIsStandalone(isStandalonePwa());

    const hashView = parseHashView(window.location.hash);
    if (hashView) setView(hashView);

    const onOnline = () => setIsOnline(true);
    const onOffline = () => setIsOnline(false);
    const onHashChange = () => {
      const nextView = parseHashView(window.location.hash);
      if (nextView) setView(nextView);
    };
    const onBeforeInstallPrompt = (event: Event) => {
      event.preventDefault();
      setInstallPrompt(event);
    };

    window.addEventListener("online", onOnline);
    window.addEventListener("offline", onOffline);
    window.addEventListener("hashchange", onHashChange);
    window.addEventListener("beforeinstallprompt", onBeforeInstallPrompt);
    window.matchMedia?.("(display-mode: standalone)").addEventListener?.("change", () => {
      setIsStandalone(isStandalonePwa());
    });

    if ("serviceWorker" in navigator) {
      navigator.serviceWorker.register("/sw.js").catch(() => undefined);
    }

    handleYandexOAuthCallback()
      .then((nextTokens) => {
        if (nextTokens) {
          setTokens(nextTokens);
          setMessage("Вы вошли через Яндекс.");
        }
      })
      .catch((error) => setMessage(error instanceof Error ? error.message : "Не удалось войти."));

    return () => {
      window.removeEventListener("online", onOnline);
      window.removeEventListener("offline", onOffline);
      window.removeEventListener("hashchange", onHashChange);
      window.removeEventListener("beforeinstallprompt", onBeforeInstallPrompt);
    };
  }, []);

  useEffect(() => {
    if (!tokens) return;
    api<HomeSummary>("/api/home/summary", tokens)
      .then(setSummary)
      .catch(() => {
        setSummary({ events: fallbackEvents });
        setMessage("Backend недоступен, показан демо-срез PWA.");
      });
  }, [tokens]);

  const events = useMemo(() => (summary?.events?.length ? summary.events : fallbackEvents), [summary]);
  const owedToMe = summary?.totals?.owed_to_me_kopecks ?? 720000;
  const iOwe = summary?.totals?.i_owe_kopecks ?? 295000;

  const navigate = (nextView: View) => {
    setPreviousView(view);
    setView(nextView);
    window.history.replaceState(null, "", `#${nextView}`);
  };

  const goBack = () => navigate(previousView === view ? "home" : previousView);
  const goHome = () => navigate("home");

  const runInstall = async () => {
    if (!installPrompt) {
      setMessage("На iPhone нажмите Share -> Add to Home Screen, затем откройте SplitApp с ярлыка.");
      return;
    }
    const prompt = installPrompt as Event & { prompt?: () => Promise<void>; userChoice?: Promise<unknown> };
    await prompt.prompt?.();
    await prompt.userChoice;
    setInstallPrompt(null);
  };

  const enableDemo = () => {
    const demoTokens = { access_token: "demo-pwa-token" };
    setTokens(demoTokens);
    setSummary({ events: fallbackEvents });
    setMessage("Открыт кликабельный демо-режим PWA.");
  };

  const logout = () => {
    clearTokens();
    setTokens(null);
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
        updatePermission("gallery", "skipped", permissionErrorMessage(error, "Выбор фото отменен."));
        return;
      }
    }

    galleryInputRef.current?.click();
  };

  const requestNotificationPermission = async () => {
    if (!("Notification" in window)) {
      updatePermission("notifications", "unsupported", "Этот браузер не поддерживает web-уведомления.");
      return;
    }
    if (isIosDevice() && !isStandalonePwa()) {
      updatePermission("notifications", "skipped", "На iPhone сначала добавьте SplitApp: Share -> Add to Home Screen, потом откройте ярлык.");
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
      updatePermission("contacts", "unsupported", "iPhone Safari обычно не дает Web Contacts API. Используем ручное добавление/инвайт.");
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

  const sendSplitikMessage = (event?: FormEvent<HTMLFormElement>) => {
    event?.preventDefault();
    const text = chatDraft.trim();
    if (!text) return;
    const userMessage = { id: `u-${Date.now()}`, from: "user" as const, text };
    const answer = splitikAnswer(text);
    setChatMessages((items) => [...items, userMessage, { id: `s-${Date.now()}`, from: "splitik", text: answer }]);
    setChatDraft("");
    setMessage("Сплитик ответил в чате.");
  };

  return (
    <main className="min-h-dvh bg-[#1e1e1e] text-slate-950">
      <section className="mx-auto grid min-h-dvh w-full max-w-7xl place-items-center px-3 py-4 sm:px-6">
        <div className="grid w-full gap-4 lg:grid-cols-[420px_minmax(0,1fr)] lg:items-center">
          <aside className="hidden text-white lg:block">
            <p className="text-sm uppercase tracking-[0.36em] text-white/50">SplitApp PWA</p>
            <h1 className="mt-4 text-5xl font-bold leading-tight">Дизайн из SVG, собранный в рабочее приложение</h1>
            <p className="mt-4 max-w-sm text-base leading-7 text-white/64">
              Синий мобильный shell, карточки событий, друзья, входящие, профиль и доработанный Сплитик.
            </p>
          </aside>

          <div className="mx-auto w-full max-w-[430px]">
            <PhoneShell
              view={tokens ? view : "home"}
              title={tokens ? viewTitle(view) : "Split."}
              isOnline={isOnline}
              onBack={goBack}
              onHome={goHome}
              showBack={Boolean(tokens && view !== "home")}
              onNotifications={() => navigate("notifications")}
              onLogout={logout}
              loggedIn={Boolean(tokens)}
            >
              {!tokens ? (
                <AuthScreen
                  isIos={isIos}
                  isStandalone={isStandalone}
                  onLogin={startYandexLogin}
                  onDemo={enableDemo}
                  onInstall={runInstall}
                  onPermission={requestPermission}
                  permissionState={permissionState}
                  galleryInputRef={galleryInputRef}
                  onGalleryPicked={(picked) =>
                    updatePermission("gallery", picked ? "granted" : "skipped", picked ? "Фото выбрано из галереи." : "Выбор фото отменен.")
                  }
                />
              ) : (
                <WorkspaceScreen
                  view={view}
                  events={events}
                  eventTab={eventTab}
                  onEventTab={setEventTab}
                  notificationTab={notificationTab}
                  onNotificationTab={setNotificationTab}
                  owedToMe={owedToMe}
                  iOwe={iOwe}
                  chatMessages={chatMessages}
                  chatDraft={chatDraft}
                  onChatDraft={setChatDraft}
                  onSendChat={sendSplitikMessage}
                  onNavigate={navigate}
                  onMessage={setMessage}
                />
              )}
            </PhoneShell>
          </div>
        </div>
      </section>

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
    </main>
  );
}

function PhoneShell({
  view,
  title,
  isOnline,
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
  isOnline: boolean;
  loggedIn: boolean;
  showBack: boolean;
  children: React.ReactNode;
  onBack: () => void;
  onHome: () => void;
  onNotifications: () => void;
  onLogout: () => void;
}) {
  return (
    <div className="rounded-[38px] bg-[#101010] p-2 shadow-[0_26px_80px_rgba(0,0,0,0.7)]">
      <div className="relative min-h-[812px] overflow-hidden rounded-[30px] bg-[#1f3d8f]">
        <div className="absolute left-1/2 top-2 z-30 h-7 w-24 -translate-x-1/2 rounded-full bg-black" />
        <header className="relative z-20 flex h-[92px] items-end justify-between px-4 pb-4 text-white">
          <div className="absolute left-4 top-4 text-[11px] font-bold">9:41</div>
          <div className="absolute right-4 top-4 text-[11px] font-bold text-white/80">◢ Wi-Fi</div>
          <div className="flex items-center gap-2">
            {showBack ? (
              <button
                type="button"
                aria-label="Назад"
                onClick={onBack}
                className="grid h-10 w-10 place-items-center rounded-full bg-white/14 text-white"
              >
                <ArrowLeft className="h-5 w-5" />
              </button>
            ) : null}
            <h2 className="text-3xl font-black tracking-normal">{title}</h2>
          </div>
          {loggedIn ? (
            <div className="flex gap-2">
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
          ) : (
            <Badge className="bg-white/16 text-white">{isOnline ? "online" : "offline"}</Badge>
          )}
        </header>

        <section className={cn("relative z-10 min-h-[720px]", loggedIn && "pb-[92px]")}>{children}</section>

        {loggedIn ? (
          <nav className="absolute inset-x-3 bottom-5 z-30 rounded-[24px] bg-[#6f7888]/96 p-1.5 shadow-[0_14px_40px_rgba(15,23,42,0.25)]">
            <div className="grid grid-cols-5 gap-1">
              {navItems.map((item) => (
                <BottomNavButton key={item.id} item={item} active={view === item.id} />
              ))}
            </div>
          </nav>
        ) : null}
      </div>
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

function AuthScreen({
  isIos,
  isStandalone,
  onLogin,
  onDemo,
  onInstall,
  onPermission,
  permissionState,
  galleryInputRef,
  onGalleryPicked
}: {
  isIos: boolean;
  isStandalone: boolean;
  onLogin: () => void;
  onDemo: () => void;
  onInstall: () => void;
  onPermission: (id: PermissionId) => void;
  permissionState: PermissionState;
  galleryInputRef: React.RefObject<HTMLInputElement | null>;
  onGalleryPicked: (picked: boolean) => void;
}) {
  return (
    <div className="grid min-h-[720px] content-between px-5 pb-7 pt-16 text-white">
      <div className="grid gap-4">
        <div>
          <h1 className="text-6xl font-black leading-none tracking-normal">Split.</h1>
          <p className="mt-3 text-sm font-bold text-[#d2daec]">Делите счета поровну</p>
        </div>
        <div className="rounded-[22px] bg-white p-4 text-[#111111] shadow-[0_18px_40px_rgba(0,0,0,0.18)]">
          <div className="rounded-2xl bg-[#111111] p-4 text-white">
            <p className="text-xs font-bold text-white/58">Сегодня</p>
            <p className="mt-1 text-2xl font-black">4 250 ₽</p>
            <div className="mt-3 grid grid-cols-2 gap-2 text-xs font-bold">
              <span className="rounded-xl bg-emerald-400/18 px-3 py-2 text-emerald-200">вам должны</span>
              <span className="rounded-xl bg-rose-400/18 px-3 py-2 text-rose-200">вы должны</span>
            </div>
          </div>
          <div className="mt-3 grid gap-2">
            <div className="flex items-center justify-between rounded-xl bg-[#f5f5f7] px-3 py-2 text-xs font-black">
              <span>Поездка в Карпаты</span>
              <span>38 400 ₽</span>
            </div>
            <div className="flex items-center justify-between rounded-xl bg-[#f5f5f7] px-3 py-2 text-xs font-black">
              <span>Сплитик готовит чек</span>
              <span className="text-[#1f3d8f]">черновик</span>
            </div>
          </div>
        </div>
        {isIos && !isStandalone ? (
          <div className="rounded-2xl bg-white/12 p-3 text-xs leading-5 text-white">
            <Share2 className="mb-2 h-4 w-4" />
            iPhone: Share {"->"} Add to Home Screen. После запуска с ярлыка будут доступны PWA-разрешения.
          </div>
        ) : null}
      </div>

      <div className="grid gap-3">
        <button type="button" onClick={onDemo} className="min-h-14 rounded-2xl bg-white px-4 text-sm font-black text-[#111111]">
          Покрутить приложение
        </button>
        <button
          type="button"
          onClick={onLogin}
          className="min-h-12 rounded-2xl border border-white/20 bg-white/10 px-4 text-sm font-black text-white"
        >
          Войти через Яндекс
        </button>
        <p className="text-center text-[11px] font-semibold leading-4 text-white/62">
          Яндекс доступен только на зарегистрированном домене. В локальном preview сначала смотрим приложение.
        </p>
        <div className="grid grid-cols-4 gap-2">
          {permissions.map((item) => {
            const Icon = item.icon;
            const status = permissionState[item.id].status;
            return (
              <button
                key={item.id}
                type="button"
                onClick={() => onPermission(item.id)}
                aria-label={item.label}
                className="grid min-h-[54px] place-items-center rounded-2xl bg-white/12 text-white"
                title={status === "pending" ? item.detail : permissionState[item.id].detail}
              >
                <Icon className="h-5 w-5" />
              </button>
            );
          })}
        </div>
        <div>
          <Button className="w-full" variant="secondary" onClick={onInstall}>
            <Smartphone className="h-4 w-4" />
            Установить SplitApp
          </Button>
        </div>
      </div>

      <input
        ref={galleryInputRef}
        type="file"
        accept="image/*"
        className="hidden"
        onChange={(event) => {
          onGalleryPicked(Boolean(event.currentTarget.files?.length));
          event.currentTarget.value = "";
        }}
      />
    </div>
  );
}

function WorkspaceScreen({
  view,
  events,
  eventTab,
  onEventTab,
  notificationTab,
  onNotificationTab,
  owedToMe,
  iOwe,
  chatMessages,
  chatDraft,
  onChatDraft,
  onSendChat,
  onNavigate,
  onMessage
}: {
  view: View;
  events: HomeSummary["events"];
  eventTab: EventTab;
  onEventTab: (tab: EventTab) => void;
  notificationTab: NotificationTab;
  onNotificationTab: (tab: NotificationTab) => void;
  owedToMe: number;
  iOwe: number;
  chatMessages: ChatMessage[];
  chatDraft: string;
  onChatDraft: (value: string) => void;
  onSendChat: (event?: FormEvent<HTMLFormElement>) => void;
  onNavigate: (view: View) => void;
  onMessage: (message: string) => void;
}) {
  return (
    <AnimatePresence mode="wait">
      <motion.div
        key={view}
        className="min-h-[720px] rounded-t-[24px] bg-[#f5f5f7] px-3 pb-5 pt-3"
        initial={{ opacity: 0, y: 16 }}
        animate={{ opacity: 1, y: 0 }}
        exit={{ opacity: 0, y: -10 }}
        transition={{ duration: 0.2 }}
      >
        {view === "home" ? (
          <HomeScreen events={events} owedToMe={owedToMe} iOwe={iOwe} onNavigate={onNavigate} onMessage={onMessage} />
        ) : null}
        {view === "people" ? <PeopleScreen /> : null}
        {view === "profile" ? <ProfileScreen owedToMe={owedToMe} iOwe={iOwe} /> : null}
        {view === "events" ? <EventsScreen events={events} activeTab={eventTab} onTab={onEventTab} /> : null}
        {view === "notifications" ? (
          <NotificationsScreen activeTab={notificationTab} onTab={onNotificationTab} />
        ) : null}
        {view === "splitik" ? (
          <SplitikScreen messages={chatMessages} draft={chatDraft} onDraft={onChatDraft} onSend={onSendChat} />
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
  onMessage
}: {
  events: HomeSummary["events"];
  owedToMe: number;
  iOwe: number;
  onNavigate: (view: View) => void;
  onMessage: (message: string) => void;
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
          <span className="font-black">{mainEvent.title}</span>
          <span className="flex items-center justify-between text-xs text-white/60">
            <span>{mainEvent.participants_count ?? 0} участника</span>
            <span>{money(mainEvent.total_kopecks ?? 0)}</span>
          </span>
        </button>
        <div className="mt-4 grid grid-cols-3 gap-3">
          <QuickAction icon={CheckCircle2} label="Синхрониз." onClick={() => onMessage("Данные синхронизированы.")} />
          <QuickAction icon={Plus} label="Добавить" onClick={() => onNavigate("events")} />
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
  return (
    <div className="grid gap-4">
      <div className="flex justify-end">
        <button type="button" aria-label="Поиск друзей" className="grid h-12 w-12 place-items-center rounded-full bg-[#d2daec] text-[#1f3d8f]">
          <Search className="h-5 w-5" />
        </button>
      </div>
      <ContentPanel title="Друзья">
        {friends.map((friend) => (
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
      </ContentPanel>
    </div>
  );
}

function EventsScreen({
  events,
  activeTab,
  onTab
}: {
  events: HomeSummary["events"];
  activeTab: EventTab;
  onTab: (tab: EventTab) => void;
}) {
  const filtered = (events ?? fallbackEvents).filter((event) => {
    if (activeTab === "active") return event.status !== "closed" && event.status !== "invite";
    if (activeTab === "closed") return event.status === "closed";
    return event.status === "invite";
  });
  const visible = filtered.length ? filtered : activeTab === "closed" ? [fallbackEvents[2]] : [fallbackEvents[1]];

  return (
    <div className="grid gap-4">
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
        <button key={event.id} type="button" className="grid min-h-[98px] gap-3 rounded-xl bg-white p-4 text-left shadow-sm">
          <span className="text-lg font-black">{event.title}</span>
          <span className="text-xs text-slate-500">
            {event.participants_count ?? 0} участника · {money(event.total_kopecks ?? 0)}
          </span>
        </button>
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

function ProfileScreen({ owedToMe, iOwe }: { owedToMe: number; iOwe: number }) {
  return (
    <div className="grid gap-4">
      <div className="-mx-3 -mt-3 grid justify-items-center rounded-b-[24px] bg-[#1f3d8f] px-5 pb-8 pt-4 text-white">
        <div className="grid h-28 w-28 place-items-center rounded-full bg-[#bbb2d5] text-6xl font-black text-[#654da1]">A</div>
      </div>
      <ContentPanel title="Анна">
        <ProfileRow label="Мне должны" value={money(owedToMe)} tone="text-emerald-600" />
        <ProfileRow label="Я должен" value={money(iOwe)} tone="text-red-600" />
        <ProfileRow label="Активных событий" value="3" tone="text-[#1f3d8f]" />
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
  onSend
}: {
  messages: ChatMessage[];
  draft: string;
  onDraft: (value: string) => void;
  onSend: (event?: FormEvent<HTMLFormElement>) => void;
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
        <button type="submit" aria-label="Отправить Сплитику" className="grid h-12 w-12 place-items-center rounded-xl bg-[#1f3d8f] text-white">
          <Send className="h-5 w-5" />
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

function splitikAnswer(text: string) {
  const normalized = text.toLowerCase();
  if (normalized.includes("чек") || normalized.includes("receipt")) {
    return "Загружайте фото чека: я соберу позиции, спрошу кто что ел и покажу черновик перед подтверждением.";
  }
  if (normalized.includes("долг") || normalized.includes("плат")) {
    return "По долгам сейчас вижу баланс: зеленое вам должны, красное должны вы. Нажмите Входящие для подтверждений.";
  }
  return "Понял. Могу открыть событие, разобрать чек или подготовить сообщение участникам.";
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
