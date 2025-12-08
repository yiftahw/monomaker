from typing import List
from dataclasses import dataclass
from dataclasses_json import dataclass_json


@dataclass_json
@dataclass
class FileContent:
    filename: str
    content: str
    commit_msg: str


@dataclass_json
@dataclass
class BranchContent:
    name: str
    files: List[FileContent]


@dataclass_json
@dataclass
class RepoContent:
    branches: List[BranchContent]
