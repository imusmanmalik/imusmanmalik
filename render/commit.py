"""Commit the rendered files to main through the GitHub API.

Branch protection on main requires verified signatures. A git push from the
runner is unsigned, while a commit made with createCommitOnBranch is signed
by GitHub.
"""

import base64
import os
import subprocess

from common import graphql

PATHS = ["assets", "README.md"]


def git(*args):
    return subprocess.run(["git", *args], check=True, capture_output=True, text=True).stdout


def main():
    changed = git("ls-files", "--modified", "--others", "--exclude-standard", "--", *PATHS).split()
    if not changed:
        print("nothing to commit")
        return
    additions = [
        {"path": path, "contents": base64.b64encode(open(path, "rb").read()).decode()}
        for path in sorted(set(changed))
    ]
    data = graphql(
        """
        mutation($input: CreateCommitOnBranchInput!) {
          createCommitOnBranch(input: $input) { commit { url } }
        }
        """,
        {
            "input": {
                "branch": {"repositoryNameWithOwner": os.environ["GITHUB_REPOSITORY"], "branchName": "main"},
                "message": {"headline": "chore: refresh profile assets and upstream table"},
                "fileChanges": {"additions": additions},
                "expectedHeadOid": git("rev-parse", "HEAD").strip(),
            }
        },
    )
    print(data["createCommitOnBranch"]["commit"]["url"])


if __name__ == "__main__":
    main()
