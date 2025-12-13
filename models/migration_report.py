import os

from typing import List, Mapping, Optional, NewType
from dataclasses import dataclass, astuple

from .repository import SubmoduleDef

# SubmoduleImportInfoEntry, SubmoduleImportInfo, MigrationImportInfo
# represent data accumulated during migration for reporting purposes.

@dataclass
class SubmoduleImportInfoEntry:
    """Represents which submodule branch applied to which metarepo branch."""
    monorepo_branch: str  # branch name in the new monorepo
    metarepo_branch: str  # what branch was used to import the metarepo files
    submodule_branch: str # what branch was used to import the submodule files
    submodule_nested_submodules: List[SubmoduleDef] # nested submodules in this submodule branch
    
    def __eq__(self, other):
        if not isinstance(other, SubmoduleImportInfoEntry):
            print("Other is not SubmoduleImportInfoEntry")
            return False
        return (self.monorepo_branch == other.monorepo_branch and
                self.metarepo_branch == other.metarepo_branch and
                sorted(self.submodule_nested_submodules) == sorted(other.submodule_nested_submodules))
    
    def __str__(self):
        return f"SubmoduleImportInfoEntry(monorepo_branch={self.monorepo_branch}, metarepo_branch={self.metarepo_branch}, submodule_branch={self.submodule_branch}, nested_submodules={self.submodule_nested_submodules})"


class SubmoduleImportInfo:
    submodule_relative_path: str
    entries: List[SubmoduleImportInfoEntry]
    
    def __init__(self, submodule_relative_path: str):
        self.submodule_relative_path = submodule_relative_path
        self.entries = []
    
    def add_entry(self, monorepo_branch: str, metarepo_branch: str, submodule_branch: str, nested_submodules: Optional[List[SubmoduleDef]] = None):
        self.entries.append(SubmoduleImportInfoEntry(monorepo_branch, metarepo_branch, submodule_branch, nested_submodules or []))
    
    def __str__(self):
        s = f"Submodule Import Info for {self.submodule_relative_path}:\n"

        for entry in self.entries:
            s += f"  - {entry.monorepo_branch}: metarepo branch: {entry.metarepo_branch}, submodule branch: {entry.submodule_branch}\n"
            s += f"    - nested submodules:\n" if len(entry.submodule_nested_submodules) > 0 else ""
            for nested in entry.submodule_nested_submodules:
                s += f"    path: {nested.path}, url: {nested.url}, commit: {nested.commit_hash}\n"
        return s
    
    def __eq__(self, other):
        if not isinstance(other, SubmoduleImportInfo):
            print("Other is not SubmoduleImportInfo")
            return False
        if self.submodule_relative_path != other.submodule_relative_path:
            print(f"Submodule paths differ: {self.submodule_relative_path} != {other.submodule_relative_path}")
            return False
        if len(self.entries) != len(other.entries):
            print(f"Number of entries differ: {len(self.entries)} != {len(other.entries)}")
            return False
        # sort each list prior to comparison
        def key_func(e: SubmoduleImportInfoEntry):
            return (e.metarepo_branch, e.submodule_branch)
        self.entries.sort(key=key_func)
        other.entries.sort(key=key_func)
        for e1, e2 in zip(self.entries, other.entries):
            if e1 != e2:
                print(f"Entries differ:\n{e1}\n{e2}")
                return False
        return True


class MigrationImportInfo:
    submodules_info: Mapping[str, SubmoduleImportInfo]
    
    def __init__(self):
        self.submodules_info = dict()
    
    def add_submodule_entry(self, submodule_relative_path: str, info: SubmoduleImportInfo):
        self.submodules_info[submodule_relative_path] = info
    
    def __str__(self):
        s = "Migration Report:\n"
        for _, info in self.submodules_info.items():
            s += str(info) + "\n"
        return s
    
    def __eq__(self, other):
        if not isinstance(other, MigrationImportInfo):
            print("Other is not MigrationImportInfo")
            return False
        if set(self.submodules_info.keys()) != set(other.submodules_info.keys()):
            print(f"Submodule keys differ: {set(self.submodules_info.keys())} != {set(other.submodules_info.keys())}")
            return False
        for key in self.submodules_info.keys():
            if self.submodules_info[key] != other.submodules_info[key]:
                print(f"Submodule info for {key} differs")
                return False
        return True

RelativePath = NewType('RelativePath', str)
BranchName = NewType('BranchName', str)

@dataclass
class SubmoduleTrackingInfo:
    url: str
    commit_hash: str

@dataclass
class MigrationReportEntry:
    """
    Represents the migration report in a structured format, 
    representing the views needed for creating the monorepo.
    Intended for human-readable reporting purposes.
    """
    metarepo_branch: str
    imported_submodules: Mapping[RelativePath, BranchName]
    tracked_nested_submodules: Mapping[RelativePath, SubmoduleTrackingInfo]

class MigrationReport:
    monorepo_branches: Mapping[BranchName, MigrationReportEntry] = dict()
    
    def __init__(self, report_info: MigrationImportInfo):
        self.entries = []
        for submodule_relative_path, submodule_info in report_info.submodules_info.items():
            for entry in submodule_info.entries:
                monorepo_branch = entry.monorepo_branch
                metarepo_branch = entry.metarepo_branch
                submodule_branch = entry.submodule_branch
                nested_submodules = entry.submodule_nested_submodules

                # add to the appropriate monorepo branch entry
                if not monorepo_branch in self.monorepo_branches:
                    self.monorepo_branches[monorepo_branch] = MigrationReportEntry(
                        metarepo_branch=metarepo_branch,
                        imported_submodules=dict(),
                        tracked_nested_submodules=dict()
                    )
                
                # add the imported submodule
                self.monorepo_branches[monorepo_branch].imported_submodules[submodule_relative_path] = submodule_branch

                # add the tracked nested submodules
                for nested in nested_submodules:
                    nested_relative_path = os.path.join(submodule_relative_path, nested.path)
                    self.monorepo_branches[monorepo_branch].tracked_nested_submodules[nested_relative_path] = SubmoduleTrackingInfo(
                        url=nested.url,
                        commit_hash=nested.commit_hash
                    )
                
    def __str__(self):
        s = "Migration Report:\n"
        for monorepo_branch, entry in self.monorepo_branches.items():
            s += f"\nMonorepo branch: {monorepo_branch}\n"
            s += f"  Imported branches:\n"
            s += f"  - metarepo: {entry.metarepo_branch}\n"
            for submodule_path, submodule_branch in entry.imported_submodules.items():
                s += f"  - {submodule_path}: {submodule_branch}\n"
            s += f"  Tracked nested submodules:\n" if len(entry.tracked_nested_submodules) > 0 else ""
            for nested_path, tracking_info in entry.tracked_nested_submodules.items():
                s += f"  - {nested_path}: url={tracking_info.url}, commit={tracking_info.commit_hash}\n"
        return s
