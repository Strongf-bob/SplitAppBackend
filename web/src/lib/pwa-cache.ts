import type { EventSummary, Friendship, HomeSummary, UserProfile } from "@/lib/splitapp-api";

export type CachedChatMessage = {
  id: string;
  from: "user" | "splitik";
  text: string;
};

export type PwaAppSnapshot = {
  version: 1;
  updatedAt: number;
  summary: HomeSummary | null;
  events: EventSummary[];
  currentUser: UserProfile | null;
  friendships: Friendship[];
  chatMessages: CachedChatMessage[];
};

const snapshotPrefix = "splitapp.pwaSnapshot.v1";

const snapshotKey = (userId?: string | null) => `${snapshotPrefix}:${userId || "anonymous"}`;

const emptySnapshot = (): PwaAppSnapshot => ({
  version: 1,
  updatedAt: Date.now(),
  summary: null,
  events: [],
  currentUser: null,
  friendships: [],
  chatMessages: []
});

export function loadPwaSnapshot(userId?: string | null): PwaAppSnapshot | null {
  if (typeof window === "undefined") return null;
  try {
    const raw = window.localStorage.getItem(snapshotKey(userId));
    if (!raw) return null;
    const parsed = JSON.parse(raw) as Partial<PwaAppSnapshot>;
    if (parsed.version !== 1 || typeof parsed.updatedAt !== "number") return null;
    return {
      ...emptySnapshot(),
      ...parsed,
      summary: parsed.summary ?? null,
      events: Array.isArray(parsed.events) ? parsed.events : [],
      currentUser: parsed.currentUser ?? null,
      friendships: Array.isArray(parsed.friendships) ? parsed.friendships : [],
      chatMessages: Array.isArray(parsed.chatMessages) ? parsed.chatMessages : []
    };
  } catch {
    return null;
  }
}

export function savePwaSnapshot(userId: string | null | undefined, snapshot: Omit<PwaAppSnapshot, "version" | "updatedAt">) {
  if (typeof window === "undefined") return;
  const nextSnapshot: PwaAppSnapshot = {
    version: 1,
    updatedAt: Date.now(),
    ...snapshot,
    events: snapshot.events.slice(0, 50),
    friendships: snapshot.friendships.slice(0, 100),
    chatMessages: snapshot.chatMessages.slice(-40).map(({ id, from, text }) => ({ id, from, text }))
  };
  window.localStorage.setItem(snapshotKey(userId), JSON.stringify(nextSnapshot));
}

export function clearPwaSnapshot(userId?: string | null) {
  if (typeof window === "undefined") return;
  window.localStorage.removeItem(snapshotKey(userId));
}
