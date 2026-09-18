import { setupServer } from "msw/node";

// Handlers are registered per test so each case states the API behaviour it depends on.
export const server = setupServer();
