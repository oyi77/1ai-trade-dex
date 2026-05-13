import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import List, Optional

logger = logging.getLogger(__name__)


@dataclass
class NotificationManifest:
    name: str = ""
    display_name: str = ""
    version: str = "1.0.0"
    required_env_vars: List[str] = field(default_factory=list)
    tags: List[str] = field(default_factory=list)


class BaseNotificationProvider(ABC):
    @classmethod
    @abstractmethod
    def manifest(cls) -> NotificationManifest:
        ...

    @abstractmethod
    async def send(self, message: str, event_type: str, details: Optional[dict] = None) -> bool:
        ...

    async def health_check(self) -> bool:
        return True

    async def teardown(self) -> None:
        pass
