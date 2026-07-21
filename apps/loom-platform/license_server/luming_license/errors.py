class ActivationError(RuntimeError):
    def __init__(self, message: str, status: int = 400, code: str = "REQUEST_INVALID"):
        super().__init__(message)
        self.status = status
        self.code = code
