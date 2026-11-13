# 24 — Independent shipping and packaging choices

**Current source / unreleased.** Use a checkout containing this extension. Published v0.15.0 cannot execute this declaration; the earlier one-choice graph slice alone is also insufficient.

Five real application operations calculate allowed tariffs, accept a canonical shipping option, independently calculate packaging options, accept one canonical packaging option, and combine the exact quote. There is no artificial `after` edge from shipping to packaging discovery. The local tariffs are arithmetic, not live carrier services, inventory, charges or reservations.

Every operation is required and executes sequentially. Declaration priority breaks readiness ties; the agent selects argument values, not branches, execution order or the final response. Two different consumers have separate decision frontiers. Multiple ambiguous arguments on one consumer are instead selected together; see the operation reference for that distinction.

## No model: both domains are singleton

From the repository root:

```sh
uv sync --locked --all-extras
SUMMONPOT_MODEL=invalid:no-provider uv run --no-sync summonpot serve examples/24_multiple_choice_branch_join/app.py
```

```sh
curl localhost:8000/quotes/fulfillment -H 'Content-Type: application/json' \
  -d '{"units":2,"goods_cents":1000,"rush":true,"protective":true}'
```

The only permitted options are express shipping and protective packaging:

```json
{"shipping":"express","packaging":"protective","total_cents":2060}
```

Neither a model lookup nor a selector request is needed. Running the file directly also starts the same application.

## Ambiguous choices

Restart with your configured provider instead of the deliberately invalid model. With `rush:false` and `protective:false`, each consumer has two candidates. Each selector sees only its current bounded candidate evidence and opaque tokens, without business-function tools. If both lowest-price options are selected, the response is:

```json
{"shipping":"standard","packaging":"lightweight","total_cents":1480}
```

The fixed goal requests lowest price; local membership enforcement guarantees an allowed option, not provider optimality. The smoke verifier uses a separate keyless FunctionModel that actually reads projected prices and selects the minimum token. That fixture proves framework plumbing, not live-provider reasoning.

## Boundaries

- One request, principal, ledger, usage policy and deadline span both frontiers. Limits do not reset after shipping. Earlier effects could remain after a later unavailable domain, provider error or timeout; this example calculates only.
- There is no global choice barrier or batching across consumers. All current domains at one consumer are checked before its selector or application call.
- Explicit function-tool quotas reject the non-linear shape before work; private `allow_direct=False` compilation rejects it rather than changing scheduling. Existing linear-chain compatibility is unchanged.
- No optional/conditional branches, parallel execution, repetition/checkpoint graphs, rollback, recovery, new graph API or caller-selected mode is added.

Compare [one choice in independent branches](../23_choice_branch_join/README.md) and [multiple choices in a linear chain](../13_multiple_producer_choices/README.md).
