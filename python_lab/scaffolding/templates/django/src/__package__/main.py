"""Local Django health endpoint and development server."""

import os
import sys

from django.core.management import execute_from_command_line
from django.http import HttpRequest, JsonResponse
from django.urls import path


def health(request: HttpRequest) -> JsonResponse:
    return JsonResponse({"status": "ok"})


urlpatterns = [path("health", health)]


def main() -> None:
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "__package__.settings")
    execute_from_command_line([sys.argv[0], "runserver", "127.0.0.1:8000"])


if __name__ == "__main__":
    main()
