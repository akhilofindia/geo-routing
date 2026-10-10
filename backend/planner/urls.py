from django.urls import path

from planner.views import GeocodeView, HealthView, PlanView

urlpatterns = [
    path("health", HealthView.as_view()),
    path("geocode", GeocodeView.as_view()),
    path("plan", PlanView.as_view()),
]
