#!/usr/bin/env python3

import unittest
import tempfile
import shutil
import os
from pprint import pprint, PrettyPrinter
import io
import json

from utils import exec_cmd, listdir_list, pretty_print_list, header_string
import git_test_ops
from models.repository import FileContent, BranchContent, RepoContent
import merger

with open("debug.log", "w") as f:
    f.write("Debug Log\n")

def debug_log(message: str):
    with open("debug.log", "a") as f:
        f.write(message + "\n")

def create_and_fill_branch(repo_path: str, branch_content: BranchContent, branch_name: str, default_branch: str):
    """Create a branch and fill it with files as per RepoContent."""
    # switch to the default branch first, to branch off it
    git_test_ops.switch_branch(repo_path, default_branch)
    git_test_ops.create_or_switch_to_branch(repo_path, branch_name)
    # get the branch content
    for file in branch_content.files:
        git_test_ops.commit_file(repo_path, file.filename, file.content, file.commit_msg)

def create_temporary_repo(content: RepoContent) -> str:
    """Creates a temporary repository and returns its path."""
    tempdir = tempfile.mkdtemp()
    git_test_ops.create_repo(tempdir, content.default_branch)
    # start with creating the default branch first
    default_branch_content = next((b for b in content.branches if b.name == content.default_branch), None)
    if default_branch_content is not None:
        create_and_fill_branch(tempdir, default_branch_content, content.default_branch, content.default_branch)
    # create other branches
    for branch in content.branches:
        if branch.name == content.default_branch:
            continue  # already created
        create_and_fill_branch(tempdir, branch, branch.name, content.default_branch)
    git_test_ops.switch_branch(tempdir, content.default_branch)
    return tempdir


def create_repo_content() -> RepoContent:
    return RepoContent(
        default_branch="main",
        branches=[
            BranchContent(
                name="main",
                files=[
                    FileContent(
                        filename="file1.txt",
                        content="Hello, World!",
                        commit_msg="Add file1.txt"
                    ),
                    FileContent(
                        filename="file2.txt",
                        content="This is a test.",
                        commit_msg="Add file2.txt"
                    )
                ]
            ),
            BranchContent(
                name="feature",
                files=[
                    FileContent(
                        filename="feature.txt",
                        content="Feature branch file.",
                        commit_msg="Add feature.txt"
                    )
                ]
            ),
            BranchContent(
                name="foo",
                files=[
                    FileContent(
                        filename="foo.txt",
                        content="foo branch file.",
                        commit_msg="Add foo.txt"
                    )
                ]
            )
        ]
    )

def create_submodule_content() -> RepoContent:
    return RepoContent(
        default_branch="main",
        branches=[
            BranchContent(
                name="main",
                files=[
                    FileContent(
                        filename="subfile.txt",
                        content="Submodule file content.",
                        commit_msg="Add subfile.txt"
                    )
                ]
            ),
            BranchContent(
                name="dev",
                files=[
                    FileContent(
                        filename="devfile.txt",
                        content="Dev branch file in submodule.",
                        commit_msg="Add devfile.txt"
                    )
                ]
            ),
            # although both metarepo and submodule have "feature" branch,
            # the metarepo "feature" branch will not track the submodule's "feature" branch
            # hence it will not be imported into the monorepo (but the monorepo will have the metarepo "feature" branch content)
            BranchContent(
                name="feature",
                files=[
                    FileContent(
                        filename="barsub.txt",
                        content="bar branch file in submodule.",
                        commit_msg="Add barsub.txt"
                    )
                ]
            )
        ]
    )

