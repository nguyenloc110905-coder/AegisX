from typing import Protocol

from aegisx_agent.events import Observation


class Collector(Protocol):
    def collect(self) -> Observation | list[Observation]: ...
