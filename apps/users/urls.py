from django.urls import path
from . import views

app_name = 'users'

urlpatterns = [
    path('login/', views.login_view, name='login'),
    path('logout/', views.logout_view, name='logout'),
    path('profile/', views.profile_view, name='profile'),
    path('manage/', views.manage_users, name='manage'),
    path('create/', views.create_user, name='create'),
    path('edit/<int:user_id>/', views.edit_user, name='edit'),
    path('delete/<int:user_id>/', views.delete_user, name='delete'),
    path('', views.stats_view, name='home'),  # Redirect home to stats
]