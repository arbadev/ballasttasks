export type ApiErrorKind = "http" | "network";

interface ApiErrorOptions {
  kind: ApiErrorKind;
  status: number | null;
  body?: unknown;
  cause?: unknown;
}

/**
 * The single error type the HTTP layer throws. `body` is kept because some endpoints
 * answer a non-2xx status with a meaningful JSON payload (e.g. /health/ready on 503).
 */
export class ApiError extends Error {
  readonly kind: ApiErrorKind;
  /** HTTP status, or null when no response was received. */
  readonly status: number | null;
  /** Parsed JSON body of the response, when there was one. */
  readonly body: unknown;

  constructor(message: string, { kind, status, body, cause }: ApiErrorOptions) {
    super(message, { cause });
    this.name = "ApiError";
    this.kind = kind;
    this.status = status;
    this.body = body;
  }
}

/** What features depend on, so they never see fetch or a concrete client. */
export interface HttpClient {
  get<T>(path: string): Promise<T>;
}

async function readJson(response: Response): Promise<unknown> {
  try {
    return await response.json();
  } catch {
    return undefined;
  }
}

/** The only module in the app allowed to call fetch. */
export class ApiClient implements HttpClient {
  constructor(private readonly baseUrl: string) {}

  async get<T>(path: string): Promise<T> {
    const url = `${this.baseUrl}${path}`;

    let response: Response;
    try {
      response = await fetch(url, { headers: { Accept: "application/json" }, cache: "no-store" });
    } catch (cause) {
      throw new ApiError(`Network request to ${url} failed`, {
        kind: "network",
        status: null,
        cause,
      });
    }

    const body = await readJson(response);

    if (!response.ok) {
      throw new ApiError(`GET ${url} responded with ${response.status}`, {
        kind: "http",
        status: response.status,
        body,
      });
    }
    if (body === undefined) {
      throw new ApiError(`GET ${url} did not return valid JSON`, {
        kind: "http",
        status: response.status,
      });
    }
    return body as T;
  }
}
