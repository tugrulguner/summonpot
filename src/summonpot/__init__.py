"""summonpot — An API framework where every endpoint is an agent."""

from importlib.metadata import PackageNotFoundError, version

from summonpot.dependencies import Depends, Required
from summonpot.pot import Pot

try:
    __version__ = version("summonpot")
except PackageNotFoundError:
    __version__ = "0.0.0+unknown"

__all__ = ["Depends", "Pot", "Required"]
