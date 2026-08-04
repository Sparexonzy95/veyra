from drf_spectacular.extensions import OpenApiAuthenticationExtension

class VeyraSessionScheme(OpenApiAuthenticationExtension):
    target_class = 'accounts.authentication.VeyraSessionAuthentication'
    name = 'VeyraSessionCookie'

    def get_security_definition(self, auto_schema):
        return {
            'type': 'apiKey',
            'in': 'cookie',
            'name': 'veyra_session',
            'description': 'HTTP-only Veyra application session cookie.',
        }
