from django.urls import path
from . import views

app_name = 'core'

urlpatterns = [
    path('settings/', views.app_settings_view, name='settings'),
    # path('settings/update/', views.update_app_settings, name='update_settings'),
]
