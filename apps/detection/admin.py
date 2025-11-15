from django.contrib import admin
from .models import DangerousCategory, DetectionLog, ModelValidation

@admin.register(DangerousCategory)
class DangerousCategoryAdmin(admin.ModelAdmin):
    list_display = ("name", "category_type", "is_active", "created_by", "created_at")
    list_filter = ("category_type", "is_active")
    search_fields = ("name", "description")
    list_editable = ("category_type", "is_active")
    readonly_fields = ("created_by", "created_at")

    def save_model(self, request, obj, form, change):
        if not obj.pk:
            obj.created_by = request.user
        super().save_model(request, obj, form, change)

@admin.register(DetectionLog)
class DetectionLogAdmin(admin.ModelAdmin):
    list_display = (
        "user",
        "detection_timestamp",
        "model_used",
        "danger_level",
        "is_simulated",
        "uploaded_file",
    )
    list_filter = ("danger_level", "is_simulated", "model_used", "detection_timestamp")
    search_fields = ("user__email", "uploaded_file")
    readonly_fields = (
        "user",
        "uploaded_file",
        "detection_timestamp",
        "user_location",
        "detected_objects",
        "danger_level",
        "model_used",
        "is_simulated",
    )

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

@admin.register(ModelValidation)
class ModelValidationAdmin(admin.ModelAdmin):
    list_display = (
        "detection_log",
        "validator",
        "validation_timestamp",
        "is_correct",
        "corrected_category",
    )
    list_filter = ("is_correct", "validation_timestamp")
    search_fields = ("detection_log__user__email", "validator__email", "corrected_category")
    readonly_fields = ("detection_log", "validator", "validation_timestamp")
    # Permettre la modification pour corriger/valider ? Oui.
    # L'ajout se fait via l'application, pas l'admin.
    def has_add_permission(self, request):
        return False

