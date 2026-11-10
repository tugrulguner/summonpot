# 21 — Path values and HTTP methods

Current-source lesson. Run from this checkout with its installed extras:

```sh
uv run summonpot serve examples/21_path_methods/app.py
```

Configure a provider model for ordinary use. These scalar declarations remain
model-backed; they do not qualify for direct execution. Their goal is to echo
transport data. There is no storage, CRUD behavior, or business success receipt.

All six methods share the OpenAPI template `/transport/{item_id}`.
The URL owns the integer `item_id`. GET takes required `text` from the query;
POST, PUT, and PATCH take it from JSON. DELETE and HEAD need only the URL.
A JSON `item_id` cannot override the URL value. HEAD executes its declaration
but returns an empty HTTP body.

```sh
curl 'localhost:8000/transport/7?text=hello'
curl -X POST localhost:8000/transport/7 -H 'Content-Type: application/json' -d '{"text":"hello","item_id":999}'
curl -X PUT localhost:8000/transport/7 -H 'Content-Type: application/json' -d '{"text":"replacement description"}'
curl -X PATCH localhost:8000/transport/7 -H 'Content-Type: application/json' -d '{"text":"patch description"}'
curl -X DELETE localhost:8000/transport/7
curl -I localhost:8000/transport/7
curl localhost:8000/openapi.json
```

The focused tests and release smoke use a separate keyless FunctionModel fixture.
It derives echoes from validated values actually emitted in SDK request messages.
This tests HTTP plumbing without claiming live-provider output quality.
