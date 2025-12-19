from django.urls import path
from . import views

app_name = "reviv"

urlpatterns = [
    path("", views.home, name="home"),
    path("upload/", views.upload, name="upload"),
    path("process/<uuid:restoration_id>/", views.process, name="process"),
    path("result/<uuid:restoration_id>/", views.result, name="result"),
    path("gallery/", views.gallery, name="gallery"),
    path("api/kie/callback/", views.kie_callback, name="kie_callback"),
]
