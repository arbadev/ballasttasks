/**
 * The canned drafts the in-memory assistant proposes, copied verbatim from the design
 * (hence the single quotes). A real implementation asks the API's LanguageModel port.
 */
// prettier-ignore
const DRAFTS: Record<string, readonly string[]> = {
  t4: ['users table + Alembic migration (email, password_hash)', 'Ports: PasswordHasher and TokenIssuer; adapters: argon2 and PyJWT', 'Use cases: register, login → access + refresh tokens', 'current_user dependency on every /tasks route (401 on missing or expired)', 'Contract tests for both token adapters; API tests for the 401 paths', 'Frontend: token storage in client.ts, login form, redirect on 401'],
  t6: ['Add a seed command: 3 users, 12 tasks across every status', 'Demo credentials in README (demo@ballast.dev / demo1234)', 'Make it idempotent — skip when users already exist', 'Run the seed in the api container entrypoint behind SEED=1'],
  t7: ['RateLimiter port with allow(key) -> bool', 'Redis token-bucket adapter + in-memory fake', 'FastAPI middleware keyed by user id, falling back to client IP', 'Document the 429 response in OpenAPI', 'Contract tests parametrised over both adapters'],
  t9: ['Outline: user story → architecture → demo → GenAI usage (12 min)', 'Record a 2-minute fallback demo video', 'Prepare 3 code-review hotspots: bootstrap.py, the ports, TaskService', 'Rehearse the AI-evaluation answer: what was corrected and why'],
  t3: ['Define the job payload (task id, prompt version) and result schema', 'Prompt template: title, description, attachment summaries, step count cap', 'Worker writes proposed steps with status=proposed, never directly to the task', 'GET /jobs/{id} for polling; 202 on enqueue', 'Deterministic fake provider for the unit and API tests'],
  t5: ['Overview: one paragraph, who the app is for', 'Three user stories mapped to the CRUD, filter and steps endpoints', 'Non-goals: teams, recurring tasks, notifications'],
  t8: ['Paste the exact scaffold prompt used', 'Show a 40-line representative sample of the output', 'Table: what the AI got wrong → the fix → why it matters', 'Note edge cases handled: auth, validation, pagination bounds'],
  t16: ['Reply to the recruiter thread with two slots', 'Ask who sits on the panel and how long the review is', 'Block the calendar and add the Meet link to this task'],
};

// prettier-ignore
const FALLBACK: readonly string[] = ['Clarify the outcome and acceptance criteria', 'Cut a first vertical slice that can be demoed', 'Write the failing test for that slice', 'Implement, then run make lint and make test', 'Update the docs and commit'];

export function draftStepsFor(taskId: string): readonly string[] {
  return DRAFTS[taskId] ?? FALLBACK;
}
