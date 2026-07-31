from typing import Any

from fastapi import HTTPException


class AppError(Exception):
    def __init__(
        self, code: str, message: str, status_code: int = 400, details: dict[str, Any] | None = None
    ) -> None:
        self.code = code
        self.message = message
        self.status_code = status_code
        self.details = details or {}
        super().__init__(message)

    def as_detail(self) -> dict[str, Any]:
        return {"error": {"code": self.code, "message": self.message, "details": self.details}}


def http_error(error: AppError) -> HTTPException:
    return HTTPException(status_code=error.status_code, detail=error.as_detail())

