"""Statistical defaults used to reconstruct missing answers (brief section 8).

One `AreaDefaults` per residential context. The demand estimator looks values up by
`AreaDefaults.values[key]`; the keys it relies on are listed in
`app.data.loader.REQUIRED_DEFAULT_KEYS`. Each value is a `Param`, so it carries range,
confidence, source and placeholder flag like every other number of the model.
"""

from .base import DomainModel
from .enums import AreaType
from .provenance import Param


class AreaDefaults(DomainModel):
    id: str
    area_type: AreaType
    description: str | None = None
    values: dict[str, Param]
