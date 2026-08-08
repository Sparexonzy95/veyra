from rest_framework.pagination import PageNumberPagination


class VeyraPageNumberPagination(PageNumberPagination):
    """Default page-number pagination for every Veyra list endpoint.

    DRF's PageNumberPagination ignores a ``page_size`` query parameter unless
    ``page_size_query_param`` is set. The project previously configured only
    ``PAGE_SIZE``, so callers that already asked for ``?page_size=100`` were
    silently served 20 records and quietly lost the rest. Declaring the
    parameter here makes those requests behave as the callers intended.

    ``max_page_size`` is the guard that keeps this from becoming an unbounded
    fetch: a caller can tune the page, not disable paging.
    """

    page_size = 20
    page_size_query_param = 'page_size'
    max_page_size = 100
