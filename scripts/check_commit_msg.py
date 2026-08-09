"""Validate that a commit message follows Conventional Commits format."""

import re
import sys

PATTERN = re.compile(
    r"^(feat|fix|docs|style|refactor|test|chore|ci|perf|build|revert)"
    r"(\([a-zA-Z0-9_\-\.]+\))?(!)?: .+"
)


def main() -> None:
    """Check the commit message file passed as first argument.

    Args are provided by pre-commit at the commit-msg stage.

    Raises:
        SystemExit: With code 1 if the message does not conform.
    """
    with open(sys.argv[1], encoding="utf-8") as f:
        subject = f.readline().strip()

    if not PATTERN.match(subject):
        print("ERROR: Commit message does not follow Conventional Commits.")
        print(f"       Got:      {subject!r}")
        print("       Expected: <type>(<scope>): <description>")
        print(
            "       Types: feat fix docs style refactor test chore ci perf build revert"
        )
        sys.exit(1)


if __name__ == "__main__":
    main()
