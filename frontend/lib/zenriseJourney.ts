"use client";

export const ZENRISE_JOURNEY_STORAGE_KEY = "rm_zenrise_journey_v1";
export const ZENRISE_JOURNEY_EVENT_NAME = "rm:zenrise-journey";
export const ZENRISE_JOURNEY_COMPLETE_EVENT_NAME = "rm:zenrise-journey-complete";

const DEFAULT_MARKET_INSPECTION_TARGET = 3;
const DEFAULT_MARKET_INSPECTION_DWELL_MS = 2_000;
const ATTRIBUTION_QUERY_KEYS = [
  "zenrise",
  "zenrise_click_id",
  "zenrise_user_id",
  "zenrise_campaign_id",
  "zenrise_task_id",
  "zr_click_id",
  "zr_user_id",
  "zr_campaign_id",
  "zr_task_id",
  "utm_source",
  "utm_medium",
  "utm_campaign",
] as const;

type ZenriseJourneyEventType = "attribution_captured" | "wallet_connected" | "market_inspected" | "completed";

export type ZenriseAttribution = {
  capturedAt: string;
  landingPath: string;
  referrer: string | null;
  params: Record<string, string>;
};

export type ZenriseWalletConnection = {
  address: string;
  chainId: number | null;
  connectorId: string | null;
  connectorName: string | null;
  connectedAt: string;
  lastSeenAt: string;
};

export type ZenriseMarketInspection = {
  eventId: string;
  canonicalEventId: string | null;
  title: string;
  marketAddress: string | null;
  conditionId: string | null;
  groupSlug: string | null;
  firstSeenAt: string;
  lastSeenAt: string;
  views: number;
};

export type ZenriseJourney = {
  version: 1;
  sessionId: string;
  createdAt: string;
  updatedAt: string;
  targetMarketCount: number;
  uniqueMarketCount: number;
  done: boolean;
  completedAt: string | null;
  attribution: ZenriseAttribution | null;
  wallet: ZenriseWalletConnection | null;
  inspectedMarkets: ZenriseMarketInspection[];
};

export type ZenriseJourneyEventDetail = {
  type: ZenriseJourneyEventType;
  journey: ZenriseJourney;
};

type WalletConnectedInput = {
  address: string;
  chainId?: number | null;
  connectorId?: string | null;
  connectorName?: string | null;
};

type MarketInspectionInput = {
  walletAddress: string;
  eventId: string;
  canonicalEventId?: string | null;
  title: string;
  marketAddress?: string | null;
  conditionId?: string | null;
  groupSlug?: string | null;
};

const isRecord = (value: unknown): value is Record<string, unknown> =>
  typeof value === "object" && value !== null && !Array.isArray(value);

const optionalString = (value: unknown): string | null => (typeof value === "string" && value ? value : null);

const optionalNumber = (value: unknown): number | null =>
  typeof value === "number" && Number.isFinite(value) ? value : null;

const getStorage = (): Storage | null => {
  if (typeof window === "undefined") {
    return null;
  }
  try {
    return window.localStorage;
  } catch {
    return null;
  }
};

const parsePositiveInt = (raw: string | undefined, fallback: number): number => {
  if (!raw) {
    return fallback;
  }
  const parsed = Number.parseInt(raw, 10);
  if (!Number.isFinite(parsed) || parsed < 1) {
    return fallback;
  }
  return parsed;
};

const nowIso = () => new Date().toISOString();

const createSessionId = (): string => {
  if (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function") {
    return crypto.randomUUID();
  }
  return `${Date.now().toString(36)}-${Math.random().toString(36).slice(2)}`;
};

export const getZenriseMarketInspectionTarget = (): number =>
  parsePositiveInt(process.env.NEXT_PUBLIC_ZENRISE_MARKET_INSPECTION_TARGET, DEFAULT_MARKET_INSPECTION_TARGET);

export const getZenriseMarketInspectionDwellMs = (): number =>
  parsePositiveInt(
    process.env.NEXT_PUBLIC_ZENRISE_MARKET_INSPECTION_MIN_DWELL_MS,
    DEFAULT_MARKET_INSPECTION_DWELL_MS,
  );

const normalizeAttribution = (value: unknown): ZenriseAttribution | null => {
  if (!isRecord(value)) {
    return null;
  }
  const capturedAt = optionalString(value.capturedAt);
  const landingPath = optionalString(value.landingPath);
  if (!capturedAt || !landingPath) {
    return null;
  }
  const params: Record<string, string> = {};
  if (isRecord(value.params)) {
    Object.entries(value.params).forEach(([key, rawValue]) => {
      if (typeof rawValue === "string") {
        params[key] = rawValue;
      }
    });
  }
  return {
    capturedAt,
    landingPath,
    referrer: optionalString(value.referrer),
    params,
  };
};

