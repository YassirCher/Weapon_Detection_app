from django.db import models
from django.conf import settings
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
import os

def detection_media_path(instance, filename):
    now = timezone.now()
    return f"uploads/{now.year}/{now.month:02d}/{now.day:02d}/{filename}"

class DangerousCategory(models.Model):
    CATEGORY_TYPES = (
        ('DANGEROUS', 'Dangereuse'),
        ('HYPERDANGEROUS', 'Hyperdangereuse'),
    )
    name = models.CharField(_("nom de la catégorie"), max_length=100, unique=True)
    description = models.TextField(_("description"), blank=True, null=True)
    category_type = models.CharField(
        max_length=20,
        choices=CATEGORY_TYPES,
        default='DANGEROUS',
        verbose_name=_("type de danger")
    )
    is_active = models.BooleanField(
        _("active"), 
        default=True, 
        help_text=_("Seules les catégories actives sont signalées.")
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, 
        related_name='created_dangerous_categories', 
        on_delete=models.SET_NULL, 
        null=True, 
        blank=True, 
        verbose_name=_("créé par")
    )
    created_at = models.DateTimeField(
        auto_now_add=True, 
        verbose_name=_("créé le")
    )

    class Meta:
        verbose_name = _("Catégorie Dangereuse")
        verbose_name_plural = _("Catégories Dangereuses")
        ordering = ["name"]

    def __str__(self):
        return f"{self.name} ({self.get_category_type_display()})"

class Report(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='reports',
        verbose_name=_("utilisateur")
    )
    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name=_("créé le")
    )
    name = models.CharField(
        _("nom du rapport"),
        max_length=255,
        blank=True,
        help_text=_("Nom optionnel du rapport")
    )
    location = models.CharField(
        _("localisation"),
        max_length=255,
        blank=True,
        null=True,
        help_text=_("Localisation associée au rapport")
    )

    class Meta:
        verbose_name = _("Rapport")
        verbose_name_plural = _("Rapports")
        ordering = ["-created_at"]

    def __str__(self):
        return f"Rapport {self.id} par {self.user.email} le {self.created_at.strftime('%Y-%m-%d %H:%M')}"

class DetectionLog(models.Model):
    DANGER_LEVELS = (
        ('DANGEROUS', 'Dangereuse'),
        ('HYPERDANGEROUS', 'Hyperdangereuse'),
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, 
        on_delete=models.CASCADE, 
        related_name='detection_logs', 
        verbose_name=_("utilisateur")
    )
    report = models.ForeignKey(
        Report,
        on_delete=models.CASCADE,
        related_name='detections',
        null=True,
        blank=True,
        verbose_name=_("rapport")
    )
    uploaded_file = models.FileField(
        _("fichier uploadé"), 
        upload_to=detection_media_path, 
        help_text=_("Image ou vidéo analysée.")
    )
    original_file = models.FileField( 
        _("fichier original"),
        upload_to='uploads/%Y/%m/%d/',
        help_text=_("Image originale téléversée."),
        null=True,
        blank=True
    )
    detection_timestamp = models.DateTimeField(
        _("horodatage détection"), 
        default=timezone.now
    )
    user_location = models.CharField(
        _("localisation utilisateur"), 
        max_length=255, 
        blank=True, 
        null=True, 
        help_text=_("Localisation de l'utilisateur au moment de la détection.")
    )
    detected_objects = models.JSONField(
        _("objets détectés"), 
        blank=True, 
        null=True, 
        help_text=_("Résultats bruts du modèle IA (ex: [{\"category\": \"knife\", \"confidence\": 0.85, \"bbox\": [x,y,w,h]}]).")
    )
    danger_level = models.CharField(
        _("niveau de danger"),
        max_length=20,
        choices=DANGER_LEVELS,
        null=True,
        blank=True,
        help_text=_("Niveau de danger détecté (Dangereuse ou Hyperdangereuse).")
    )
    model_used = models.CharField(
        _("modèle utilisé"), 
        max_length=255, 
        blank=True, 
        null=True, 
        help_text=_("Nom ou identifiant du modèle de détection utilisé (ou 'simulation').")
    )
    is_simulated = models.BooleanField(
        _("détection simulée"), 
        default=False, 
        help_text=_("Indique si cette détection provient d'une simulation.")
    )
    
    # ============ NOUVEAUX CHAMPS POUR SUPPORT VIDÉO ============
    media_type = models.CharField(
        max_length=10,
        choices=(('IMAGE', 'Image'), ('VIDEO', 'Vidéo')),
        default='IMAGE',
        verbose_name=_("type de média"),
        help_text=_("Type de fichier analysé : image ou vidéo")
    )
    
    video_metadata = models.JSONField(
        blank=True,
        null=True,
        verbose_name=_("métadonnées vidéo"),
        help_text=_("FPS, durée, résolution, nombre total de frames, etc.")
    )
    
    frames_analyzed = models.IntegerField(
        default=0,
        verbose_name=_("frames analysés"),
        help_text=_("Nombre de frames qui ont été analysées dans la vidéo")
    )
    
    processing_duration = models.FloatField(
        default=0.0,
        verbose_name=_("durée de traitement (secondes)"),
        help_text=_("Temps total de traitement de la détection")
    )

    class Meta:
        verbose_name = _("Journal de Détection")
        verbose_name_plural = _("Journaux de Détection")
        ordering = ["-detection_timestamp"]

    def __str__(self):
        sim_status = "(Simulé)" if self.is_simulated else ""
        return f"Détection par {self.user.email} le {self.detection_timestamp.strftime('%Y-%m-%d %H:%M')} {sim_status}"

