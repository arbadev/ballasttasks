export type ApiErrorKind = "http" | "network" | "session";

interface ApiErrorOptions {
  kind: ApiErrorKind;
  status: number | null;
  body?: unknown;
  cause?: unknown;
  retryAfterSeconds?: number | null;
}

/** A safe transport failure. Credential endpoint response bodies are never retained. */
export class ApiError extends Error {
  readonly kind: ApiErrorKind;
  readonly status: number | null;
  readonly body: unknown;
  /** The API's delta-seconds Retry-After, or null when missing/invalid. */
  readonly retryAfterSeconds: number | null;

  constructor(message: string, { kind, status, body, cause, retryAfterSeconds }: ApiErrorOptions) {
    super(message, { cause });
    this.name = "ApiError";
    this.kind = kind;
    this.status = status;
    this.body = body;
    this.retryAfterSeconds = retryAfterSeconds ?? null;
  }
}

/** Read-only consumers such as health do not depend on mutation capabilities. */
export interface HttpClient {
  get<T>(path: string): Promise<T>;
}

export interface RequestOptions {
  method?: "GET" | "POST" | "PATCH" | "PUT" | "DELETE";
  body?: object;
  /** Login, registration and SSO exchange must not send a previous session's token. */
  authenticated?: boolean;
}

export interface HttpTransport extends HttpClient {
  request<T>(path: string, options?: RequestOptions): Promise<T>;
  download(path: string): Promise<Blob>;
}

interface Credentials {
  token(): string | null;
  /** Session epoch fences every completion, including old public login requests. */
  version?(): number;
  /** Session-scoped data clients cannot send queued work after that session ends. */
  expectedVersion?: number;
  unauthorized?(): void;
}

async function readJson(response: Response): Promise<unknown> {
  try {
    return await response.json();
  } catch {
    return undefined;
  }
}

function retryAfter(response: Response): number | null {
  const value = response.headers.get("Retry-After");
  if (value === null || !/^\d+$/.test(value)) return null;
  const seconds = Number(value);
  return Number.isSafeInteger(seconds) ? seconds : null;
}

/**
 * The only fetch caller. No automatic retries: repeating a mutation can duplicate it.
 * Credential ownership/persistence belongs to the injected session, not this transport.
 */
export class ApiClient implements HttpTransport {
  constructor(private readonly baseUrl: string, private readonly credentials?: Credentials) {}

  get<T>(path: string): Promise<T> {
    return this.request<T>(path);
  }

  async request<T>(path: string, options: RequestOptions = {}): Promise<T> {
    const version = this.credentials?.version?.();
    const response = await this.send(path, options);
    if (response.status === 204) return undefined as T;
    const body = await readJson(response);
    this.assertSession(version);
    if (body === undefined) {
      throw new ApiError("The API returned an invalid response.", {
        kind: "http", status: response.status,
      });
    }
    return body as T;
  }

  async download(path: string): Promise<Blob> {
    const version = this.credentials?.version?.();
    const response = await this.send(path, {}, "application/octet-stream");
    const blob = await response.blob();
    this.assertSession(version);
    return blob;
  }

  private async send(path: string, options: RequestOptions, accept = "application/json"): Promise<Response> {
    const version = this.credentials?.version?.();
    this.assertSession(version);
    const token = options.authenticated === false ? null : this.credentials?.token();
    const headers: Record<string, string> = { Accept: accept };
    if (token) headers.Authorization = `Bearer ${token}`;
    let body: BodyInit | undefined;
    if (options.body instanceof FormData || options.body instanceof URLSearchParams) {
      body = options.body; // The browser supplies multipart boundaries / form content type.
    } else if (options.body !== undefined) {
      body = JSON.stringify(options.body);
      headers["Content-Type"] = "application/json";
    }
    let response: Response;
    try {
      response = await fetch(`${this.baseUrl}${path}`, {
        method: options.method ?? "GET", headers, body,
        cache: "no-store", credentials: "omit", redirect: "error",
      });
    } catch {
      // A native error can contain a sensitive URL. Do not retain it as a cause.
      throw new ApiError("Could not reach the API. Try again.", { kind: "network", status: null });
    }
    this.assertSession(version);
    if (!response.ok) {
      const errorBody = path.startsWith("/auth/") ? undefined : await readJson(response);
      this.assertSession(version);
      // A delayed 401 from the previous session must not sign out a new one.
      if (response.status === 401 && token && token === this.credentials?.token()) {
        this.credentials.unauthorized?.();
      }
      throw new ApiError(`The API request failed (${response.status}).`, {
        kind: "http", status: response.status, body: errorBody,
        retryAfterSeconds: retryAfter(response),
      });
    }
    return response;
  }

  private assertSession(version: number | undefined): void {
    const current = this.credentials?.version?.();
    if (version !== current || (this.credentials?.expectedVersion !== undefined && this.credentials.expectedVersion !== current)) {
      throw new ApiError("This session has ended. Sign in again.", { kind: "session", status: null });
    }
  }
}
