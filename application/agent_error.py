from enum import Enum


class AgentErrorCode(Enum):
    EMPTY_MESSAGE = "empty_message"
    HTTP_ERROR = "http_error"
    CONNECTION_ERROR = "connection_error"
    TIMEOUT = "timeout"
    INVALID_JSON = "invalid_json"
    MISSING_OUTPUT_TEXT = "missing_output_text"
    INCOMPLETE_RESPONSE = "incomplete_response"


class AgentError(Exception):
    def __init__(
        self,
        code: AgentErrorCode,
        *,
        details: str | None = None,
        status_code: int | None = None,
        response_status: str | None = None,
    ) -> None:
        self.code = code
        self.details = details
        self.status_code = status_code
        self.response_status = response_status
        super().__init__(code.value)
