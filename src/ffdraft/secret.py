"""Secret handling.

`docs/SECURITY_LICENSE.md` section 2 and ADR-017 require that a provisioned secret never
reaches a log line, a cache key, a URL query, a committed fixture or a serialized artifact.
Python makes that easy to get wrong: the default ``repr`` of any container holding a plain
string prints the string, and one stray f-string in an error path is enough to leak it.

:class:`Secret` closes that hole by construction. The value is reachable only through an
explicit :meth:`Secret.reveal` call, ``repr``/``str`` show provenance rather than content,
and the object is not JSON-serialisable, so ``json.dumps`` raises instead of publishing.
"""

from __future__ import annotations

from collections.abc import Mapping

__all__ = ["Secret", "secret_from_env"]


class Secret:
    """A string value that must not be printed, logged or serialized.

    ``env_var`` is the name of the environment variable the value came from. Names are not
    sensitive - they are recorded in `config/source-registry.yaml` on purpose - so they are
    safe to show in diagnostics, and they make a missing-secret failure legible.
    """

    __slots__ = ("_value", "env_var")

    def __init__(self, value: str, *, env_var: str) -> None:
        if not value:
            raise ValueError(f"refusing to build an empty Secret from {env_var}")
        self._value = value
        self.env_var = env_var

    def reveal(self) -> str:
        """Return the raw value. Call this only at the point of use."""
        return self._value

    def __repr__(self) -> str:
        return f"Secret(env_var={self.env_var!r}, present=True)"

    __str__ = __repr__

    def __eq__(self, other: object) -> bool:
        # Comparison by identity of provenance, never by value: an equality check that
        # compared contents would let a caller brute-force the value one guess at a time.
        return isinstance(other, Secret) and other.env_var == self.env_var

    def __hash__(self) -> int:
        return hash(("Secret", self.env_var))


def secret_from_env(env_var: str, environ: Mapping[str, str]) -> Secret | None:
    """Read ``env_var`` from ``environ``. Missing or blank yields ``None``, never an error.

    A secret that is absent is a normal state here: local development, forked-PR CI and
    every network-free test run have none, and ADR-017 requires degradation rather than
    failure on the unauthenticated MFL path.
    """
    raw = environ.get(env_var, "").strip()
    if not raw:
        return None
    return Secret(raw, env_var=env_var)
