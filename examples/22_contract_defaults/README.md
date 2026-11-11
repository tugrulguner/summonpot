# 22 — Callable defaults and annotated contracts

Version 0.15.0 output inference lesson. The operation infers the
full `QuoteOutput` annotation from its callable. For v0.14.0
compatibility, explicitly declare `output=QuoteOutput` on the operation.

```sh
SUMMONPOT_MODEL=invalid:no-provider uv run summonpot serve examples/22_contract_defaults/app.py
curl localhost:8000/quotes/defaults -H 'Content-Type: application/json' -d '{"unit_price_cents":199,"quantity":3}'
```

The response is `{"subtotal_cents":597,"discount_cents":29,"total_cents":568}`.
Discount cents round down using integer arithmetic. The immutable
`discount_percent=5` belongs to the application callable: it is omitted from
`bind`, is not an implicit request binding, and cannot be supplied by a model.
The request forbids extra fields, so a caller-supplied discount is rejected.

The request accepts quantities 1–100; this quote operation accepts only 1–10.
Sending quantity 11 returns HTTP 422 for the receiving operation contract,
before the callable starts. This is contract validation, not a business failure
route. The accepted path executes directly, even with the invalid model above.
The callable return and endpoint response share the exact full Annotated
contract, including its description metadata.
