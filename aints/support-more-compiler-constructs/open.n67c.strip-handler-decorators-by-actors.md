---
title: Strip handler decorators by actors
priority: 2 # medium
---

See [1mhs] - it supports custom decorators `@actor`.
See [1fmi] - it wants to support tenacity `@retry`.

We need to understand whether asya should delete all decorators and call handlers as plain functions, or some decorators might be useful (e.g. user-defined adapter decorators, see `docs/tutorials/actor-handler-adapter-pattern.md`).
