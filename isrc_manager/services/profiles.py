"""Profile selection and deletion workflows."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .database_admin import ProfileStoreService


@dataclass(slots=True)
class ProfileChoice:
    label: str
    path: str


@dataclass(slots=True)
class ProfileRemovalResult:
    deleted_path: str
    deleting_current: bool
    fallback_path: str | None


class ProfileWorkflowService:
    """Coordinates profile list presentation and deletion fallback behavior."""

    def __init__(
        self,
        database_dir: str | Path,
        profile_store: ProfileStoreService | None = None,
    ):
        self.database_dir = Path(database_dir)
        self.profile_store = profile_store or ProfileStoreService(self.database_dir)

    def list_profile_choices(self, current_db_path: str | None = None) -> list[ProfileChoice]:
        profiles = self.profile_store.list_profiles()
        choices = [ProfileChoice(label=Path(path).name, path=path) for path in profiles]
        if current_db_path and current_db_path not in profiles:
            choices.append(
                ProfileChoice(label=f"{Path(current_db_path).name} (external)", path=current_db_path)
            )
        return choices

    def build_new_profile_path(self, name: str) -> Path:
        path = self.profile_store.build_profile_path(name)
        if path.exists():
            raise FileExistsError(path)
        return path

    def delete_profile(self, path: str | Path, current_db_path: str | None = None) -> ProfileRemovalResult:
        profile_path = str(Path(path))
        deleting_current = bool(current_db_path) and str(Path(current_db_path)) == profile_path

        self.profile_store.delete_profile(profile_path)

        fallback_path = None
        if deleting_current:
            remaining_profiles = self.profile_store.list_profiles()
            fallback_path = remaining_profiles[0] if remaining_profiles else str(self.database_dir / "library.db")

        return ProfileRemovalResult(
            deleted_path=profile_path,
            deleting_current=deleting_current,
            fallback_path=fallback_path,
        )
