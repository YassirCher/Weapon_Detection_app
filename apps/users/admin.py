from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from .models import User
from .forms import UserCreationForm, UserEditForm

class UserAdmin(BaseUserAdmin):
    # Utiliser les formulaires personnalisés
    form = UserEditForm
    add_form = UserCreationForm

    # Champs à afficher dans la liste
    list_display = (
        "email",
        "first_name",
        "last_name",
        "role",
        "is_staff",
        "is_active",
    )
    list_filter = ("is_staff", "is_superuser", "is_active", "groups", "role")
    search_fields = ("email", "first_name", "last_name")
    ordering = ("email",)
    
    # Champs pour modifier un utilisateur
    fieldsets = (
        (None, {"fields": ("email", "password")}),
        (
            "Informations personnelles",
            {"fields": ("first_name", "last_name", "profile_picture", "location")},
        ),
        (
            "Permissions",
            {
                "fields": (
                    "is_active",
                    "is_staff",
                    "is_superuser",
                    "groups",
                    "user_permissions",
                ),
            },
        ),
        ("Rôle", {"fields": ("role",)}),
        ("Dates importantes", {"fields": ("last_login", "date_joined")}),
    )
    
    # Champs pour ajouter un utilisateur
    add_fieldsets = (
        (
            None,
            {
                "classes": ("wide",),
                "fields": (
                    "email",
                    "password1",
                    "password2",
                    "first_name",
                    "last_name",
                    "role",
                    "profile_picture",
                    "location",
                    "is_active",
                    "is_staff",
                    "is_superuser",
                ),
            },
        ),
    )

admin.site.register(User, UserAdmin)