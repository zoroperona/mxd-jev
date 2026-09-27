from __future__ import annotations

from dataclasses import asdict, dataclass, field


@dataclass
class Detection:
    x: float
    y: float
    w: float
    h: float
    confidence: float

    @property
    def center(self) -> tuple[float, float]:
        return self.x + self.w / 2, self.y + self.h / 2


@dataclass
class Observation:
    frame_id: int
    timestamp: float
    player: tuple[float, float] | None = None
    monsters: list[Detection] = field(default_factory=list)
    hp: float | None = None
    mp: float | None = None
    minimap: tuple[float, float] | None = None
    valid: bool = False
    reason: str = "not_calibrated"

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Decision:
    action: str
    reason: str
    source: str = "rules"
    confidence: float | None = None
    probabilities: dict[str, float] | None = None
