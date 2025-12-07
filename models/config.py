from dataclasses import dataclass
from dataclasses_json import dataclass_json
from typing import Optional


@dataclass_json
@dataclass
class RepoConfig:
    path: str
    url: str


@dataclass_json
@dataclass
class Config:
    monorepo_name: str
    repositories: list[RepoConfig]
    monorepo_url: Optional[str] = None
