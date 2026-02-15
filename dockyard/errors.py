"""Custom exceptions for Dockyard."""


class DockyardError(Exception):
    """Base exception type for Dockyard command errors."""


class NotGitRepositoryError(DockyardError):
    """Raised when a git repository cannot be detected."""
