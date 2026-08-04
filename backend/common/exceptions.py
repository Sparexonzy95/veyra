from rest_framework.views import exception_handler


def api_exception_handler(exc, context):
    response = exception_handler(exc, context)
    if response is not None:
        request = context.get('request')
        original_data = response.data
        message = (
            original_data.get('detail', original_data)
            if isinstance(original_data, dict)
            else original_data
        )
        response.data = {
            'error': {
                'code': getattr(exc, 'default_code', 'request_error'),
                'message': message,
                'request_id': getattr(request, 'request_id', None),
            }
        }
    return response