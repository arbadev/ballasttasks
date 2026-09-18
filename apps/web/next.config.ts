import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Self-contained server bundle for the Docker image.
  output: "standalone",
  // `next dev` otherwise writes AGENTS.md/CLAUDE.md here whenever it detects a coding agent.
  // Agent guidance for this monorepo lives at the repository root, and the working tree
  // should not depend on who runs the dev server.
  agentRules: false,
};

export default nextConfig;
