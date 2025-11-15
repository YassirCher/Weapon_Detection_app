from django.urls import path
from . import views

app_name = 'dashboard'

urlpatterns = [
    path('stats/', views.stats_view, name='stats'),
    path('model-errors/', views.model_errors_view, name='model_errors'),
]
