"""Git repository manager for Prometheus rule GitOps workflow."""

import os
import shutil
import tempfile
from pathlib import Path
from typing import Any

import httpx
import structlog

from poundcake.config import get_settings

logger = structlog.get_logger(__name__)


class GitManager:
    """Manages Git repository operations for Prometheus rules."""

    def __init__(self) -> None:
        """Initialize the Git manager."""
        self.settings = get_settings()
        self.work_dir = Path(tempfile.gettempdir()) / "poundcake-git"
        self.repo_path: Path | None = None

    async def clone_or_pull(self) -> bool:
        """
        Clone the repository or pull latest changes.

        Returns:
            True if successful
        """
        if not self.settings.git_enabled or not self.settings.git_repo_url:
            logger.warning("Git not enabled or repo URL not configured")
            return False

        try:
            import git
        except ImportError:
            logger.error("GitPython not installed. Install with: pip install GitPython")
            return False

        try:
            self.work_dir.mkdir(parents=True, exist_ok=True)
            repo_name = self.settings.git_repo_url.split("/")[-1].replace(".git", "")
            self.repo_path = self.work_dir / repo_name

            if self.repo_path.exists():
                repo = git.Repo(self.repo_path)
                origin = repo.remotes.origin
                origin.pull(self.settings.git_branch)
                logger.info("Pulled latest changes", repo=str(self.repo_path))
            else:
                env = self._get_git_env()
                git.Repo.clone_from(
                    self.settings.git_repo_url,
                    self.repo_path,
                    branch=self.settings.git_branch,
                    env=env,
                )
                logger.info("Cloned repository", repo=str(self.repo_path))

            return True
        except Exception as e:
            logger.error("Failed to clone/pull repository", error=str(e))
            return False

    def _get_git_env(self) -> dict[str, str]:
        """
        Get environment variables for Git operations.

        Returns:
            Environment variables with Git credentials
        """
        env = os.environ.copy()

        if self.settings.git_token:
            if "github.com" in self.settings.git_repo_url:
                env["GIT_ASKPASS"] = "echo"
                env["GIT_USERNAME"] = "oauth2"
                env["GIT_PASSWORD"] = self.settings.git_token
            elif "gitlab.com" in self.settings.git_repo_url:
                env["GIT_ASKPASS"] = "echo"
                env["GIT_USERNAME"] = "oauth2"
                env["GIT_PASSWORD"] = self.settings.git_token

        if self.settings.git_ssh_key_path:
            env["GIT_SSH_COMMAND"] = (
                f"ssh -i {self.settings.git_ssh_key_path} -o StrictHostKeyChecking=no"
            )

        return env

    async def commit_and_push_deletion(
        self,
        file_path: str,
        commit_message: str,
    ) -> tuple[bool, str]:
        """
        Delete a file and push changes to a new branch.

        Args:
            file_path: Relative path to file in repo
            commit_message: Commit message

        Returns:
            Tuple of (success, branch_name)
        """
        if not self.repo_path:
            if not await self.clone_or_pull():
                return False, ""

        try:
            import git
        except ImportError:
            logger.error("GitPython not installed")
            return False, ""

        try:
            assert self.repo_path is not None
            repo = git.Repo(self.repo_path)

            branch_name = f"poundcake-rule-update-{os.urandom(4).hex()}"
            current = repo.head.reference
            new_branch = repo.create_head(branch_name)
            assert hasattr(new_branch, 'checkout')
            new_branch.checkout()

            full_path = self.repo_path / file_path
            if full_path.exists():
                full_path.unlink()

            repo.index.remove([file_path])

            repo.config_writer().set_value("user", "name", self.settings.git_user_name).release()
            repo.config_writer().set_value("user", "email", self.settings.git_user_email).release()

            repo.index.commit(commit_message)

            env = self._get_git_env()
            if self.settings.git_token and "github.com" in self.settings.git_repo_url:
                url = self.settings.git_repo_url.replace(
                    "https://", f"https://oauth2:{self.settings.git_token}@"
                )
                repo.remotes.origin.set_url(url)

            repo.git.push("--set-upstream", "origin", branch_name, env=env)

            assert hasattr(current, 'checkout')
            current.checkout()

            logger.info(
                "Committed and pushed file deletion",
                branch=branch_name,
                file=file_path,
            )
            return True, branch_name
        except Exception as e:
            logger.error("Failed to commit and push deletion", error=str(e))
            return False, ""

    async def commit_and_push_changes(
        self,
        file_path: str,
        content: str,
        commit_message: str,
    ) -> tuple[bool, str]:
        """
        Commit and push changes to a new branch.

        Args:
            file_path: Relative path to file in repo
            content: New file content
            commit_message: Commit message

        Returns:
            Tuple of (success, branch_name)
        """
        if not self.repo_path:
            if not await self.clone_or_pull():
                return False, ""

        try:
            import git
        except ImportError:
            logger.error("GitPython not installed")
            return False, ""

        try:
            assert self.repo_path is not None
            repo = git.Repo(self.repo_path)

            branch_name = f"poundcake-rule-update-{os.urandom(4).hex()}"
            current = repo.head.reference
            new_branch = repo.create_head(branch_name)
            assert hasattr(new_branch, 'checkout')
            new_branch.checkout()

            full_path = self.repo_path / file_path
            full_path.parent.mkdir(parents=True, exist_ok=True)
            full_path.write_text(content)

            repo.index.add([file_path])

            repo.config_writer().set_value("user", "name", self.settings.git_user_name).release()
            repo.config_writer().set_value("user", "email", self.settings.git_user_email).release()

            repo.index.commit(commit_message)

            env = self._get_git_env()
            if self.settings.git_token and "github.com" in self.settings.git_repo_url:
                url = self.settings.git_repo_url.replace(
                    "https://", f"https://oauth2:{self.settings.git_token}@"
                )
                repo.remotes.origin.set_url(url)

            repo.git.push("--set-upstream", "origin", branch_name, env=env)

            assert hasattr(current, 'checkout')
            current.checkout()

            logger.info(
                "Committed and pushed changes",
                branch=branch_name,
                file=file_path,
            )
            return True, branch_name
        except Exception as e:
            logger.error("Failed to commit and push", error=str(e))
            return False, ""

    async def create_pull_request(
        self,
        branch_name: str,
        title: str,
        description: str,
    ) -> dict[str, Any] | None:
        """
        Create a pull request.

        Args:
            branch_name: Source branch name
            title: PR title
            description: PR description

        Returns:
            PR information or None if failed
        """
        if self.settings.git_provider == "none":
            logger.info("Git provider is 'none', skipping PR creation")
            return None

        if self.settings.git_provider == "github":
            return await self._create_github_pr(branch_name, title, description)
        elif self.settings.git_provider == "gitlab":
            return await self._create_gitlab_pr(branch_name, title, description)
        elif self.settings.git_provider == "gitea":
            return await self._create_gitea_pr(branch_name, title, description)
        else:
            logger.warning("Unknown git provider", provider=self.settings.git_provider)
            return None

    async def _create_github_pr(
        self, branch_name: str, title: str, description: str
    ) -> dict[str, Any] | None:
        """Create a GitHub pull request."""
        try:
            repo_url = self.settings.git_repo_url.replace(".git", "")
            repo_parts = repo_url.split("github.com/")[-1].split("/")
            owner, repo = repo_parts[0], repo_parts[1]

            api_url = f"https://api.github.com/repos/{owner}/{repo}/pulls"

            headers = {
                "Authorization": f"token {self.settings.git_token}",
                "Accept": "application/vnd.github.v3+json",
            }

            data = {
                "title": title,
                "body": description,
                "head": branch_name,
                "base": self.settings.git_branch,
            }

            async with httpx.AsyncClient(timeout=30) as client:
                response = await client.post(api_url, headers=headers, json=data)

                if response.status_code == 201:
                    pr_data = response.json()
                    logger.info(
                        "Created GitHub PR",
                        pr_number=pr_data.get("number"),
                        url=pr_data.get("html_url"),
                    )
                    return pr_data  # type: ignore[no-any-return]
                else:
                    logger.error(
                        "Failed to create GitHub PR",
                        status=response.status_code,
                        response=response.text,
                    )
                    return None
        except Exception as e:
            logger.error("Error creating GitHub PR", error=str(e))
            return None

    async def _create_gitlab_pr(
        self, branch_name: str, title: str, description: str
    ) -> dict[str, Any] | None:
        """Create a GitLab merge request."""
        try:
            repo_url = self.settings.git_repo_url.replace(".git", "")
            repo_parts = repo_url.split("gitlab.com/")[-1]
            project_path = repo_parts.replace("/", "%2F")

            api_url = f"https://gitlab.com/api/v4/projects/{project_path}/merge_requests"

            headers = {
                "PRIVATE-TOKEN": self.settings.git_token,
            }

            data = {
                "source_branch": branch_name,
                "target_branch": self.settings.git_branch,
                "title": title,
                "description": description,
            }

            async with httpx.AsyncClient(timeout=30) as client:
                response = await client.post(api_url, headers=headers, json=data)

                if response.status_code == 201:
                    mr_data = response.json()
                    logger.info(
                        "Created GitLab MR",
                        mr_iid=mr_data.get("iid"),
                        url=mr_data.get("web_url"),
                    )
                    return mr_data  # type: ignore[no-any-return]
                else:
                    logger.error(
                        "Failed to create GitLab MR",
                        status=response.status_code,
                        response=response.text,
                    )
                    return None
        except Exception as e:
            logger.error("Error creating GitLab MR", error=str(e))
            return None

    async def _create_gitea_pr(
        self, branch_name: str, title: str, description: str
    ) -> dict[str, Any] | None:
        """Create a Gitea pull request."""
        try:
            repo_url = self.settings.git_repo_url.replace(".git", "")
            base_url = "/".join(repo_url.split("/")[:-2])
            owner_repo = "/".join(repo_url.split("/")[-2:])

            api_url = f"{base_url}/api/v1/repos/{owner_repo}/pulls"

            headers = {
                "Authorization": f"token {self.settings.git_token}",
            }

            data = {
                "title": title,
                "body": description,
                "head": branch_name,
                "base": self.settings.git_branch,
            }

            async with httpx.AsyncClient(timeout=30) as client:
                response = await client.post(api_url, headers=headers, json=data)

                if response.status_code == 201:
                    pr_data = response.json()
                    logger.info(
                        "Created Gitea PR",
                        pr_number=pr_data.get("number"),
                        url=pr_data.get("html_url"),
                    )
                    return pr_data  # type: ignore[no-any-return]
                else:
                    logger.error(
                        "Failed to create Gitea PR",
                        status=response.status_code,
                        response=response.text,
                    )
                    return None
        except Exception as e:
            logger.error("Error creating Gitea PR", error=str(e))
            return None

    def cleanup(self) -> None:
        """Clean up cloned repository."""
        if self.repo_path and self.repo_path.exists():
            try:
                shutil.rmtree(self.repo_path)
                logger.info("Cleaned up Git repository", path=str(self.repo_path))
            except Exception as e:
                logger.error("Failed to cleanup Git repo", error=str(e))


_git_manager: GitManager | None = None


def get_git_manager() -> GitManager:
    """Get the global Git manager instance."""
    global _git_manager
    if _git_manager is None:
        _git_manager = GitManager()
    return _git_manager
