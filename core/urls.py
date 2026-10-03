from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path("admin/", admin.site.urls),
    path("dashboard/", include("dashboard.urls")),
    path("api/v1/", include("api.urls")),
]
