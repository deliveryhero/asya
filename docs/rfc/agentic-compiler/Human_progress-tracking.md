Summary: What Was Created

RFC Document

docs/rfc/agentic-compiler/agentic-compiler-rfc.md (~950 lines) covering:
- CPS transformation design (how await becomes actor boundaries)
- New IR node types: AwaitCall, WhileLoop, YieldEvent, AsyncFlowFunction
- Parser, Grouper, CodeGen extensions
- Validated ADK LLM Auditor example with full execution trace
- Two compilation levels (orchestration + agent decomposition)
- Testing strategy with 5 realistic test cases based on real ADK samples
- Runtime and sidecar streaming protocol extensions

Epic

asya-4ozl — Epic: Agentic Flow Compiler (P1), child of asya-bi8 (Agentic Asya)

Beads (12 total under the epic)
┌───────────┬──────────┬─────────────────────────────────────────────────┬────────────────┐
│    ID     │ Priority │                      Title                      │   Blocked by   │
├───────────┼──────────┼─────────────────────────────────────────────────┼────────────────┤
│ asya-pec  │ WIP       │ Flow DSL: async/await handlers (updated)        │ -              │
├───────────┼──────────┼─────────────────────────────────────────────────┼────────────────┤
│ asya-bp6  │ DONE - PR163 │ Flow DSL: for/while loops (updated)             │ -              │
├───────────┼──────────┼─────────────────────────────────────────────────┼────────────────┤
│ asya-ajeq │ WIP       │ Runtime: async handler execution (asyncio.run)  │ -              │
├───────────┼──────────┼─────────────────────────────────────────────────┼────────────────┤
│ asya-qrsp │ P1       │ Sidecar: multi-frame streaming protocol         │ -              │
├───────────┼──────────┼─────────────────────────────────────────────────┼────────────────┤
│ asya-fudp │ P1       │ Test: async flow example fixtures (ADK-based)   │ -              │
├───────────┼──────────┼─────────────────────────────────────────────────┼────────────────┤
│ asya-cx34 │ P1       │ Runtime: AsyncGenerator multi-frame response    │ ajeq, qrsp     │
├───────────┼──────────┼─────────────────────────────────────────────────┼────────────────┤
│ asya-yfv1 │ P1       │ Test: ADK LLM Auditor compilation test          │ pec, bp6, fudp │
├───────────┼──────────┼─────────────────────────────────────────────────┼────────────────┤
│ asya-asp7 │ P2       │ DotGen: loop and async visualization            │ pec, bp6       │
├───────────┼──────────┼─────────────────────────────────────────────────┼────────────────┤
│ asya-mhuz │ P2       │ Compiler: max_iterations guard                  │ bp6            │
├───────────┼──────────┼─────────────────────────────────────────────────┼────────────────┤
│ asya-n5mc │ P2       │ Sidecar: HTTP streaming to gateway              │ qrsp           │
├───────────┼──────────┼─────────────────────────────────────────────────┼────────────────┤
│ asya-ync  │ P2       │ Flow DSL: try-catch blocks (existing)           │ -              │
├───────────┼──────────┼─────────────────────────────────────────────────┼────────────────┤
│ asya-cv4g │ P3       │ Free variable detection across await boundaries │ pec            │
└───────────┴──────────┴─────────────────────────────────────────────────┴────────────────┘
Updated/Closed Beads

- asya-pec: Updated with CPS transformation details, promoted to P1
- asya-bp6: Updated with back-edge router generation, promoted to P1
- asya-ugj: Closed (superseded by asya-4ozl decomposition)