const normalizeWallet = (value: unknown): ZenriseWalletConnection | null => {
  if (!isRecord(value)) {
    return null;
  }
  const address = optionalString(value.address);
  const connectedAt = optionalString(value.connectedAt);
  const lastSeenAt = optionalString(value.lastSeenAt);
  if (!address || !connectedAt || !lastSeenAt) {
    return null;
  }
  return {
    address,
    chainId: optionalNumber(value.chainId),
    connectorId: optionalString(value.connectorId),
    connectorName: optionalString(value.connectorName),
    connectedAt,
    lastSeenAt,
  };
};

const normalizeMarketInspection = (value: unknown): ZenriseMarketInspection | null => {
  if (!isRecord(value)) {
    return null;
  }
  const eventId = optionalString(value.eventId);
  const title = optionalString(value.title);
  const firstSeenAt = optionalString(value.firstSeenAt);
  const lastSeenAt = optionalString(value.lastSeenAt);
  const views = optionalNumber(value.views);
  if (!eventId || !title || !firstSeenAt || !lastSeenAt || views === null) {
    return null;
  }
  return {
    eventId,
    canonicalEventId: optionalString(value.canonicalEventId),
    title,
    marketAddress: optionalString(value.marketAddress),
    conditionId: optionalString(value.conditionId),
    groupSlug: optionalString(value.groupSlug),
    firstSeenAt,
    lastSeenAt,
    views,
  };
};

const normalizeJourney = (value: unknown): ZenriseJourney | null => {
  if (!isRecord(value)) {
    return null;
  }
  const sessionId = optionalString(value.sessionId);
  const createdAt = optionalString(value.createdAt);
  const updatedAt = optionalString(value.updatedAt);
  if (!sessionId || !createdAt || !updatedAt) {
    return null;
  }
  const inspectedMarkets = Array.isArray(value.inspectedMarkets)
    ? value.inspectedMarkets
        .map(normalizeMarketInspection)
        .filter((item): item is ZenriseMarketInspection => item !== null)
    : [];
  const targetMarketCount = optionalNumber(value.targetMarketCount) ?? getZenriseMarketInspectionTarget();
  const completedAt = optionalString(value.completedAt);
  return {
    version: 1,
    sessionId,
    createdAt,
    updatedAt,
    targetMarketCount,
    uniqueMarketCount: inspectedMarkets.length,
    done: Boolean(value.done) && Boolean(completedAt),
    completedAt,
    attribution: normalizeAttribution(value.attribution),
    wallet: normalizeWallet(value.wallet),
    inspectedMarkets,
  };
};

export const readZenriseJourney = (): ZenriseJourney | null => {
  const storage = getStorage();
  if (!storage) {
    return null;
  }
  const raw = storage.getItem(ZENRISE_JOURNEY_STORAGE_KEY);
  if (!raw) {
    return null;
  }
  try {
    return normalizeJourney(JSON.parse(raw));
  } catch {
    return null;
  }
};

const createEmptyJourney = (timestamp: string): ZenriseJourney => ({
  version: 1,
  sessionId: createSessionId(),
  createdAt: timestamp,
  updatedAt: timestamp,
  targetMarketCount: getZenriseMarketInspectionTarget(),
  uniqueMarketCount: 0,
  done: false,
  completedAt: null,
  attribution: null,
  wallet: null,
  inspectedMarkets: [],
});

const getOrCreateJourney = (timestamp: string): ZenriseJourney => readZenriseJourney() ?? createEmptyJourney(timestamp);

const writeJourney = (journey: ZenriseJourney): void => {
  const storage = getStorage();
  if (!storage) {
    return;
  }
  storage.setItem(ZENRISE_JOURNEY_STORAGE_KEY, JSON.stringify(journey));
};

const dispatchJourneyEvent = (type: ZenriseJourneyEventType, journey: ZenriseJourney): void => {
  if (typeof window === "undefined") {
    return;
  }
  const detail: ZenriseJourneyEventDetail = { type, journey };
  window.dispatchEvent(new CustomEvent<ZenriseJourneyEventDetail>(ZENRISE_JOURNEY_EVENT_NAME, { detail }));
  if (type === "completed") {
    window.dispatchEvent(new CustomEvent<ZenriseJourneyEventDetail>(ZENRISE_JOURNEY_COMPLETE_EVENT_NAME, { detail }));
  }
};

