"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import { AnimatePresence, motion } from "framer-motion";
import {
  AlertCircle,
  Bell,
  Camera,
  Check,
  CheckCircle2,
  CreditCard,
  Home,
  Image as ImageIcon,
  LogOut,
  MessageCircle,
  Plus,
  ReceiptText,
  Share2,
  ShieldCheck,
  Smartphone,
  Upload,
  Users
} from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
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

type View = "home" | "events" | "receipts" | "payments" | "people" | "splitik";
type PermissionId = "contacts" | "camera" | "gallery" | "notifications";
type PermissionStatus = "pending" | "granted" | "unsupported" | "denied" | "skipped";
type PermissionState = Record<PermissionId, { status: PermissionStatus; detail: string }>;

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

const navItems: Array<{ id: View; label: string; icon: React.ElementType }> = [
  { id: "home", label: "Главная", icon: Home },
  { id: "events", label: "События", icon: Users },
  { id: "receipts", label: "Чеки", icon: ReceiptText },
  { id: "payments", label: "Платежи", icon: CreditCard },
  { id: "people", label: "Люди", icon: ShieldCheck },
  { id: "splitik", label: "Сплитик", icon: MessageCircle }
];

const fallbackEvents = [
  { id: "demo-1", title: "Поездка в Казань", total_kopecks: 1284000, participants_count: 4, status: "active" },
  { id: "demo-2", title: "Ужин после защиты", total_kopecks: 486000, participants_count: 3, status: "review" },
  { id: "demo-3", title: "Квартира июль", total_kopecks: 3690000, participants_count: 2, status: "closed" }
];

const initialPermissionState: PermissionState = {
  contacts: { status: "pending", detail: "Выберите контакт явно, без скрытого чтения адресной книги." },
  camera: { status: "pending", detail: "Откроем системный запрос камеры для фото чека." },
  gallery: { status: "pending", detail: "Откроем выбор изображения из Фото или файлов." },
  notifications: { status: "pending", detail: "Запросим уведомления после установки PWA на экран Домой." }
};

const permissions: Array<{
  id: PermissionId;
  label: string;
  icon: React.ElementType;
  detail: string;
}> = [
  { id: "contacts", label: "Контакты", icon: Users, detail: "найти участников быстрее" },
  { id: "camera", label: "Камера", icon: Camera, detail: "снимать чеки сразу" },
  { id: "gallery", label: "Галерея", icon: ImageIcon, detail: "загрузить фото чека" },
  { id: "notifications", label: "Уведомления", icon: Bell, detail: "не забыть оплату" }
];

