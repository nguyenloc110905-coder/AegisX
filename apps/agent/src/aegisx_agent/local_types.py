from enum import StrEnum


class EventPriority(StrEnum):
    BULK = "BULK"
    OPERATIONAL = "OPERATIONAL"
    SECURITY = "SECURITY"
    UNCLASSIFIED = "UNCLASSIFIED"


class DeliveryState(StrEnum):
    PENDING = "PENDING"
    ACKED = "ACKED"
    QUARANTINED = "QUARANTINED"
