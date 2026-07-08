from __future__ import annotations

from dataclasses import asdict, dataclass

KINDS = ("chat", "cowork", "code", "tmux")
PROFILES = ("work", "personal")


@dataclass(frozen=True)
class Surface:
    name: str
    kind: str
    address: str
    digest: str
    profile: str
    registered_at: str

    def __post_init__(self) -> None:
        if self.kind not in KINDS:
            raise ValueError(f"unknown surface kind: {self.kind!r}")
        if self.profile not in PROFILES:
            raise ValueError(f"unknown profile: {self.profile!r}")

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "Surface":
        return cls(**data)
