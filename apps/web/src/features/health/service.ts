import { ApiError, type HttpClient } from "@/lib/api/client";
import type { components } from "@/lib/api/schema";

// Wire types come from the generated OpenAPI schema, never redeclared by hand.
type HealthResponse = components["schemas"]["HealthResponse"];
type ReadinessResponse = components["schemas"]["ReadinessResponse"];

export interface ComponentStatusView {
  name: string;
  label: string;
  ok: boolean;
}

export interface AiInfoView {
  provider: string;
  model: string;
}

/** View model owned by this feature; the UI never sees the wire format. */
export interface HealthViewModel {
  /** Whether GET /health answered at all. */
  apiReachable: boolean;
  /** Whether every readiness check passed. */
  ready: boolean;
  components: ComponentStatusView[];
  ai: AiInfoView | null;
}

export interface HealthService {
  getHealth(): Promise<HealthViewModel>;
}

// Display names for known checks. An unlisted name falls back to the raw name, so a new
// backend check shows up on the page with no frontend change.
const LABELS: Record<string, string> = {
  database: "Database",
  redis: "Redis",
  ai: "AI",
};

const API_UNREACHABLE: HealthViewModel = {
  apiReachable: false,
  ready: false,
  components: [],
  ai: null,
};

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

// An error body is untyped, so its shape is checked before it is trusted.
function isReadinessResponse(value: unknown): value is ReadinessResponse {
  return (
    isRecord(value) &&
    (value.status === "ready" || value.status === "not_ready") &&
    Array.isArray(value.checks) &&
    value.checks.every(
      (check) =>
        isRecord(check) &&
        typeof check.name === "string" &&
        (check.status === "ok" || check.status === "failed"),
    ) &&
    isRecord(value.ai) &&
    typeof value.ai.provider === "string" &&
    typeof value.ai.model === "string"
  );
}

function toViewModel(readiness: ReadinessResponse): HealthViewModel {
  return {
    apiReachable: true,
    ready: readiness.status === "ready",
    components: readiness.checks.map((check) => ({
      name: check.name,
      label: LABELS[check.name] ?? check.name,
      ok: check.status === "ok",
    })),
    ai: { provider: readiness.ai.provider, model: readiness.ai.model },
  };
}

export class HttpHealthService implements HealthService {
  constructor(private readonly client: HttpClient) {}

  async getHealth(): Promise<HealthViewModel> {
    try {
      await this.client.get<HealthResponse>("/health");
      return toViewModel(await this.readiness());
    } catch (error) {
      // An unreachable API is a state the page displays, not a failure of the page.
      if (error instanceof ApiError && error.kind === "network") {
        return API_UNREACHABLE;
      }
      throw error;
    }
  }

  private async readiness(): Promise<ReadinessResponse> {
    try {
      return await this.client.get<ReadinessResponse>("/health/ready");
    } catch (error) {
      // 503 means "not ready" and carries the same body shape as 200.
      if (error instanceof ApiError && error.status === 503 && isReadinessResponse(error.body)) {
        return error.body;
      }
      throw error;
    }
  }
}
