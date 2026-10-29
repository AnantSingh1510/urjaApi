class ServiceError(Exception):
    """Sanitized error safe to expose; never use raw portal bodies or credentials."""

    def __init__(self, code: str, message: str, status: int = 502):
        super().__init__(message)
        self.code, self.message, self.status = code, message, status


def protocol_error() -> ServiceError:
    return ServiceError(
        "upstream_protocol_error", "Portal returned an unexpected data format."
    )
