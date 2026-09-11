1. Context & Execution Scope (The "Guardrails")
    • Goal Statement: A concise, single-sentence explanation of what the agent must build.
    • Component Boundaries: Explicit declarations of what files/directories the agent is allowed to touch and what is strictly off-limits.
    • Tech Stack & Version Pinning: Exact versions of languages, libraries, and frameworks (e.g., Node.js v22.0.0, Next.js v15.1) to prevent the agent from hallucinating deprecated or future syntax.
2. State Machine & Domain Schemas
    • Strict Types & Schemas: Exact JSON/Zod schemas, database models, or TypeScript interfaces. Agents thrive on explicit types.
    • State Transition Rules: A strict mapping of inputs to output states (e.g., Status: DRAFT -> SUBMITTED can only happen if Payload.isValid === true).
3. Step-by-Step Execution Protocol
    • Atomic Sub-tasks: Break down the implementation into chronological, linear steps. Agents perform significantly better when given a sequential checklist rather than a broad objective.
    • Edge Case Matrix: A explicit list of errors the agent must handle (e.g., "If network timeout happens, retry 3 times, then throw NetworkException").
4. Code Style & Architecture Constraints
    • Design Patterns: Explicitly command the pattern to use (e.g., "Use the Repository Pattern; do not write inline SQL queries").
    • Naming & Style Guidelines: Explicit variable naming conventions (e.g., camelCase for variables, PascalCase for classes) and file structures to maintain code consistency.
    • Code Splitting Metrics: Maximum limits to prevent agentic bloat (e.g., "No single function should exceed 40 lines of code; split into utility files if necessary").
5. API & Interface Contracts
    • OpenAPI / Protocol Buffers: Copy-pasteable, valid spec strings directly inside the document.
    • Mock Request/Response Payloads: Perfect, production-grade JSON examples for every single API scenario.
6. Dependency & Environment Configuration
    • Environment Variables: A strict checklist of .env variables required, including their expected data types and descriptions.
    • Third-Party Integration Contracts: Stubbed-out definitions or SDK expectations for external services (like Stripe or Auth0) so the agent can safely mock them.
7. Definition of Done (DoD) & Verification Script
    • Automated Test Matrix: A comprehensive list of unit and integration tests the agent must write and pass.
    • Verification Command: The exact terminal command the agent should execute to verify its work (e.g., npm run test:ci && npm run lint).
8. Failure Modes & Self-Correction Hints
    • Known Gotchas: Explanations of common anti-patterns or quirks in your existing codebase that the agent might accidentally replicate.
    • Fallback Instructions: Directives on what the agent should do if it gets stuck in an infinite loop or encounters a terminal error (e.g., "If the test fails 3 consecutive times with the same error, write a log to agent_error.log and halt execution").
