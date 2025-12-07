from dataclasses import dataclass
from dataclasses_json import dataclass_json


@dataclass_json
@dataclass
class RepositoryReportEntry:
    url: str
    branches: list[str]


@dataclass_json
@dataclass
class RepositoryReport:
    repositories: list[RepositoryReportEntry]
