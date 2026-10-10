"""HTTP endpoints for place search and trip planning."""

from __future__ import annotations

import logging

from rest_framework.response import Response
from rest_framework.views import APIView

from planner.geocode import GeocodeError, search
from planner.planning import PlanError, plan_trip

logger = logging.getLogger(__name__)


class HealthView(APIView):
    def get(self, request):
        return Response({"status": "ok"})


class GeocodeView(APIView):
    def get(self, request):
        query = (request.query_params.get("q") or "").strip()
        if len(query) < 2:
            return Response({"results": []})
        try:
            results = search(query)
        except GeocodeError as exc:
            return Response({"error": str(exc)}, status=exc.status)
        return Response({"results": results})


class PlanView(APIView):
    def post(self, request):
        try:
            result = plan_trip(request.data)
        except PlanError as exc:
            return Response({"error": str(exc)}, status=exc.status)
        except Exception:
            logger.exception("Trip planning failed")
            return Response({"error": "Planning failed. Try again in a moment."}, status=500)
        return Response(result)
