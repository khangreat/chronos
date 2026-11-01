"""The single chokepoint for outbound network access.

Every feature that would touch the network MUST call NetworkPolicy.require()
first. Default state is fully offline. This makes the privacy claim operational
rather than merely declared: with network disabled, require() raises and no
request is ever attempted.

There is deliberately no auto-installer here (or anywhere). Optional extras are
installed by the user, never by the app.
"""

from __future__ import annotations

from ..core.config import Settings


class NetworkDisabled(RuntimeError):
    """Raised when a network feature is invoked while networking is off."""


class NetworkPolicy:
    def __init__(self, settings: Settings):
        self.settings = settings

    def _enabled(self, capability: str) -> bool:
        s = self.settings
        # A model on this computer is not "the network": it needs only the AI
        # switch. Anything that leaves the machine goes through the master switch.
        # An app on this computer you asked Chronos to hand items to (Zotero).
        # The caller must refuse any address that isn't this computer.
        if capability == "local_app":
            return True
        if capability == "ai_local":
            return bool(getattr(s, "allow_ai", False))
        if capability == "ai_remote":
            return bool(s.network_enabled and getattr(s, "allow_ai", False)
                        and getattr(s, "allow_ai_remote", False))
        if not s.network_enabled:
            return False
        return {
            "link_check": s.allow_link_check,
            "wayback": s.allow_wayback,
            "page_fetch": s.allow_page_fetch,
            "feeds": s.allow_feeds,
            "archive_submit": getattr(s, "allow_archive_submit", False),
        }.get(capability, False)

    def is_allowed(self, capability: str) -> bool:
        return self._enabled(capability)

    def require(self, capability: str) -> None:
        if capability.startswith("ai_") and not self._enabled(capability):
            raise NetworkDisabled(
                "AI is off. Turn it on in Settings, AI." if capability == "ai_local"
                else "This AI service is on another computer. To use it, turn on "
                     "networking, AI, and \u201cAllow AI services on other computers\u201d "
                     "in Settings.")
        if not self._enabled(capability):
            raise NetworkDisabled(
                f"Network capability '{capability}' is disabled. Enable it in "
                f"settings (network_enabled + allow_{capability}) to use this."
            )
