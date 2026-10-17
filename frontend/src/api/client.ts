import { API_URL } from "../config";
import { reportError } from "../store/errors";
import type { ErrorBody } from "./types";

export class ApiError extends Error {
  constructor(
    public body: ErrorBody,
    public status: number,
  ) {
    super(`${body.code}: ${body.message}`);
  }
}

let requestCounter = 0;
const newRequestId = () => `c${Date.now().toString(36)}${(requestCounter++).toString(36)}`;

/** Every failed request lands in the error panel, so nobody has to open the network tab. */
export async function api<T>(path: string, init: RequestInit & { quiet?: boolean } = {}): Promise<T> {
  const requestId = newRequestId();
  const headers = new Headers(init.headers);
  headers.set("X-Request-ID", requestId);
  if (init.body && typeof init.body === "string") headers.set("Content-Type", "application/json");
  let res: Response;
  try {
    res = await fetch(`${API_URL}${path}`, { ...init, headers });
  } catch (e) {
    const body: ErrorBody = {
      code: "NETWORK_ERROR",
      message: `Cannot reach backend ${API_URL}: ${(e as Error).message}`,
      request_id: requestId,
    };
    if (!init.quiet) reportError({ level: "error", source: "client", ...toEntry(body, path) });
    throw new ApiError(body, 0);
  }
  if (res.ok) return (await res.json()) as T;
  let body: ErrorBody;
  try {
    body = ((await res.json()) as { error: ErrorBody }).error;
  } catch {
    body = { code: `HTTP_${res.status}`, message: res.statusText, request_id: requestId };
  }
  body.request_id ??= requestId;
  if (!init.quiet) reportError({ level: "error", source: "client", ...toEntry(body, path) });
  throw new ApiError(body, res.status);
}

function toEntry(body: ErrorBody, path: string) {
  return {
    code: body.code,
    message: `${body.message}  (${path})`,
    requestId: body.request_id,
    details: body.details && Object.keys(body.details).length ? body.details : undefined,
    modelId: (body.details?.model_id as string | undefined) ?? null,
  };
}

export const json = (data: unknown) => JSON.stringify(data);