class ModelValidation(models.Model):
    detection_log = models.OneToOneField(DetectionLog, on_delete=models.CASCADE, related_name='validation', verbose_name=_("log de détection"))
    validator = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='validations', verbose_name=_("validateur"))
    validation_timestamp = models.DateTimeField(_("horodatage validation"), default=timezone.now)
    is_correct = models.BooleanField(_("détection correcte?"), help_text=_("Le modèle (ou la simulation) a-t-il correctement identifié les objets ?"))
    corrected_category = models.CharField(_("catégorie corrigée"), max_length=100, blank=True, null=True, help_text=_("Si incorrect, spécifier la catégorie réelle (ou laisser vide si aucun objet pertinent)."))
    comments = models.TextField(_("commentaires"), blank=True, null=True)

    class Meta:
        verbose_name = _("Validation Modèle")
        verbose_name_plural = _("Validations Modèle")
        ordering = ["-validation_timestamp"]

    def __str__(self):
        status = _("Correcte") if self.is_correct else _("Incorrecte")
        return f"Validation de {self.detection_log} par {self.validator.email if self.validator else 'N/A'} - {status}"


class CategoryValidation(models.Model):
    """Validation individuelle par catégorie pour les vidéos"""
    detection_log = models.ForeignKey(
        DetectionLog, 
        on_delete=models.CASCADE, 
        related_name='category_validations', 
        verbose_name=_("log de détection")
    )
    category_name = models.CharField(
        _("nom de catégorie"), 
        max_length=100,
        help_text=_("Nom de la catégorie détectée (ex: shotgun, knife)")
    )
    validator = models.ForeignKey(
        settings.AUTH_USER_MODEL, 
        on_delete=models.SET_NULL, 
        null=True, 
        blank=True, 
        related_name='category_validations', 
        verbose_name=_("validateur")
    )
    validation_timestamp = models.DateTimeField(
        _("horodatage validation"), 
        default=timezone.now
    )
    is_valid = models.BooleanField(
        _("catégorie valide?"), 
        help_text=_("La détection de cette catégorie est-elle correcte ?")
    )
    frame_number = models.IntegerField(
        _("numéro de frame"),
        null=True,
        blank=True,
        help_text=_("Frame où cette catégorie a été détectée (pour vidéos)")
    )
    confidence = models.FloatField(
        _("confiance"), 
        default=0.0,
        help_text=_("Confiance du modèle pour cette détection")
    )
    comments = models.TextField(
        _("commentaires"), 
        blank=True, 
        null=True
    )

    class Meta:
        verbose_name = _("Validation de Catégorie")
        verbose_name_plural = _("Validations de Catégories")
        ordering = ["-validation_timestamp"]
        unique_together = ['detection_log', 'category_name', 'frame_number']

    def __str__(self):
        status = _("Valide") if self.is_valid else _("Invalide")
        return f"{self.category_name} - {status} (Frame {self.frame_number or 'N/A'})"