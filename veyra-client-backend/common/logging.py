import contextvars

_request_id = contextvars.ContextVar('request_id', default='-')

class RequestIdFilter:
    def filter(self, record):
        record.request_id = _request_id.get()
        return True

def set_request_id(value: str):
    _request_id.set(value)
