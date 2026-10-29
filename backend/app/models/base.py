from pydantic import BaseModel, ConfigDict


class DomainModel(BaseModel):
    """Base class for all domain models.

    `extra="forbid"` makes typos in the YAML data files and in API payloads fail loudly
    instead of being silently ignored.
    """

    model_config = ConfigDict(extra="forbid")
