const API_BASE = (process.env.NEXT_PUBLIC_VEYRA_API_URL ?? "http://localhost:8000").replace(/\/$/, "");

export class ApiError extends Error {
  status: number;
  code?: string;
  requestId?: string;
  details?: unknown;

  constructor(message: string, status: number, payload?: unknown) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.details = payload;
    if (payload && typeof payload === "object" && "error" in payload) {
      const error = (payload as { error?: { code?: string; request_id?: string } }).error;
      this.code = error?.code;
      this.requestId = error?.request_id ?? undefined;
    }
  }
}

function getErrorMessage(payload: unknown, fallback: string): string {
  if (payload && typeof payload === "object") {
    if ("error" in payload) {
      const error = (payload as { error?: { message?: unknown } }).error;
      if (typeof error?.message === "string") return error.message;
      if (error?.message && typeof error.message === "object") {
        return Object.values(error.message as Record<string, unknown>).flat().join(" ");
      }
    }
    if ("detail" in payload && typeof (payload as { detail?: unknown }).detail === "string") {
      return (payload as { detail: string }).detail;
    }
  }
  return fallback;
}

export async function apiFetch<T>(
  path: string,
  options: RequestInit & { circleUserToken?: string } = {},
): Promise<T> {
  const headers = new Headers(options.headers);
  if (!headers.has("Content-Type") && options.body) headers.set("Content-Type", "application/json");
  headers.set("Accept", "application/json");
  if (options.circleUserToken) headers.set("X-Circle-User-Token", options.circleUserToken);

  const response = await fetch(`${API_BASE}${path}`, {
    ...options,
    headers,
    credentials: "include",
    cache: "no-store",
  });

  if (response.status === 204) return undefined as T;
  const text = await response.text();
  let payload: unknown = null;
  if (text) {
    try { payload = JSON.parse(text); } catch { payload = text; }
  }
  if (!response.ok) {
    throw new ApiError(getErrorMessage(payload, `Request failed (${response.status}).`), response.status, payload);
  }
  return payload as T;
}

export function postJson<T>(path: string, body: unknown, circleUserToken?: string) {
  return apiFetch<T>(path, {
    method: "POST",
    body: JSON.stringify(body),
    circleUserToken,
  });
}

export function patchJson<T>(path: string, body: unknown, circleUserToken?: string) {
  return apiFetch<T>(path, {
    method: "PATCH",
    body: JSON.stringify(body),
    circleUserToken,
  });
}

export function deleteRequest(path: string) {
  return apiFetch<void>(path, { method: "DELETE" });
}