export default function SplitAppPage() {
  const [tokens, setTokens] = useState<SplitAppTokens | null>(null);
  const [view, setView] = useState<View>("home");
  const [summary, setSummary] = useState<HomeSummary | null>(null);
  const [isOnline, setIsOnline] = useState(true);
  const [message, setMessage] = useState("Готов к работе");
  const [installPrompt, setInstallPrompt] = useState<Event | null>(null);
  const [isIos, setIsIos] = useState(false);
  const [isStandalone, setIsStandalone] = useState(false);
  const [permissionState, setPermissionState] = useState<PermissionState>(initialPermissionState);
  const galleryInputRef = useRef<HTMLInputElement | null>(null);

  useEffect(() => {
    setTokens(loadTokens());
    setIsOnline(navigator.onLine);
    setIsIos(isIosDevice());
    setIsStandalone(isStandalonePwa());

    const onOnline = () => setIsOnline(true);
    const onOffline = () => setIsOnline(false);
    const onBeforeInstallPrompt = (event: Event) => {
      event.preventDefault();
      setInstallPrompt(event);
    };

    window.addEventListener("online", onOnline);
    window.addEventListener("offline", onOffline);
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

  const events = useMemo(() => summary?.events?.length ? summary.events : fallbackEvents, [summary]);
  const owedToMe = summary?.totals?.owed_to_me_kopecks ?? 184500;
  const iOwe = summary?.totals?.i_owe_kopecks ?? 73200;

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
      const stream = await navigator.mediaDevices.getUserMedia({
        video: { facingMode: { ideal: "environment" } },
        audio: false
      });
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
        updatePermission(
          "gallery",
          files.length ? "granted" : "skipped",
          files.length ? "Фото выбрано из галереи." : "Выбор фото отменен."
        );
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
      updatePermission(
        "notifications",
        "skipped",
        "На iPhone сначала добавьте SplitApp: Share -> Add to Home Screen, потом откройте ярлык."
      );
      return;
    }

    try {
      const result = await Notification.requestPermission();
      if (result !== "granted") {
        updatePermission("notifications", result === "denied" ? "denied" : "skipped", "Уведомления не разрешены.");
        return;
      }

      const registration = "serviceWorker" in navigator ? await navigator.serviceWorker.ready : null;
      const pushPublicKey = process.env.NEXT_PUBLIC_WEB_PUSH_PUBLIC_KEY;
      if (registration?.pushManager && pushPublicKey) {
        await registration.pushManager.subscribe({
          userVisibleOnly: true,
          applicationServerKey: urlBase64ToUint8Array(pushPublicKey)
        });
      }
      updatePermission(
        "notifications",
        "granted",
        pushPublicKey
          ? "Уведомления разрешены и подписка создана."
          : "Уведомления разрешены. Push-подписку подключим после добавления VAPID key."
      );
    } catch (error) {
      updatePermission(
        "notifications",
        "denied",
        permissionErrorMessage(error, "Не удалось запросить уведомления.")
      );
    }
  };

  const requestContactsPermission = async () => {
    if (!navigator.contacts?.select) {
      updatePermission(
        "contacts",
        "unsupported",
        "iPhone Safari обычно не дает Web Contacts API. Используем ручное добавление/инвайт."
      );
      return;
    }

    try {
      const contacts = await navigator.contacts.select(["name", "tel", "email"], { multiple: false });
      updatePermission(
        "contacts",
        contacts.length ? "granted" : "skipped",
        contacts.length ? "Контакт выбран." : "Выбор контакта отменен."
      );
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

  return (
    <main className="min-h-dvh">
      <header className="sticky top-0 z-40 border-b bg-background/88 backdrop-blur-xl">
        <div className="mx-auto flex min-h-[72px] max-w-7xl items-center justify-between gap-3 px-4 sm:px-6 lg:px-8">
          <Link className="flex items-center gap-3 text-sm font-semibold" href="/">
            <span className="grid h-10 w-10 place-items-center rounded-md bg-primary text-primary-foreground">S</span>
            <span>
              <span className="block text-base">SplitApp</span>
              <span className="block text-xs font-medium text-muted-foreground">PWA expenses workspace</span>
            </span>
          </Link>
          <div className="flex items-center gap-2">
            <Badge variant={isOnline ? "secondary" : "outline"}>{isOnline ? "online" : "offline"}</Badge>
            <Button variant="outline" size="sm" onClick={runInstall}>
              Установить SplitApp
            </Button>
            {tokens ? (
              <Button variant="ghost" size="sm" onClick={logout} aria-label="Выйти">
                <LogOut className="h-4 w-4" />
              </Button>
            ) : null}
          </div>
        </div>
      </header>

      <div className="mx-auto grid max-w-7xl gap-6 px-4 py-6 sm:px-6 lg:grid-cols-[232px_minmax(0,1fr)] lg:px-8">
        <aside className="hidden lg:block">
          <nav className="sticky top-24 grid gap-2">
            {navItems.map((item) => (
              <NavButton key={item.id} item={item} active={view === item.id} onClick={() => setView(item.id)} />
            ))}
          </nav>
        </aside>

        <section className="min-w-0">
          {!tokens ? (
            <Landing
              isIos={isIos}
              isStandalone={isStandalone}
              onLogin={startYandexLogin}
              onInstall={runInstall}
              onPermission={requestPermission}
              permissionState={permissionState}
              galleryInputRef={galleryInputRef}
              onGalleryPicked={(picked) =>
                updatePermission(
                  "gallery",
                  picked ? "granted" : "skipped",
                  picked ? "Фото выбрано из галереи." : "Выбор фото отменен."
                )
              }
            />
          ) : (
            <Workspace view={view} events={events} owedToMe={owedToMe} iOwe={iOwe} />
          )}
        </section>
      </div>

      {tokens ? (
        <nav className="fixed inset-x-0 bottom-0 z-40 border-t bg-background/94 px-2 py-2 backdrop-blur-xl lg:hidden">
          <div className="grid grid-cols-6 gap-1">
            {navItems.map((item) => (
              <NavButton key={item.id} item={item} active={view === item.id} compact onClick={() => setView(item.id)} />
            ))}
          </div>
        </nav>
      ) : null}

      <div className="fixed bottom-20 left-1/2 z-50 w-[min(92vw,420px)] -translate-x-1/2 lg:bottom-6" aria-live="polite">
        <AnimatePresence>
          {message ? (
            <motion.div
              className="rounded-md border bg-card px-4 py-3 text-sm shadow-soft"
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

function NavButton({
  item,
  active,
  compact,
  onClick
}: {
  item: { id: View; label: string; icon: React.ElementType };
  active: boolean;
  compact?: boolean;
  onClick: () => void;
}) {
  const Icon = item.icon;
  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        "flex min-h-11 items-center gap-3 rounded-md px-3 text-sm font-semibold text-muted-foreground transition-colors hover:bg-muted hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
        active && "bg-primary text-primary-foreground hover:bg-primary hover:text-primary-foreground",
        compact && "grid justify-items-center gap-1 px-1 text-[11px]"
      )}
    >
      <Icon className="h-4 w-4" />
      <span>{item.label}</span>
    </button>
  );
}

function Landing({
  isIos,
  isStandalone,
  onLogin,
  onInstall,
  onPermission,
  permissionState,
  galleryInputRef,
  onGalleryPicked
}: {
  isIos: boolean;
  isStandalone: boolean;
  onLogin: () => void;
  onInstall: () => void;
  onPermission: (id: PermissionId) => void;
  permissionState: PermissionState;
  galleryInputRef: React.RefObject<HTMLInputElement | null>;
  onGalleryPicked: (picked: boolean) => void;
}) {
  return (
    <div className="grid gap-6">
      {isIos && !isStandalone ? (
        <section className="rounded-lg border border-amber-300 bg-amber-50 p-4 text-amber-950 shadow-panel">
          <div className="flex gap-3">
            <div className="grid h-10 w-10 shrink-0 place-items-center rounded-md bg-amber-200">
              <Share2 className="h-5 w-5" />
            </div>
            <div className="grid gap-1">
              <h2 className="font-semibold">iPhone: сначала добавьте SplitApp на экран Домой</h2>
              <p className="text-sm leading-6">
                Откройте меню Share в Safari и нажмите Add to Home Screen. После запуска с ярлыка
                SplitApp сможет запросить разрешения PWA, включая уведомления.
              </p>
            </div>
          </div>
        </section>
      ) : null}

      <motion.section
        className="grid overflow-hidden rounded-lg border bg-card shadow-panel lg:grid-cols-[1.05fr_0.95fr]"
        initial={{ opacity: 0, y: 16 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.32 }}
      >
        <div className="grid content-center gap-6 p-6 sm:p-8 lg:p-10">
          <Badge className="w-fit" variant="secondary">
            Next.js PWA
          </Badge>
          <div className="grid gap-4">
            <h1 className="max-w-3xl text-4xl font-bold leading-tight tracking-normal sm:text-5xl">
              SplitApp для чеков, долгов и общих событий
            </h1>
            <p className="max-w-2xl text-base leading-7 text-muted-foreground">
              Новый web-клиент на React: рабочая панель, PWA-установка, Яндекс-вход, быстрый доступ к
              событиям, чекам, платежам и Сплитику.
            </p>
          </div>
          <div className="flex flex-wrap gap-3">
            <Button size="lg" onClick={onLogin}>
              Войти через Яндекс
            </Button>
            <Button size="lg" variant="outline" onClick={onInstall}>
              <Smartphone className="h-4 w-4" />
              Установить SplitApp
            </Button>
          </div>
        </div>
        <div className="grid gap-4 bg-slate-950 p-6 text-white sm:p-8">
          <DashboardPreview />
        </div>
      </motion.section>

      <section className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
        {permissions.map((item) => {
          const Icon = item.icon;
          const current = permissionState[item.id];
          return (
            <Card key={item.label}>
              <CardHeader className="min-h-full">
                <div className="flex items-start justify-between gap-3">
                  <div className="grid h-10 w-10 place-items-center rounded-md bg-secondary text-secondary-foreground">
                    <Icon className="h-5 w-5" />
                  </div>
                  <PermissionBadge status={current.status} />
                </div>
                <CardTitle>{item.label}</CardTitle>
                <CardDescription>{current.detail || item.detail}</CardDescription>
                <Button
                  className="mt-2 w-full"
                  variant={current.status === "granted" ? "secondary" : "outline"}
                  onClick={() => onPermission(item.id)}
                >
                  {item.id === "gallery" ? <Upload className="h-4 w-4" /> : null}
                  {current.status === "granted" ? "Проверить снова" : "Разрешить"}
                </Button>
              </CardHeader>
            </Card>
          );
        })}
      </section>

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

function PermissionBadge({ status }: { status: PermissionStatus }) {
  const content: Record<PermissionStatus, { label: string; className: string; icon: React.ElementType }> = {
    pending: { label: "ожидает", className: "bg-muted text-muted-foreground", icon: AlertCircle },
    granted: { label: "готово", className: "bg-emerald-100 text-emerald-800", icon: Check },
    unsupported: { label: "fallback", className: "bg-amber-100 text-amber-800", icon: AlertCircle },
    denied: { label: "запрещено", className: "bg-red-100 text-red-800", icon: AlertCircle },
    skipped: { label: "пропущено", className: "bg-slate-100 text-slate-700", icon: AlertCircle }
  };
  const item = content[status];
  const Icon = item.icon;

  return (
    <span className={cn("inline-flex items-center gap-1 rounded-md px-2 py-1 text-xs font-semibold", item.className)}>
      <Icon className="h-3.5 w-3.5" />
      {item.label}
    </span>
  );
}

function DashboardPreview() {
  return (
    <div className="grid gap-4">
      <div className="flex items-center justify-between">
        <div>
          <p className="text-sm text-cyan-200">Событие</p>
          <h2 className="text-2xl font-bold">Ужин после защиты</h2>
        </div>
        <Badge>review</Badge>
      </div>
      <div className="grid gap-3 sm:grid-cols-2">
        <PreviewTile title="Чек" value="4 860 ₽" tone="bg-amber-300 text-slate-950" />
        <PreviewTile title="Участники" value="3" tone="bg-cyan-300 text-slate-950" />
      </div>
      <div className="rounded-md border border-white/12 bg-white/8 p-4">
        <div className="mb-3 flex items-center justify-between text-sm">
          <span>Сплитик распознал черновик</span>
          <CheckCircle2 className="h-4 w-4 text-emerald-300" />
        </div>
        <div className="grid gap-2">
          {["Пицца", "Напитки", "Такси"].map((label, index) => (
            <div key={label} className="flex items-center justify-between rounded-md bg-white/8 px-3 py-2 text-sm">
              <span>{label}</span>
              <span>{money([230000, 128000, 128000][index])}</span>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

function PreviewTile({ title, value, tone }: { title: string; value: string; tone: string }) {
  return (
    <div className={cn("rounded-md p-4", tone)}>
      <p className="text-sm font-semibold opacity-75">{title}</p>
      <p className="text-2xl font-bold">{value}</p>
    </div>
  );
}

function Workspace({
  view,
  events,
  owedToMe,
  iOwe
}: {
  view: View;
  events: HomeSummary["events"];
  owedToMe: number;
  iOwe: number;
}) {
  return (
    <AnimatePresence mode="wait">
      <motion.div
        key={view}
        className="grid gap-5 pb-24 lg:pb-0"
        initial={{ opacity: 0, y: 12 }}
        animate={{ opacity: 1, y: 0 }}
        exit={{ opacity: 0, y: -8 }}
        transition={{ duration: 0.2 }}
      >
        <section className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <p className="text-sm font-semibold text-muted-foreground">Рабочее пространство</p>
            <h1 className="text-3xl font-bold tracking-normal">{viewTitle(view)}</h1>
          </div>
          <Button>
            <Plus className="h-4 w-4" />
            Создать
          </Button>
        </section>

        <section className="grid gap-4 md:grid-cols-3">
          <MetricCard title="Мне должны" value={money(owedToMe)} helper="по открытым событиям" />
          <MetricCard title="Я должен" value={money(iOwe)} helper="требует подтверждения" />
          <MetricCard title="Активные события" value={String(events?.length ?? 0)} helper="с чеками и платежами" />
        </section>

        <section className="grid gap-4 xl:grid-cols-[1fr_360px]">
          <Card>
            <CardHeader>
              <CardTitle>{view === "splitik" ? "Диалог со Сплитиком" : "События и расходы"}</CardTitle>
              <CardDescription>Данные подтягиваются из backend API, при недоступности показан демо-срез.</CardDescription>
            </CardHeader>
            <CardContent className="grid gap-3">
              {(events ?? fallbackEvents).map((event) => (
                <div key={event.id} className="grid gap-3 rounded-md border p-4 sm:grid-cols-[1fr_auto] sm:items-center">
                  <div>
                    <div className="flex flex-wrap items-center gap-2">
                      <h2 className="font-semibold">{event.title}</h2>
                      <Badge variant="outline">{event.status ?? "active"}</Badge>
                    </div>
                    <p className="text-sm text-muted-foreground">
                      {event.participants_count ?? 0} участника · {money(event.total_kopecks ?? 0)}
                    </p>
                  </div>
                  <Button variant="outline" size="sm">
                    Открыть
                  </Button>
                </div>
              ))}
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>Следующие действия</CardTitle>
              <CardDescription>Приоритетные операции для текущего состояния.</CardDescription>
            </CardHeader>
            <CardContent className="grid gap-3">
              {["Проверить AI-черновик чека", "Подтвердить входящий платеж", "Закрыть событие после сверки"].map(
                (item) => (
                  <div key={item} className="flex gap-3 rounded-md bg-muted p-3 text-sm">
                    <CheckCircle2 className="mt-0.5 h-4 w-4 text-emerald-600" />
                    <span>{item}</span>
                  </div>
                )
              )}
            </CardContent>
          </Card>
        </section>
      </motion.div>
    </AnimatePresence>
  );
}

function MetricCard({ title, value, helper }: { title: string; value: string; helper: string }) {
  return (
    <Card>
      <CardHeader>
        <CardDescription>{title}</CardDescription>
        <CardTitle className="text-2xl">{value}</CardTitle>
      </CardHeader>
      <CardContent>
        <p className="text-sm text-muted-foreground">{helper}</p>
      </CardContent>
    </Card>
  );
}

function viewTitle(view: View) {
  const titles: Record<View, string> = {
    home: "Главная",
    events: "События",
    receipts: "Чеки",
    payments: "Платежи",
    people: "Люди",
    splitik: "Сплитик"
  };
  return titles[view];
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
