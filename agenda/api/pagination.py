"""Global limit-offset pagination with limit clamping and parameter validation."""

from rest_framework.exceptions import ValidationError
from rest_framework.pagination import LimitOffsetPagination
from rest_framework.request import Request


class StandardLimitOffsetPagination(LimitOffsetPagination):
    """Standard limit-offset pagination with clamping to max_limit."""

    default_limit = 25
    max_limit = 100

    def get_limit(self, request: Request) -> int:
        if self.limit_query_param in request.query_params:
            raw_limit = request.query_params[self.limit_query_param]
            try:
                limit = int(raw_limit)
            except (TypeError, ValueError):
                raise ValidationError(
                    "El parámetro 'limit' debe ser un número entero positivo."
                ) from None

            if limit <= 0:
                raise ValidationError("El parámetro 'limit' debe ser mayor a 0.")

            if self.max_limit:
                return min(limit, self.max_limit)
            return limit

        return self.default_limit

    def get_offset(self, request: Request) -> int:
        if self.offset_query_param in request.query_params:
            raw_offset = request.query_params[self.offset_query_param]
            try:
                offset = int(raw_offset)
            except (TypeError, ValueError):
                raise ValidationError(
                    "El parámetro 'offset' debe ser un número entero mayor o igual a 0."
                ) from None

            if offset < 0:
                raise ValidationError("El parámetro 'offset' debe ser mayor o igual a 0.")

            return offset

        return 0
