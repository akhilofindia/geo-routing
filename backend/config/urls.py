"""URL routes. API paths stay out of the frontend catch-all."""

from __future__ import annotations

import mimetypes
from pathlib import Path

from django.conf import settings
from django.http import FileResponse, HttpResponse, JsonResponse
from django.urls import include, path, re_path


def spa(request, path: str = ""):
    if path.startswith("api/") or path == "api":
        return JsonResponse({"error": "Not found."}, status=404)
    dist = Path(settings.FRONTEND_DIST)
    if path:
        candidate = (dist / path).resolve()
        try:
            inside = candidate.is_relative_to(dist.resolve())
        except ValueError:
            inside = False
        if inside and candidate.is_file():
            content_type, _encoding = mimetypes.guess_type(candidate.name)
            response = FileResponse(candidate.open("rb"), content_type=content_type or "application/octet-stream")
            if "assets" in candidate.parts:
                response["Cache-Control"] = "public, max-age=31536000, immutable"
            return response
    index = dist / "index.html"
    if not index.is_file():
        return HttpResponse(
            "Frontend is not built. From the frontend folder, run npm install and npm run build.",
            status=503,
            content_type="text/plain",
        )
    return FileResponse(index.open("rb"), content_type="text/html")


urlpatterns = [
    path("api/", include("planner.urls")),
    re_path(r"^(?P<path>.*)$", spa),
]
