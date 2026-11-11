"""Version 0.15.0 lesson 21: stateless, model-backed HTTP transport echoes.

These declarations do not persist, update, or delete resources. A configured provider
is needed for ordinary use. The tests and release smoke use a separate keyless
FunctionModel fixture that copies the actual SDK request values.
"""

from pydantic import BaseModel

from summonpot import Summon


class PathEcho(BaseModel):
    item_id: int


class TextEcho(PathEcho):
    text: str


summon = Summon("path-method-transport")


@summon("/transport/{item_id}", method="GET")
def read_transport(item_id: int, text: str) -> TextEcho:
    """Echo the URL item_id and query text exactly; do not access any resource."""
    ...


@summon("/transport/{item_id}", method="POST")
def post_transport(item_id: int, text: str) -> TextEcho:
    """Echo the URL item_id and JSON text exactly; do not create any resource."""
    ...


@summon("/transport/{item_id}", method="PUT")
def put_transport(item_id: int, text: str) -> TextEcho:
    """Echo the URL item_id and JSON text exactly; do not replace any resource."""
    ...


@summon("/transport/{item_id}", method="PATCH")
def patch_transport(item_id: int, text: str) -> TextEcho:
    """Echo the URL item_id and JSON text exactly; do not modify any resource."""
    ...


@summon("/transport/{item_id}", method="DELETE")
def delete_transport(item_id: int) -> PathEcho:
    """Echo the URL item_id exactly; do not delete any resource."""
    ...


@summon("/transport/{item_id}", method="HEAD")
def head_transport(item_id: int) -> PathEcho:
    """Echo the URL item_id internally; HTTP HEAD sends no response body."""
    ...


if __name__ == "__main__":
    summon.serve(host="127.0.0.1", port=8000)
