class PasswordChangeRequiredError(Exception):
    def __init__(self, message: str = "Change your password before using the app.") -> None:
        super().__init__(message)


class AuthError(Exception):
    def __init__(self, status_code: int, detail: str) -> None:
        self.status_code = status_code
        self.detail = detail
        super().__init__(detail)
