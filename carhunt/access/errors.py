"""Access-layer exceptions shared by sites, contact and discover."""


class AccessError(Exception):
    """Base class for access-layer failures."""


class Blocked(AccessError):
    """A site answered with a bot wall / ban instead of content.

    `signature` names the wall (e.g. "datadome-slider", "imperva", "http-403") so callers
    can stop at the first block and the skill's escalation ladder can pick the next rung.
    """

    def __init__(self, signature: str, *, site: str | None = None, url: str | None = None, detail: str = ""):
        self.signature = signature
        self.site = site
        self.url = url
        self.detail = detail
        where = f" on {site}" if site else ""
        super().__init__(f"blocked{where}: {signature}" + (f" ({detail})" if detail else ""))


class PaceExceeded(AccessError):
    """The shared pace ledger or a day cap refused the action. `retry_at` is a datetime or None (cap)."""

    def __init__(self, site: str, kind: str, *, retry_at=None, reason: str = ""):
        self.site, self.kind, self.retry_at, self.reason = site, kind, retry_at, reason
        when = f", retry at {retry_at.isoformat(timespec='seconds')}" if retry_at else ""
        super().__init__(f"pace exceeded for {site}/{kind}: {reason}{when}")


class ProxyUnavailable(AccessError):
    """No proxy, or the exit IP failed verification. Fail closed: no request was sent through it."""


class LeaseBusy(AccessError):
    """A single-holder resource (identity copy, geo browser) is held by someone else."""
