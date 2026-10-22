import type { Asset, LayerDocument, Project, ProjectDetail, Version } from "./types";

const BASE = "/api/bff/map-studio";
let sessionCsrfToken: string | null = null;
export class StudioApiError extends Error { constructor(public status: number, message: string, public detail?: unknown) { super(message); this.name = "StudioApiError"; } }

function csrfToken(): string | null { return sessionCsrfToken; }
async function request<T>(path: string, init: RequestInit = {}, idempotencyKey?: string): Promise<T> {
  const headers = new Headers(init.headers);
  if (init.body && !headers.has("content-type")) headers.set("content-type", "application/json");
  if (init.method && !["GET", "HEAD"].includes(init.method.toUpperCase())) {
    const csrf = csrfToken(); if (csrf) headers.set("X-CSRF-Token", csrf);
  }
  if (idempotencyKey) headers.set("Idempotency-Key", idempotencyKey);
  const response = await fetch(`${BASE}${path}`, { ...init, headers, credentials: "include", cache: "no-store" });
  if (!response.ok) {
    let detail: unknown;
    try { detail = await response.json(); } catch { /* preserve status message */ }
    const message = typeof detail === "object" && detail && "detail" in detail ? String((detail as { detail: unknown }).detail) : response.status === 401 ? "Your session has expired. Sign in again to continue." : response.status === 409 ? "Someone else changed this map. Review the newer draft before saving." : `Map Studio could not complete that request (${response.status}).`;
    throw new StudioApiError(response.status, message, detail);
  }
  if (response.status === 204) return undefined as T;
  return response.json() as Promise<T>;
}

export type Session = { authenticated: boolean; user?: { id: string; email?: string; name?: string } | null; csrfToken?: string | null };
async function authRequest<T>(path: string, init: RequestInit = {}): Promise<T> {
  const response = await fetch(path, { ...init, credentials: "include", cache: "no-store" });
  if (!response.ok) throw new StudioApiError(response.status, response.status === 401 ? "Your session has expired. Sign in again to continue." : "Authentication service is unavailable.");
  const body = await response.json() as T;
  if (path === "/api/auth/session") sessionCsrfToken = (body as Session).csrfToken ?? null;
  if (path === "/api/auth/logout") { sessionCsrfToken = null; }
  return body;
}

export const studioApi = {
  session: () => authRequest<Session>("/api/auth/session"),
  logout: () => authRequest<{ ok: true }>("/api/auth/logout", { method: "POST", headers: { "X-CSRF-Token": csrfToken() ?? "" } }),
  projects: () => request<{ projects: Project[]; isAdmin: boolean }>("/projects"),
  project: (key: string) => request<ProjectDetail>(`/projects/${encodeURIComponent(key)}`),
  lease: (key: string, clientId: string) => request<{ clientId: string; expiresAt: string }>(`/projects/${encodeURIComponent(key)}/lease`, { method: "POST", body: JSON.stringify({ clientId }) }),
  releaseLease: (key: string, clientId: string) => request<{ ok: true }>(`/projects/${encodeURIComponent(key)}/lease/release`, { method: "POST", body: JSON.stringify({ clientId }) }),
  saveDraft: (key: string, document: LayerDocument, expectedRevision: number, clientId: string) => request<{ revision: number; document: LayerDocument }>(`/projects/${encodeURIComponent(key)}/draft`, { method: "POST", body: JSON.stringify({ document, expectedRevision, clientId }) }),
  versions: (key: string) => request<{ versions: Version[]; publishedVersionId: string | null }>(`/projects/${encodeURIComponent(key)}/versions`),
  publish: (key: string, expectedRevision: number, clientId: string) => request<{ versionId: string }>(`/projects/${encodeURIComponent(key)}/publish`, { method: "POST", body: JSON.stringify({ expectedRevision, clientId }) }, crypto.randomUUID()),
  rollback: (key: string, versionId: string, clientId: string) => request<{ versionId: string }>(`/projects/${encodeURIComponent(key)}/rollback`, { method: "POST", body: JSON.stringify({ versionId, clientId }) }, crypto.randomUUID()),
  assets: (key: string) => request<{ assets: Asset[] }>(`/projects/${encodeURIComponent(key)}/assets`),
  uploadAsset: (key: string, body: { name: string; altText: string; rights: string; mimeType: string; dataBase64: string }) => request<{ asset: Asset }>(`/projects/${encodeURIComponent(key)}/assets`, { method: "POST", body: JSON.stringify(body) }),
  deleteAsset: (key: string, assetId: string) => request<{ ok: true }>(`/projects/${encodeURIComponent(key)}/assets/${encodeURIComponent(assetId)}/delete`, { method: "POST" }),
};

export function loginHref(): string { return `/api/auth/login?return=${encodeURIComponent(window.location.pathname + window.location.search)}`; }
