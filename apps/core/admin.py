from django.contrib import admin
from .models import AppSettings

@admin.register(AppSettings)
class AppSettingsAdmin(admin.ModelAdmin):
    """Admin interface pour le singleton AppSettings."""
    list_display = ("active_detection_model", "active_chatbot_model", "last_updated_at", "last_updated_by")
    readonly_fields = ("last_updated_at", "last_updated_by")

    # Empêcher l'ajout ou la suppression d'instances (singleton)
    def has_add_permission(self, request):
        # Autoriser l'ajout seulement s'il n'y a aucune instance
        return not AppSettings.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False # Ne jamais autoriser la suppression

    def save_model(self, request, obj, form, change):
        # Assigner l'utilisateur courant lors de la modification
        obj.last_updated_by = request.user
        super().save_model(request, obj, form, change)

    # S'assurer que l'objet est chargé pour l'édition
    def get_object(self, request, object_id, from_field=None):
        # Toujours retourner l'instance singleton (pk=1)
        return AppSettings.load()

    # Optionnel: rediriger vers l'édition de l'instance unique
    def changelist_view(self, request, extra_context=None):
        from django.http import HttpResponseRedirect
        from django.urls import reverse
        # Si l'objet existe, rediriger vers sa page d'édition
        # Sinon, laisser la vue standard (qui permettra l'ajout si has_add_permission le permet)
        try:
            singleton_instance = AppSettings.load()
            # Construire l'URL de la page d'édition
            change_url = reverse(
                f"admin:{self.model._meta.app_label}_{self.model._meta.model_name}_change",
                args=[singleton_instance.pk]
            )
            return HttpResponseRedirect(change_url)
        except AppSettings.DoesNotExist:
            # Si l'objet n'existe pas encore, laisser la vue standard
            # (qui devrait montrer un bouton "Ajouter" si has_add_permission le permet)
            return super().changelist_view(request, extra_context=extra_context)

