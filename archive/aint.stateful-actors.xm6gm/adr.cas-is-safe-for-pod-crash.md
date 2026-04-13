
CAS + Pod Crash: Is State Safe?

Short answer: yes, by design. CAS (Compare-And-Swap) is specifically built for this:

- Crash before CAS write → no state change, message gets redelivered, retry reads same state
- Crash during CAS write → the write either succeeds or fails atomically (that's the entire point of CAS)
- Crash after CAS write but before message ack → message redelivered, but CAS detects version conflict on retry. Handler gets a
conflict error and must handle it (which is already the contract for CAS-using actors)

The concern isn't timeout-specific — it's the general retry-after-crash story, which CAS handles correctly. The only risk would be if a handler does multiple CAS writes in sequence (non-atomic multi-key update), where a crash between writes leaves partial state.
