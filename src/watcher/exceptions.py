"""Custom exceptions for the file watcher package."""


class WatcherError(Exception):
    """Base exception for all watcher errors."""
    pass


class QueueError(WatcherError):
    """Error related to the persistent queue."""
    pass


class QueueCorruptionError(QueueError):
    """Queue database is corrupted."""
    pass


class RootError(WatcherError):
    """Error related to root folder management."""
    pass


class RootNotFoundError(RootError):
    """Specified root folder does not exist."""
    pass


class RootAlreadyExistsError(RootError):
    """Root folder is already being watched."""
    pass


class WatcherNotRunningError(WatcherError):
    """Watcher process is not running."""
    pass


class WatcherAlreadyRunningError(WatcherError):
    """Watcher process is already running."""
    pass
