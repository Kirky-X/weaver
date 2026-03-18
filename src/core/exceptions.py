"""Core exception classes for the weaver system."""


class InvalidStateTransitionError(Exception):
    """Raised when an invalid state transition is attempted.

    Attributes:
        from_status: The current status before transition.
        to_status: The attempted target status.
        message: Human-readable error message.
    """

    def __init__(self, from_status: str, to_status: str) -> None:
        """Initialize the exception with transition details.

        Args:
            from_status: The current status.
            to_status: The attempted target status.
        """
        self.from_status = from_status
        self.to_status = to_status
        self.message = (
            f"Invalid state transition: cannot transition from '{from_status}' to '{to_status}'"
        )
        super().__init__(self.message)