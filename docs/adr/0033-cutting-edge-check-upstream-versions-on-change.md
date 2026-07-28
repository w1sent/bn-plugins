# Check for new upstream dependency versions whenever changing a plugin

Pinning dependencies (ADR-0032) trades staleness for stability, which only
stays a good trade if the pins get revisited regularly rather than frozen
indefinitely. Rather than a separate update sweep, fold the check into normal
work: whenever a plugin's code is being changed for any reason, check whether
its pinned third-party dependencies have a newer version available, and
whether upgrading is worth doing as part of that change (or as a clearly
separated follow-up commit if it's more than a version-bump-in-place).

This keeps the project close to upstream without taking on same-day-release
risk -- a plugin that isn't being touched keeps its working pin, but one
that's actively being worked on doesn't drift further out of date each time.
`ai/mcp-server`'s `mcp<2.0` pin (ADR-0032) is the first case: recorded as an
open migration in its README rather than actioned immediately, since 2.0.0
shipped the same day it was discovered and hasn't had time to stabilize --
the next time `ai/mcp-server` is changed for another reason, check whether
that's changed.