const finalizeJourney = (journey: ZenriseJourney, timestamp: string): { journey: ZenriseJourney; completedNow: boolean } => {
  const uniqueMarketCount = journey.inspectedMarkets.length;
  const done = Boolean(journey.wallet?.address) && uniqueMarketCount >= journey.targetMarketCount;
  const completedNow = done && !journey.completedAt;
  return {
    journey: {
      ...journey,
      uniqueMarketCount,
      done,
      completedAt: completedNow ? timestamp : journey.completedAt,
      updatedAt: timestamp,
    },
    completedNow,
  };
};

export const captureZenriseAttribution = (): ZenriseJourney | null => {
  if (typeof window === "undefined") {
    return null;
  }
  const timestamp = nowIso();
  const params = new URL(window.location.href).searchParams;
  const capturedParams: Record<string, string> = {};
  ATTRIBUTION_QUERY_KEYS.forEach((key) => {
    const value = params.get(key);
    if (value) {
      capturedParams[key] = value;
    }
  });
  const hasAttribution = Object.keys(capturedParams).length > 0;
  const existing = readZenriseJourney();
  if (!hasAttribution) {
    return existing;
  }
  const baseJourney = existing ?? createEmptyJourney(timestamp);
  const journey = {
    ...baseJourney,
    attribution: {
      capturedAt: timestamp,
      landingPath: `${window.location.pathname}${window.location.search}`,
      referrer: document.referrer || null,
      params: capturedParams,
    },
    updatedAt: timestamp,
  };
  writeJourney(journey);
  dispatchJourneyEvent("attribution_captured", journey);
  return journey;
};

export const recordZenriseWalletConnected = (input: WalletConnectedInput): ZenriseJourney | null => {
  const address = input.address.trim().toLowerCase();
  if (!address) {
    return readZenriseJourney();
  }
  const timestamp = nowIso();
  const existing = getOrCreateJourney(timestamp);
  const sameWallet = existing.wallet?.address.toLowerCase() === address;
  const wallet: ZenriseWalletConnection = {
    address,
    chainId: input.chainId ?? null,
    connectorId: input.connectorId ?? null,
    connectorName: input.connectorName ?? null,
    connectedAt: sameWallet ? existing.wallet?.connectedAt ?? timestamp : timestamp,
    lastSeenAt: timestamp,
  };
  const targetMarketCount = getZenriseMarketInspectionTarget();
  const { journey, completedNow } = finalizeJourney(
    {
      ...existing,
      wallet,
      targetMarketCount,
      inspectedMarkets: sameWallet ? existing.inspectedMarkets : [],
      completedAt: sameWallet ? existing.completedAt : null,
      done: sameWallet ? existing.done : false,
    },
    timestamp,
  );
  writeJourney(journey);
  dispatchJourneyEvent("wallet_connected", journey);
  if (completedNow) {
    dispatchJourneyEvent("completed", journey);
  }
  return journey;
};

export const recordZenriseMarketInspection = (input: MarketInspectionInput): ZenriseJourney | null => {
  const eventId = input.eventId.trim();
  if (!eventId) {
    return readZenriseJourney();
  }
  const timestamp = nowIso();
  const existing = getOrCreateJourney(timestamp);
  const walletAddress = input.walletAddress.trim().toLowerCase();
  if (!existing.wallet?.address || existing.wallet.address.toLowerCase() !== walletAddress) {
    return existing;
  }
  const inspectedMarkets = [...existing.inspectedMarkets];
  const existingIndex = inspectedMarkets.findIndex((item) => item.eventId === eventId);
  if (existingIndex >= 0) {
    const current = inspectedMarkets[existingIndex];
    inspectedMarkets[existingIndex] = {
      ...current,
      title: input.title,
      canonicalEventId: input.canonicalEventId ?? current.canonicalEventId,
      marketAddress: input.marketAddress ?? current.marketAddress,
      conditionId: input.conditionId ?? current.conditionId,
      groupSlug: input.groupSlug ?? current.groupSlug,
      lastSeenAt: timestamp,
      views: current.views + 1,
    };
  } else {
    inspectedMarkets.push({
      eventId,
      canonicalEventId: input.canonicalEventId ?? null,
      title: input.title,
      marketAddress: input.marketAddress ?? null,
      conditionId: input.conditionId ?? null,
      groupSlug: input.groupSlug ?? null,
      firstSeenAt: timestamp,
      lastSeenAt: timestamp,
      views: 1,
    });
  }
  const { journey, completedNow } = finalizeJourney(
    {
      ...existing,
      targetMarketCount: getZenriseMarketInspectionTarget(),
      inspectedMarkets,
    },
    timestamp,
  );
  writeJourney(journey);
  dispatchJourneyEvent("market_inspected", journey);
  if (completedNow) {
    dispatchJourneyEvent("completed", journey);
  }
  return journey;
};