class TestGitOps(unittest.TestCase):
    repo_content: RepoContent
    repo_path: str
    submodule_a_path: str
    submodule_a_content: RepoContent
    submodule_relative_path: str = "submodule_a"
    nested_submodule_path: str
    nested_submodule_content: RepoContent
    nested_submodule_relative_path: str = "nested_submodule"

    def check_file_content(self, repo_path: str, filename: str, expected_content: str) -> bool:
        file_path = os.path.join(repo_path, filename)
        if not os.path.isfile(file_path):
            debug_log(f"File {file_path} does not exist.")
            debug_log(f"Current directory listing: {pretty_print_list(listdir_list(repo_path))}")
            return False
        with open(file_path, "r") as f:
            content = f.read()
        if not content == expected_content:
            debug_log(f"File {file_path} content mismatch.\nExpected:\n{expected_content}\nGot:\n{content}")
            return False
        return True

    def assertSubmoduleImport(self, monorepo_path: str, submodule_relative_path: str, 
                                expected_branches: set, submodule_content: RepoContent):
        """Verify that submodule branches and files were correctly imported into monorepo."""
        # verify expected submodule branches were imported
        monorepo_branches = set(merger.get_all_branches(monorepo_path))
        self.assertTrue(expected_branches.issubset(monorepo_branches), f"Expected branches {expected_branches} not all found in monorepo branches {monorepo_branches}")
        
        # verify files were imported, and their content is correct
        for branch in submodule_content.branches:
            if branch.name not in expected_branches:
                continue
            # we switch branches in the main repo, submodule files should now exist in it
            git_test_ops.switch_branch(monorepo_path, branch.name)
            submodule_files = set([file.filename for file in branch.files])
            imported_files = set(os.listdir(os.path.join(monorepo_path, submodule_relative_path)))
            self.assertTrue(submodule_files.issubset(imported_files), f"Expected files {submodule_files} not all found in imported files {imported_files} for branch {branch.name}, expected branches: {expected_branches}")
            for file in branch.files:
                self.assertTrue(self.check_file_content(os.path.join(monorepo_path, submodule_relative_path), file.filename, file.content))
    
    def assertNestedSubmoduleTracking(self, monorepo_default_branch: str):
        # verify nested submodule is tracked correctly in the monorepo
        # <root>/submodule_a/nested_submodule default branch should be a direct submodule of the monorepo default branch
        
        # verify we are tracking exactly 1 nested submodule
        git_test_ops.switch_branch(self.monorepo_path, monorepo_default_branch)
        submodules_in_monorepo = merger.get_all_submodules(self.monorepo_path)
        self.assertEqual(1, len(submodules_in_monorepo))
        nested_submodule_in_monorepo = submodules_in_monorepo[0]
        
        expected_path = os.path.join(self.submodule_relative_path, self.nested_submodule_relative_path)
        self.assertEqual(nested_submodule_in_monorepo.path, expected_path)
        
        original_commit_hash = git_test_ops.get_commit_hash(self.nested_submodule_path, self.nested_submodule_content.default_branch)
        current_commit_hash = git_test_ops.get_submodule_commit_hash(self.monorepo_path, expected_path)
        imported_commit_hash = nested_submodule_in_monorepo.commit_hash
        self.assertEqual(original_commit_hash, current_commit_hash)
        self.assertEqual(original_commit_hash, imported_commit_hash)

    def allow_git_file_protocol(self):
        self.old_file_allow_value = exec_cmd('git config --global --get protocol.file.allow || echo ""', verbose=False).stdout.strip()
        self.old_file_allow_value = None if self.old_file_allow_value == "" else self.old_file_allow_value
        exec_cmd('git config --global protocol.file.allow always')

    def cleanup_git_file_protocol(self):
        if self.old_file_allow_value is None:
            exec_cmd('git config --global --unset protocol.file.allow', verbose=False)
        else:
            exec_cmd(f'git config --global protocol.file.allow {self.old_file_allow_value}', verbose=False)

    def setUp(self):
        self.allow_git_file_protocol()
        self.repo_content = create_repo_content()
        self.repo_path = create_temporary_repo(self.repo_content)
        self.submodule_a_content = create_submodule_content()
        self.submodule_a_path = create_temporary_repo(self.submodule_a_content)
        self.nested_submodule_content = create_submodule_content()
        self.nested_submodule_path = create_temporary_repo(self.nested_submodule_content)
        self.monorepo_path = create_temporary_repo(RepoContent(default_branch="main", branches=[]))
        # register the submodule in the metarepo under default branch
        git_test_ops.add_local_submodule(
            self.repo_path,
            self.repo_content.default_branch,
            self.submodule_a_path,
            self.submodule_relative_path,
            self.submodule_a_content.default_branch
        )
        # register the submodule in the metarepo under "foo" branch
        git_test_ops.add_local_submodule(
            self.repo_path,
            "foo",
            self.submodule_a_path,
            self.submodule_relative_path,
            self.submodule_a_content.default_branch
        )
        # register nested submodule in submodule_a under default branch
        git_test_ops.add_local_submodule(
            self.submodule_a_path,
            self.submodule_a_content.default_branch,
            self.nested_submodule_path,
            self.nested_submodule_relative_path,
            self.nested_submodule_content.default_branch
        )
        # make sure we switch back to default branch (HEAD is just whatever we point to now)
        git_test_ops.switch_branch(self.repo_path, self.repo_content.default_branch)
        git_test_ops.switch_branch(self.submodule_a_path, self.submodule_a_content.default_branch)
        git_test_ops.switch_branch(self.nested_submodule_path, self.nested_submodule_content.default_branch)
        self.nested_submodule_url = git_test_ops.repo_url(self.nested_submodule_path)
        self.nested_submodule_default_branch_commit_hash = git_test_ops.get_commit_hash(self.nested_submodule_path, self.nested_submodule_content.default_branch)
        print(header_string("Setup complete"))

    def tearDown(self):
        shutil.rmtree(self.monorepo_path)
        shutil.rmtree(self.repo_path)
        shutil.rmtree(self.submodule_a_path)
        shutil.rmtree(self.nested_submodule_path)
        self.cleanup_git_file_protocol()

    def test_repo_creation(self):
        # Verify main branch files
        for branch in self.repo_content.branches:
            git_test_ops.switch_branch(self.repo_path, branch.name)
            for file in branch.files:
                self.assertTrue(self.check_file_content(self.repo_path, file.filename, file.content))

    def test_submodule_integration(self):
        git_test_ops.switch_branch(self.repo_path, "main")
        submodule_path = os.path.join(self.repo_path, self.submodule_relative_path)
        self.assertTrue(os.path.isdir(submodule_path))
        for branch in self.submodule_a_content.branches:
            git_test_ops.switch_branch(submodule_path, branch.name)
            for file in branch.files:
                self.assertTrue(self.check_file_content(submodule_path, file.filename, file.content))

    def test_merger_get_all_branches(self):
        branches = set(merger.get_all_branches(self.repo_path))
        expected_branches = set([branch.name for branch in self.repo_content.branches])
        self.assertCountEqual(branches, expected_branches)

        submodule_branches = set(merger.get_all_branches(self.submodule_a_path))
        expected_submodule_branches = set([branch.name for branch in self.submodule_a_content.branches])
        self.assertCountEqual(submodule_branches, expected_submodule_branches)

    def test_merger_get_all_submodules(self):
        submodules = merger.get_all_submodules(self.repo_path)
        self.assertEqual(len(submodules), 1)
        self.assertEqual(submodules[0].path, self.submodule_relative_path)

    def test_merger_import_meta_repo(self):
        merger.import_meta_repo(self.monorepo_path, self.repo_path)
        for branch in self.repo_content.branches:
            git_test_ops.switch_branch(self.monorepo_path, branch.name)
            for file in branch.files:
                self.assertTrue(self.check_file_content(self.monorepo_path, file.filename, file.content))

    def test_merger_main_flow(self):
       # prepare params for main flow
        params = merger.WorkspaceMetadata(
            monorepo_root_dir=self.monorepo_path,
            metarepo_root_dir=self.repo_path,
            metarepo_default_branch=merger.get_head_branch(self.repo_path),
            metarepo_branches=merger.get_all_branches(self.repo_path)
        )
        report = merger.main_flow(params)
        print(header_string("Migration Report from main_flow"))
        print(report)

        # checks to see import was successful
        # "feature" branch should exist in the monorepo (it exists in the metarepo)
        monorepo_expected_branches = set(["main", "feature", "foo", "dev"])
        monorepo_actual_branches = set(merger.get_all_branches(self.monorepo_path))
        self.assertEqual(monorepo_expected_branches, monorepo_actual_branches)
        
        # but "feature" should not be imported from the submodule (the metarepo "feature" branch doesn't track the submodule)
        # hence, it is not part of the expected submodule import report
        # verify we imported the submodule branches correctly, and we track the nested submodules correctly
        expected_nested_submodule_tracking = [merger.SubmoduleDef(self.nested_submodule_relative_path, self.nested_submodule_url, self.nested_submodule_default_branch_commit_hash)]
        expected_submodule_report = merger.SubmoduleImportInfo(self.submodule_relative_path)
        # case 2: created "main" in monorepo from metarepo "main" and submodule "main"
        # submodule_a default branch "main" tracks nested_submodule default "main"
        expected_submodule_report.add_entry("main", "main", "main", expected_nested_submodule_tracking)
        # case 3: created "foo" in monorepo from metarepo "foo" and submodule default "main"
        # submodule_a default branch "main" tracks nested_submodule default "main"
        expected_submodule_report.add_entry("foo", "foo", "main", expected_nested_submodule_tracking)
        # case 4: created "dev" in monorepo from metarepo default "main" and submodule "dev"
        expected_submodule_report.add_entry("dev", "main", "dev")
        expected_migration_report = merger.MigrationReport()
        expected_migration_report.add_submodule_entry(self.submodule_relative_path, expected_submodule_report)
        self.assertEqual(report, expected_migration_report)

        # verify file contents
        submodule_expected_branches = set(["main", "dev"])
        for submodule in report.submodules_info.keys():
            self.assertSubmoduleImport(self.monorepo_path, submodule, submodule_expected_branches, self.submodule_a_content)
            
if __name__ == "__main__":
    unittest.main()
