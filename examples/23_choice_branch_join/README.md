# 23 — Independent branches with one shipping choice

**Current source / unreleased.** Published v0.15.0 rejects this choice-bearing branch/join shape. Use a checkout containing this implementation; installing v0.15.0 alone is insufficient.

The declaration has four application operations:

1. `price_merchandise` calculates the subtotal.
2. `list_shipping` independently calculates application-defined tariffs and removes options that miss the requested delivery window.
3. `apply_shipping` accepts one canonical permitted offer.
4. `combine_quote` joins merchandise and selected shipping into the exact response.

There is no artificial ordering edge between merchandise and offer discovery. These are independent dependency branches, **not parallel execution or conditional branch skipping**. All operations are required. Ready operations run sequentially in declaration-priority order. The agent chooses one argument, not which operations execute, their order, or the final quote.

## Singleton: no model needed

From the repository root, install the locked environment and launch the public command:

```sh
uv sync --locked --all-extras
SUMMONPOT_MODEL=invalid:no-provider uv run --no-sync summonpot serve examples/23_choice_branch_join/app.py
```

Then request a one-day delivery window:

```sh
curl localhost:8000/quotes/shipping-choice -H 'Content-Type: application/json' \
  -d '{"quantity":2,"unit_price_cents":150,"unit_weight_grams":700,"max_delivery_days":1}'
```

Only express is permitted, so the entire graph executes without resolving or constructing a model. The response is:

```json
{"merchandise_cents":300,"shipping_cents":1350,"service":"express","total_cents":1650}
```

The tariffs are local business arithmetic, not live carrier quotes. No charge, reservation, persistence or external carrier service is performed.

## Ambiguity: bounded model choice

Restart with your normally configured provider/model instead of the deliberately invalid value above. Send the same request with `max_delivery_days: 4`. Both standard and express are permitted. The selector sees bounded offer evidence and opaque tokens, with no business-function tools. The fixed goal asks for the lowest-priced offer; local membership validation guarantees a permitted choice, not optimal reasoning by a provider. If standard is selected, the result is:

```json
{"merchandise_cents":300,"shipping_cents":700,"service":"standard","total_cents":1000}
```

The keyless release-smoke fixture derives its token from actual projected evidence and deliberately selects the lowest price. It verifies wiring and canonical response ownership; it is not a live-provider evaluation. The fixture is outside this teaching application.

## Boundaries

- This lesson uses one producer-backed choice and one required single-start sink owning the exact response. The initial source slice admitted exactly one choice globally; the current extension also supports multiple choices (see [example 24](../24_multiple_choice_branch_join/README.md)). Existing linear compatibility is unchanged.
- Quantity must be 1–100 and the delivery window 1–4 days; invalid requests reject with HTTP 422 before selection.
- There is no global choice barrier. Declaration order breaks readiness ties, and explicit `after` edges express required business ordering. Earlier effects may remain after a later failure; this example itself performs calculations only.
- Explicit function-tool quotas reject this new shape before operation/model starts; the decision-only selector does not report business tool calls. Private `allow_direct=False` compilation also rejects the new graph rather than falling back to unchecked scheduling.
- One request-local context, ledger, usage policy and deadline span execution. No graph repetition, checkpoint/feedback, public graph API, parallel scheduling, rollback or durable resumption is added.

Compare [resolved branches and joins](../20_branch_join/README.md), [multiple choices in a linear chain](../13_multiple_producer_choices/README.md), and the [example progression](../README.md).
