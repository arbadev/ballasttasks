import type { Person } from "@/features/tasks/model/types";

export interface Session {
  epoch: number;
  user: Person | null;
  reason?: "expired";
}

export interface AuthService {
  current(): Session;
  subscribe(listener: () => void): () => void;
  login(email: string, password: string): Promise<void>;
  register(email: string, name: string, password: string): Promise<void>;
  exchange(code: string): Promise<void>;
  providers(): Promise<{ name: string; url: string }[]>;
  logout(): void;
}
