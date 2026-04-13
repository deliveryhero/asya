---
title: "x-pause: auto-preserve remaining route.next when actor overwrites with x-pause"
status: open
priority: 2
---

When an actor does `yield "SET", ".route.next", ["x-pause"]`, the remaining actors in route.next are lost. x-pause auto-prepends x-resume (RFC line 138) but doesn't preserve whatever was originally after the current actor.

**Fix**: x-pause should read the original route.next from the persisted envelope (before the actor overwrote it) or the actor should be required to GET+SET. Preferred approach: x-pause handler should merge — if route.next is just `["x-pause"]`, load route.next from the envelope's pre-handler state (available via route.prev reconstruction or a new header). This way actors can simply `yield "SET", ".route.next", ["x-pause"]` without worrying about losing downstream actors.

**Alternative**: document that actors must use GET+SET pattern to preserve the route. But this is error-prone and adds boilerplate.

Discovered during KubeCon slide review — the simple pause pattern shown in talks/docs silently drops the continuation.
