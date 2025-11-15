from django.db import models
from django.utils.translation import gettext_lazy as _
import os
from django.conf import settings

def get_available_detection_models():
    model_path = "models_ai/detection/weapon.pt"
    full_path = os.path.join(settings.BASE_DIR, model_path)
    if os.path.exists(full_path):
        return [(model_path, "weapon.pt (Fichier Présent)"), ("simulation", "Simulation Détection")]
    return [("simulation", "Simulation Détection")]

def get_available_chatbot_models():
    return [
        ("grok-3", "Grok-3 (xAI)"),  # Add Grok model
        ("gemini-2.0-flash", "gemini-2.0-flash (Google)"),
        ("simulation", "Simulation Chatbot")
    ]

class AppSettings(models.Model):
    active_detection_model = models.CharField(
        _("modèle de détection actif"),
        max_length=500,
        choices=get_available_detection_models(),
        default="simulation",
        help_text=_("Choisir le modèle de détection ou la simulation.")
    )
    active_chatbot_model = models.CharField(
        _("modèle de chatbot actif"),
        max_length=255,
        choices=get_available_chatbot_models(),
        default="grok-3",  # Default to Grok-3
        help_text=_("Choisir le modèle de chatbot ou la simulation.")
    )
    dangerous_threshold = models.FloatField(
        _("seuil de confiance"),
        default=0.5,
        help_text=_("Seuil de confiance minimum pour considérer une détection comme valide (0.1 à 1.0).")
    )
    last_updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        verbose_name=_("dernière modification par")
    )
    last_updated_at = models.DateTimeField(
        auto_now=True,
        verbose_name=_("dernière modification le")
    )

    class Meta:
        verbose_name = _("Paramètres de l'Application")
        verbose_name_plural = _("Paramètres de l'Application")

    def __str__(self):
        return str(_("Paramètres Actuels de l'Application"))

    def save(self, *args, **kwargs):
        self.pk = 1
        super(AppSettings, self).save(*args, **kwargs)

    @classmethod
    def load(cls):
        obj, created = cls.objects.get_or_create(pk=1)
        return obj