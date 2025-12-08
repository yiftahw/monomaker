from typing import Optional
from dataclasses import dataclass
from dataclasses_json import dataclass_json

@dataclass_json
@dataclass
class RepoConfig:
    path: str
    url: str


@dataclass_json
@dataclass
class Config:
    destination: Optional[RepoConfig]
    metarepo: RepoConfig
    repositories: list[RepoConfig]
