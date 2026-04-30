# Manual Test Fix Items

Source: real player run on 2026-04-30 08:41-08:50 local time.

Scope for this iteration:

- Include all stored conversation history for the current player as role messages in LLM context, excluding the current request row.
- Keep the current end-portal/stronghold command behavior unchanged for this iteration.
- Prevent model-facing memory search from returning old conversation, event, action, or removed body-control content as stable memory.
- Force player-specific home facts into player-scoped memory and sanitize the current Minecraft username before storage.
- Improve web search observations so Mina can detect weak or incomplete search evidence instead of fabricating detailed Minecraft farm/redstone instructions.
- Add recent Minecraft event observation support for advancement and other player events.
- Use player-friendly wording for read-only capability explanations and avoid exposing slash-command implementation details unless the player asks for exact commands.
- Add E2E coverage for the observed regressions: short follow-up answers, memory pollution, home memory scope, shulker farm search/correction, weak search uncertainty, advancement events, and read-only explanation UX.

Deferred:

- Rework the end portal versus stronghold capability boundary. This remains intentionally unchanged in this iteration.
