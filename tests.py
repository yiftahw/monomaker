#!/usr/bin/env python3

import unittest
import tempfile
import shutil
import os

from utils import exec_cmd, listdir_list, pretty_print_list, header_string
import git_test_ops
from models.repository import FileContent, BranchContent, RepoContent, SubmoduleDef
from models.migration_report import MigrationReport, MigrationImportInfo, SubmoduleImportInfo, SubmoduleImportInfoEntry
import merger

with open("debug.log", "w") as f:
    f.write("Debug Log\n")

def debug_log(message: str):
    with open("debug.log", "a") as f:
        f.write(message + "\n")


class TestSubmoduleDef(unittest.TestCase):
    """Tests for SubmoduleDef equality and hashing behavior."""
    
    def test_submodule_def_set_deduplication(self):
        """SubmoduleDefs with same path and url should deduplicate in a set, even with different commit_hash."""
        sub1 = SubmoduleDef(path="lib/foo", url="https://github.com/org/foo.git", commit_hash="abc123")
        sub2 = SubmoduleDef(path="lib/foo", url="https://github.com/org/foo.git", commit_hash="def456")
        sub3 = SubmoduleDef(path="lib/bar", url="https://github.com/org/bar.git", commit_hash="abc123")
        
        # sub1 and sub2 have same path/url, should be considered equal
        self.assertEqual(sub1, sub2)
        self.assertEqual(hash(sub1), hash(sub2))
        
        # sub1 and sub3 have different path/url, should not be equal
        self.assertNotEqual(sub1, sub3)
        
        # Set should deduplicate sub1 and sub2
        result = set()
        result.add(sub1)
        result.add(sub2)
        result.add(sub3)
        
        self.assertEqual(len(result), 2, f"Expected 2 unique submodules, got {len(result)}: {result}")
        
        # Verify the paths in the set
        paths = {s.path for s in result}
        self.assertEqual(paths, {"lib/foo", "lib/bar"})

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
            ),
            BranchContent(
                name="bar",
                files=[
                    FileContent(
                        filename="bar.txt",
                        content="bar branch file.",
                        commit_msg="Add bar.txt"
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
            ),
            # we will use "bar" branch to demonstrate
            # that different branches can track the same nested submodule
            # with a different commit hash (i.e upgrading a tag or branch)
            BranchContent(
                name="bar",
                files=[
                    FileContent(
                        filename="bazsub.txt",
                        content="baz branch file in submodule.",
                        commit_msg="Add bazsub.txt"
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
        # bottom up submodule registration
        # this way we don't need to pull new commits into submodules after adding them

        # register nested submodule in submodule_a under default branch
        git_test_ops.add_local_submodule(
            self.submodule_a_path,
            self.submodule_a_content.default_branch,
            self.nested_submodule_path,
            self.nested_submodule_relative_path,
            self.nested_submodule_content.default_branch
        )
        # register nested submodule in submodule_a under "bar" branch
        git_test_ops.add_local_submodule(
            self.submodule_a_path,
            "bar",
            self.nested_submodule_path,
            self.nested_submodule_relative_path,
            "bar"
        )

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
        # register it under "bar" as well, which will track a different nested submodule commit
        git_test_ops.add_local_submodule(
            self.repo_path,
            "bar",
            self.submodule_a_path,
            self.submodule_relative_path,
            "bar"
        )

        # make sure we switch back to default branch (HEAD is just whatever we point to now)
        git_test_ops.switch_branch(self.repo_path, self.repo_content.default_branch)
        git_test_ops.switch_branch(self.submodule_a_path, self.submodule_a_content.default_branch)
        git_test_ops.switch_branch(self.nested_submodule_path, self.nested_submodule_content.default_branch)
        self.nested_submodule_url = git_test_ops.repo_url(self.nested_submodule_path)
        self.nested_submodule_default_branch_commit_hash = git_test_ops.get_commit_hash(self.nested_submodule_path, self.nested_submodule_content.default_branch)
        self.nested_submodule_bar_branch_commit_hash = git_test_ops.get_commit_hash(self.nested_submodule_path, "bar")
        self.submodule_a_main_branch_commit_hash = git_test_ops.get_commit_hash(self.submodule_a_path, "main")
        self.submodule_a_dev_branch_commit_hash = git_test_ops.get_commit_hash(self.submodule_a_path, "dev")
        self.submodule_a_bar_branch_commit_hash = git_test_ops.get_commit_hash(self.submodule_a_path, "bar")
        self.metarepo_main_branch_commit_hash = git_test_ops.get_commit_hash(self.repo_path, "main")
        self.metarepo_foo_branch_commit_hash = git_test_ops.get_commit_hash(self.repo_path, "foo")
        self.metarepo_bar_branch_commit_hash = git_test_ops.get_commit_hash(self.repo_path, "bar")
        print(header_string("Setup complete"))

    def tearDown(self):
        shutil.rmtree(self.monorepo_path)
        shutil.rmtree(self.repo_path)
        shutil.rmtree(self.submodule_a_path)
        shutil.rmtree(self.nested_submodule_path)
        self.cleanup_git_file_protocol()

    def test_check_file_content(self):
        with tempfile.TemporaryDirectory() as tempdir:
            test_file_path = os.path.join(tempdir, "test.txt")
            with open(test_file_path, "w") as f:
                f.write("Test content")
            self.assertTrue(self.check_file_content(tempdir, "test.txt", "Test content"))
            self.assertFalse(self.check_file_content(tempdir, "test.txt", "Wrong content"))
            self.assertFalse(self.check_file_content(tempdir, "nonexistent.txt", "Test content"))

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
            metarepo_default_branch=merger.get_head_branch(self.repo_path)
        )
        report_info = merger.main_flow(params)
        print(header_string("Migration Report from main_flow"))
        print(MigrationReport(report_info)) # pretty print

        # checks to see import was successful
        # "feature" branch should exist in the monorepo (it exists in the metarepo)
        monorepo_expected_branches = set(["main", "feature", "foo", "dev", "bar"])
        monorepo_actual_branches = set(merger.get_all_branches(self.monorepo_path))
        self.assertEqual(monorepo_expected_branches, monorepo_actual_branches)
        
        # but "feature" should not be imported from the submodule (the metarepo "feature" branch doesn't track the submodule)
        # hence, it is not part of the expected submodule import report
        # verify we imported the submodule branches correctly, and we track the nested submodules correctly
        expected_nested_submodule_default_tracking = [merger.SubmoduleDef(self.nested_submodule_relative_path, self.nested_submodule_url, self.nested_submodule_default_branch_commit_hash)]
        expected_nested_submodule_bar_tracking = [merger.SubmoduleDef(self.nested_submodule_relative_path, self.nested_submodule_url, self.nested_submodule_bar_branch_commit_hash)]
        expected_submodule_report = merger.SubmoduleImportInfo(self.submodule_relative_path, self.submodule_a_content.default_branch)
        # case 2: created "main" in monorepo from metarepo "main" and submodule "main"
        # submodule_a default branch "main" tracks nested_submodule default "main"
        expected_submodule_report.add_entry("main", "main", self.metarepo_main_branch_commit_hash, "main", self.submodule_a_main_branch_commit_hash, expected_nested_submodule_default_tracking)
        # case 3: created "foo" in monorepo from metarepo "foo" and submodule default "main"
        # submodule_a default branch "main" tracks nested_submodule default "main"
        expected_submodule_report.add_entry("foo", "foo", self.metarepo_foo_branch_commit_hash, "main", self.submodule_a_main_branch_commit_hash, expected_nested_submodule_default_tracking)
        # case 4: created "dev" in monorepo from metarepo default "main" and submodule "dev"
        expected_submodule_report.add_entry("dev", "main", self.metarepo_main_branch_commit_hash, "dev", self.submodule_a_dev_branch_commit_hash)
        # "bar" branch in metarepo tracks "bar" branch in submodule
        # (case 2 variant, different nested submodule commit hash)
        expected_submodule_report.add_entry("bar", "bar", self.metarepo_bar_branch_commit_hash, "bar", self.submodule_a_bar_branch_commit_hash, expected_nested_submodule_bar_tracking)
        expected_migration_report = merger.MigrationImportInfo(self.repo_content.default_branch)
        expected_migration_report.add_submodule_entry(self.submodule_relative_path, expected_submodule_report)
        print(header_string("Expected Migration Report"))
        print(MigrationReport(expected_migration_report)) # pretty print

        # compare reports
        self.assertEqual(report_info, expected_migration_report)

        # verify file contents in each monorepo branch that imported stuff from the submodule
        submodule_expected_branches = set(["main", "dev", "bar"])
        for submodule in report_info.submodules_info.keys():
            self.assertSubmoduleImport(self.monorepo_path, submodule, submodule_expected_branches, self.submodule_a_content)

    def test_submodule_only_branch_keyerror(self):
        """
        Regression test for KeyError when a branch exists in submodule but not in metarepo.
        
        Scenario:
        - Metarepo has branches: main, foo (both track submodule)
        - Submodule has branches: main, submodule_only_branch
        - When importing submodule_only_branch (case 4), we pre-create it from metarepo default
        - The pre-created branch inherits submodule refs, making it appear in monorepo_branches_tracking_submodule
        - But it was never in metarepo_branch_commits, so we must use metarepo default's commit hash
        """
        # Create a simple metarepo with main and foo branches
        metarepo_content = RepoContent(
            default_branch="main",
            branches=[
                BranchContent(name="main", files=[FileContent("meta.txt", "main content", "Add meta.txt")]),
                BranchContent(name="foo", files=[FileContent("foo.txt", "foo content", "Add foo.txt")]),
            ]
        )
        metarepo_path = create_temporary_repo(metarepo_content)
        
        # Create submodule with main and a submodule-only branch
        submodule_content = RepoContent(
            default_branch="main",
            branches=[
                BranchContent(name="main", files=[FileContent("sub.txt", "sub content", "Add sub.txt")]),
                BranchContent(name="submodule_only_branch", files=[FileContent("only.txt", "only content", "Add only.txt")]),
            ]
        )
        submodule_path = create_temporary_repo(submodule_content)
        submodule_url = f"file://{submodule_path}"
        
        # Add submodule to metarepo main and foo branches
        for branch in ["main", "foo"]:
            git_test_ops.add_local_submodule(metarepo_path, branch, submodule_path, "the_submodule", "main")
        git_test_ops.switch_branch(metarepo_path, "main")
        
        # Create empty monorepo
        monorepo_path = tempfile.mkdtemp()
        git_test_ops.create_repo(monorepo_path, "main")
        
        try:
            # This should NOT raise KeyError
            params = merger.WorkspaceMetadata(
                monorepo_root_dir=monorepo_path,
                metarepo_root_dir=metarepo_path,
                metarepo_default_branch="main"
            )
            report = merger.main_flow(params)
            
            # Verify submodule_only_branch was created and uses metarepo main's commit
            monorepo_branches = set(merger.get_all_branches(monorepo_path))
            self.assertIn("submodule_only_branch", monorepo_branches)
            
            # The submodule_only_branch should reference metarepo "main" branch
            submodule_report = report.submodules_info["the_submodule"]
            submodule_only_entry = next(
                (e for e in submodule_report.entries if e.monorepo_branch == "submodule_only_branch"),
                None
            )
            self.assertIsNotNone(submodule_only_entry)
            self.assertEqual(submodule_only_entry.metarepo_branch, "main")  # Should use default, not "submodule_only_branch"
            
        finally:
            shutil.rmtree(metarepo_path, ignore_errors=True)
            shutil.rmtree(submodule_path, ignore_errors=True)
            shutil.rmtree(monorepo_path, ignore_errors=True)


class TestSquashCommits(unittest.TestCase):
    """Tests for the squash_commits function."""

    def test_squash_recent_commits(self):
        """
        Create a repo with 6 commits (indices 0-5), squash the last 4 (indices 2-5 = HEAD~3 to HEAD),
        verify we end up with 3 commits and the squashed one contains all original messages.
        
        This tests the use case: squash from HEAD~N+1 to HEAD (most recent N commits).
        """
        # Create a temporary repo with 6 commits
        repo_path = tempfile.mkdtemp()
        git_test_ops.create_repo(repo_path, "main")  # Creates initial commit (commit 0)
        
        git_test_ops.commit_file(
            repo_path, "file1.txt", "Content 1",
            "Commit 1: First file"
        )
        git_test_ops.commit_file(
            repo_path, "file2.txt", "Content 2",
            "Commit 2: Second file"
        )
        git_test_ops.commit_file(
            repo_path, "file3.txt", "Content 3",
            "Commit 3: Third file"
        )
        git_test_ops.commit_file(
            repo_path, "file4.txt", "Content 4",
            "Commit 4: Fourth file"
        )
        git_test_ops.commit_file(
            repo_path, "file5.txt", "Content 5",
            "Commit 5: Fifth file"
        )
        
        # Get all commit hashes (newest first - natural git log order)
        # This matches how check_squashable works
        log_result = exec_cmd("git log --format=%H", cwd=repo_path)
        commits = log_result.stdout.strip().splitlines()
        # commits[0] = HEAD (commit 5), commits[5] = oldest (initial commit)
        
        self.assertEqual(len(commits), 6, f"Expected 6 commits, got {len(commits)}")
        
        # We want to squash commits 2-5 (the last 4 commits)
        # In newest-first order: commits[0]=5, commits[1]=4, commits[2]=3, commits[3]=2, commits[4]=1, commits[5]=initial
        # So squash range is commits[0] (head/newest) to commits[3] (tail/oldest of squash range)
        head_to_squash = commits[0]  # HEAD - newest commit to squash
        tail_to_squash = commits[3]  # oldest commit to squash
        
        # Squash the last 4 commits (commits 2-5)
        merger.squash_commits(
            head=head_to_squash,
            tail=tail_to_squash,
            title="Squashed: Commits 2-5",
            description="This is the squash commit combining 4 commits.",
            cwd=repo_path
        )
        
        # Verify we now have 3 commits (newest first)
        log_result = exec_cmd("git log --format=%H", cwd=repo_path)
        new_commits = log_result.stdout.strip().splitlines()
        
        self.assertEqual(len(new_commits), 3, f"Expected 3 commits after squash, got {len(new_commits)}")
        
        # In newest-first order: new_commits[0]=squashed, new_commits[1]=commit1, new_commits[2]=initial
        # Verify the last two commits are preserved (initial and commit 1)
        self.assertEqual(new_commits[2], commits[5], "Initial commit should be preserved")
        self.assertEqual(new_commits[1], commits[4], "Commit 1 should be preserved")
        # new_commits[0] is the squashed commit (new hash)
        
        # Verify the squashed commit message contains all original messages
        squash_commit_msg = exec_cmd(f"git log -1 --format=%B {new_commits[0]}", cwd=repo_path).stdout
        
        # Check title and description
        self.assertIn("Squashed: Commits 2-5", squash_commit_msg)
        self.assertIn("This is the squash commit combining 4 commits.", squash_commit_msg)
        
        # Check that all original commit messages are preserved (commits 2-5)
        self.assertIn("Commit 2: Second file", squash_commit_msg)
        self.assertIn("Commit 3: Third file", squash_commit_msg)
        self.assertIn("Commit 4: Fourth file", squash_commit_msg)
        self.assertIn("Commit 5: Fifth file", squash_commit_msg)
        
        # Verify commit 1's message is NOT in the squash (it should remain separate)
        self.assertNotIn("Commit 1: First file", squash_commit_msg)
        
        # Verify all files are present in the working tree
        for i in range(1, 6):
            file_path = os.path.join(repo_path, f"file{i}.txt")
            self.assertTrue(os.path.isfile(file_path), f"file{i}.txt should exist after squash")
            with open(file_path, "r") as f:
                self.assertEqual(f.read(), f"Content {i}")

        # print the git commit hash of the squashed commit message for reference
        print(header_string("Squashed Commit Message"))
        print(squash_commit_msg)

if __name__ == "__main__":
    unittest.main()
