"""ApplicationContext — a small service registry / composition root.

Wires Config -> Storage -> services -> network policy in one place, so nothing
else constructs its own dependencies (the god-object antidote). The GUI, the
CLI, and the tests all build the same context; only the paths differ.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from .config import Config, Settings
from .storage import Storage
from ..net.policy import NetworkPolicy


class ApplicationContext:
    def __init__(self, config: Optional[Config] = None):
        self.config = config or Config()
        self.config.ensure_dirs()
        self.storage = Storage(self.config.db_path)
        self.network = NetworkPolicy(self.config.settings)
        # Lazily constructed services (import here to avoid import cycles).
        self._bookmark_service = None
        self._search_service = None
        self._stats_service = None
        self._content_service = None

    @property
    def bookmarks(self):
        if self._bookmark_service is None:
            from ..services.bookmark_service import BookmarkService
            self._bookmark_service = BookmarkService(self.storage)
        return self._bookmark_service

    @property
    def search(self):
        if self._search_service is None:
            from ..search.search_service import SearchService
            self._search_service = SearchService(self.storage)
        return self._search_service

    @property
    def stats(self):
        if self._stats_service is None:
            from ..services.stats_service import StatsService
            self._stats_service = StatsService(self.storage)
        return self._stats_service

    @property
    def content(self):
        if self._content_service is None:
            from ..web.content_service import ContentService
            self._content_service = ContentService(self.storage, self.network)
        return self._content_service

    @property
    def feeds(self):
        if getattr(self, "_feed_service", None) is None:
            from ..feeds.feed_service import FeedService
            self._feed_service = FeedService(self.storage, self.network)
        return self._feed_service

    @property
    def links(self):
        if getattr(self, "_link_service", None) is None:
            from ..web.link_service import LinkService
            self._link_service = LinkService(self.storage, self.network)
        return self._link_service

    @property
    def archive(self):
        if getattr(self, "_archive_service", None) is None:
            from ..web.archive_service import ArchiveService
            self._archive_service = ArchiveService(self)
        return self._archive_service

    @property
    def removal(self):
        if getattr(self, "_removal_service", None) is None:
            from ..services.removal_service import RemovalService
            self._removal_service = RemovalService(self)
        return self._removal_service

    @property
    def tagging(self):
        if getattr(self, "_tagging_service", None) is None:
            from ..services.tagging_service import AutoTagger
            self._tagging_service = AutoTagger(self)
        return self._tagging_service

    @property
    def provenance(self):
        if getattr(self, "_provenance_service", None) is None:
            from ..services.provenance_service import ProvenanceService
            self._provenance_service = ProvenanceService(self)
        return self._provenance_service

    @property
    def platform_import(self):
        if getattr(self, "_platform_import_service", None) is None:
            from ..services.platform_import import PlatformImportService
            self._platform_import_service = PlatformImportService(self)
        return self._platform_import_service

    @property
    def resources(self):
        if getattr(self, "_resource_service", None) is None:
            from ..services.resource_service import ResourceService
            self._resource_service = ResourceService(self)
        return self._resource_service

    @property
    def capture(self):
        if getattr(self, "_capture_service", None) is None:
            from ..services.capture_service import CaptureService
            self._capture_service = CaptureService(self)
        return self._capture_service

    @property
    def takeout(self):
        if getattr(self, "_takeout_service", None) is None:
            from ..services.takeout_service import TakeoutService
            self._takeout_service = TakeoutService(self)
        return self._takeout_service

    @property
    def takeaways(self):
        if getattr(self, "_takeaway_service", None) is None:
            from ..services.takeaway_service import TakeawayService
            self._takeaway_service = TakeawayService(self)
        return self._takeaway_service

    @property
    def videos(self):
        if getattr(self, "_video_service", None) is None:
            from ..services.video_service import VideoService
            self._video_service = VideoService(self)
        return self._video_service

    @property
    def related(self):
        if getattr(self, "_related_service", None) is None:
            from ..services.similarity import RelatedService
            self._related_service = RelatedService(self)
        return self._related_service

    @property
    def snippets(self):
        if getattr(self, "_snippet_service", None) is None:
            from ..services.snippet_service import SnippetService
            self._snippet_service = SnippetService(self.storage)
        return self._snippet_service

    @property
    def export(self):
        if getattr(self, "_export_service", None) is None:
            from ..services.export_service import ExportService
            self._export_service = ExportService(self)
        return self._export_service

    @property
    def curation(self):
        if getattr(self, "_curation_service", None) is None:
            from ..services.curation_service import CurationService
            self._curation_service = CurationService(self.storage)
        return self._curation_service

    def provider(self):
        """Return the interop provider other apps (CC/Nawishtar/ytman) consume."""
        from ..interop import ChronosProvider
        return ChronosProvider(self)

    def close(self) -> None:
        self.storage.close()

    def __enter__(self) -> "ApplicationContext":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    @classmethod
    def for_dir(cls, app_dir: Path) -> "ApplicationContext":
        return cls(Config(app_dir))
