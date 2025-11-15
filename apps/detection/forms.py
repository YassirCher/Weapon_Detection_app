import logging
import os
from django import forms
from django.core.exceptions import ValidationError
from .models import DangerousCategory, DetectionLog, ModelValidation, Report
import zipfile

logger = logging.getLogger(__name__)

class UploadDetectionForm(forms.Form):
    files = forms.FileField(
        label="Images, Vidéos ou Fichier ZIP",
        required=True,
        widget=forms.FileInput(attrs={
            'accept': 'image/jpeg,image/png,video/mp4,video/avi,video/quicktime,application/zip'
        }),
        help_text="Sélectionnez plusieurs images (JPG, PNG), vidéos (MP4, AVI, MOV) ou un seul fichier ZIP. Max : Images 10 Mo, Vidéos 500 Mo, ZIP 100 Mo."
    )
    report_name = forms.CharField(
        label="Nom du Rapport",
        max_length=100,
        required=False,
        help_text="Optionnel. Par défaut, un nom basé sur la date sera utilisé."
    )
    location = forms.CharField(
        label="Localisation",
        max_length=200,
        required=False,
        help_text="Optionnel. Indiquez le lieu de la détection."
    )
    
    video_frame_interval = forms.IntegerField(
        label="Intervalle d'analyse vidéo (frames)",
        initial=30,
        min_value=1,
        max_value=300,
        required=False,
        widget=forms.NumberInput(attrs={
            'class': 'form-control',
            'min': '1',
            'max': '300',
            'value': '30'
        }),
        help_text="Pour les vidéos : analyser 1 frame toutes les X frames (30 = 1/sec pour 30 FPS)"
    )

    def clean(self):
        cleaned_data = super().clean()
        files = self.files.getlist('files') if hasattr(self.files, 'getlist') else [cleaned_data.get('files')]
        logger.info(f"Form cleaning - Files: {len(files)}")

        if not files:
            raise ValidationError("Vous devez uploader au moins un fichier.")

        # Vérifier si mélange de ZIP avec d'autres fichiers
        has_zip = any(f.name.lower().endswith('.zip') for f in files)
        has_media = any(f.name.lower().endswith(('.png', '.jpg', '.jpeg', '.webp', '.jfif', '.mp4', '.avi', '.mov', '.mkv', '.wmv', '.flv')) for f in files)
        
        if has_zip and has_media:
            raise ValidationError("Vous ne pouvez pas uploader des médias (images/vidéos) et un fichier ZIP simultanément.")

        has_valid_file = False
        valid_image_extensions = ('.png', '.jpg', '.jpeg', '.webp', '.jfif')
        valid_video_extensions = ('.mp4', '.avi', '.mov', '.mkv', '.wmv', '.flv')
        
        for file in files:
            file_extension = os.path.splitext(file.name.lower())[1]
            
            if file.name.lower().endswith('.zip'):
                if len(files) > 1:
                    raise ValidationError("Vous ne pouvez uploader qu'un seul fichier ZIP.")
                logger.info(f"Validating ZIP file: {file.name}, size: {file.size}")
                if file.size > 100 * 1024 * 1024:  # 100 MB
                    raise ValidationError(f"Le fichier ZIP '{file.name}' dépasse la limite de 100 Mo.")
                try:
                    with zipfile.ZipFile(file, 'r') as zip_ref:
                        file_list = zip_ref.namelist()
                        logger.info(f"ZIP {file.name} contains {len(file_list)} files: {file_list}")
                        has_media_in_zip = False
                        for file_info in zip_ref.infolist():
                            if file_info.filename.endswith('/') or not os.path.splitext(file_info.filename)[1]:
                                logger.info(f"Skipping directory in ZIP: {file_info.filename}")
                                continue
                            zip_file_ext = os.path.splitext(file_info.filename.lower())[1]
                            if zip_file_ext not in valid_image_extensions and zip_file_ext not in valid_video_extensions:
                                logger.error(f"Invalid file found in ZIP {file.name}: {file_info.filename}")
                                raise ValidationError(f"Le fichier ZIP '{file.name}' contient des fichiers non-médias.")
                            has_media_in_zip = True
                        if not has_media_in_zip:
                            raise ValidationError(f"Le fichier ZIP '{file.name}' ne contient aucun média valide.")
                        has_valid_file = True
                except zipfile.BadZipFile:
                    logger.error(f"Invalid ZIP file: {file.name}")
                    raise ValidationError(f"Le fichier ZIP '{file.name}' est invalide ou corrompu.")
                    
            elif file_extension in valid_image_extensions:
                # Valider taille image
                if file.size > 10 * 1024 * 1024:  # 10 MB
                    raise ValidationError(f"L'image '{file.name}' dépasse la limite de 10 Mo.")
                has_valid_file = True
                
            elif file_extension in valid_video_extensions:
                # Valider taille vidéo
                if file.size > 500 * 1024 * 1024:  # 500 MB
                    raise ValidationError(f"La vidéo '{file.name}' dépasse la limite de 500 Mo.")
                has_valid_file = True
                
            else:
                raise ValidationError(
                    f"Le fichier '{file.name}' doit être une image (JPG, PNG, WEBP, JFIF), "
                    f"une vidéo (MP4, AVI, MOV) ou un fichier ZIP."
                )

        if not has_valid_file:
            raise ValidationError("Aucun fichier valide n'a été fourni.")

        cleaned_data['files'] = files
        return cleaned_data

class SingleImageDetectionForm(forms.Form):
    image = forms.FileField(
        label="Image ou Vidéo à analyser",
        required=True,
        widget=forms.FileInput(attrs={
            'accept': 'image/jpeg,image/png,image/webp,image/jfif,video/mp4,video/avi,video/quicktime',
            'class': 'form-control'
        }),
        help_text="Sélectionnez une image (JPG, JPEG, PNG, WEBP, JFIF) ou une vidéo (MP4, AVI, MOV) pour analyse."
    )
    location = forms.CharField(
        label="Localisation",
        max_length=200,
        required=False,
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Lieu de la détection (optionnel)'}),
        help_text="Optionnel. Indiquez le lieu de la détection."
    )
    
    video_frame_interval = forms.IntegerField(
        label="Intervalle d'analyse vidéo (frames)",
        initial=30,
        min_value=1,
        max_value=300,
        required=False,
        widget=forms.NumberInput(attrs={
            'class': 'form-control',
            'min': '1',
            'max': '300',
            'value': '30'
        }),
        help_text="Pour les vidéos : analyser 1 frame toutes les X frames (30 = 1/sec pour 30 FPS)"
    )

    def clean(self):
        cleaned_data = super().clean()
        image = cleaned_data.get('image')
        logger.info(f"Form cleaning - File: {image.name if image else None}")

        if not image:
            raise ValidationError("Vous devez uploader un fichier.")

        # Normaliser le nom du fichier pour éviter les problèmes de casse
        file_extension = os.path.splitext(image.name.lower())[1]
        valid_image_extensions = ('.png', '.jpg', '.jpeg', '.webp', '.jfif')
        valid_video_extensions = ('.mp4', '.avi', '.mov', '.mkv', '.wmv', '.flv')
        
        if file_extension not in valid_image_extensions and file_extension not in valid_video_extensions:
            raise ValidationError(
                f"Le fichier '{image.name}' doit être une image (JPG, JPEG, PNG, WEBP, JFIF) "
                f"ou une vidéo (MP4, AVI, MOV)."
            )
        
        # Vérifier la taille max (500 MB pour vidéos, 10 MB pour images)
        if file_extension in valid_video_extensions:
            max_size = 500 * 1024 * 1024  # 500 MB
            if image.size > max_size:
                raise ValidationError(f"La vidéo '{image.name}' dépasse la limite de 500 Mo.")
        else:
            max_size = 10 * 1024 * 1024  # 10 MB
            if image.size > max_size:
                raise ValidationError(f"L'image '{image.name}' dépasse la limite de 10 Mo.")

        cleaned_data['files'] = [image]  # Normaliser pour la vue
        return cleaned_data


class ValidationForm(forms.ModelForm):
    class Meta:
        model = ModelValidation
        fields = ['is_correct', 'corrected_category', 'comments']
        widgets = {
            'is_correct': forms.RadioSelect(attrs={'class': 'form-check-input'}, choices=[(True, 'Détection correcte'), (False, 'Détection incorrecte')]),
            'corrected_category': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Catégorie réelle si incorrecte'}),
            'comments': forms.Textarea(attrs={'class': 'form-control', 'rows': 3, 'placeholder': 'Commentaires additionnels (optionnel)'})
        }

class CategoryForm(forms.ModelForm):
    class Meta:
        model = DangerousCategory
        fields = ['name', 'description', 'is_active']
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Nom de la catégorie'}),
            'description': forms.Textarea(attrs={'class': 'form-control', 'rows': 3, 'placeholder': 'Description de la catégorie'}),
            'is_active': forms.CheckboxInput(attrs={'class': 'form-check-input'})
        }


# ============ NOUVEAU FORMULAIRE UNIFIÉ POUR IMAGES ET VIDÉOS ============

class MultipleFileInput(forms.ClearableFileInput):
    """Custom widget pour supporter les uploads multiples"""
    allow_multiple_selected = True

class MultipleFileField(forms.FileField):
    """Custom field pour supporter les uploads multiples"""
    def __init__(self, *args, **kwargs):
        kwargs.setdefault("widget", MultipleFileInput())
        super().__init__(*args, **kwargs)

    def clean(self, data, initial=None):
        single_file_clean = super().clean
        if isinstance(data, (list, tuple)):
            result = [single_file_clean(d, initial) for d in data]
        else:
            result = single_file_clean(data, initial)
        return result

class UnifiedMediaDetectionForm(forms.Form):
    """Formulaire unifié pour images, vidéos et archives ZIP"""
    
    media_files = MultipleFileField(
        label="Fichiers média (Images, Vidéos ou ZIP)",
        required=True,
        widget=MultipleFileInput(attrs={
            'accept': 'image/jpeg,image/png,video/mp4,video/avi,video/quicktime,application/zip',
            'class': 'form-control',
            'id': 'mediaFiles'
        }),
        help_text="Formats : JPG, PNG (max 10 MB) | MP4, AVI, MOV (max 500 MB) | ZIP (max 100 MB)"
    )
    
    report_name = forms.CharField(
        label="Nom du Rapport",
        max_length=255,
        required=False,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'Ex: Surveillance Métro Ligne 1',
            'id': 'report_name'
        }),
        help_text="Nom optionnel pour identifier ce rapport"
    )
    
    location = forms.CharField(
        label="Localisation",
        max_length=255,
        required=False,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'Ex: Station Châtelet, Paris',
            'id': 'location'
        }),
        help_text="Lieu où la détection a été effectuée"
    )
    
    video_frame_interval = forms.IntegerField(
        label="Intervalle d'analyse vidéo (frames)",
        initial=30,
        min_value=1,
        max_value=300,
        required=False,
        widget=forms.NumberInput(attrs={
            'class': 'form-control',
            'min': '1',
            'max': '300',
            'id': 'video_frame_interval'
        }),
        help_text="1 frame analysée toutes les X frames. 30 ≈ 1 frame/sec pour 30 FPS"
    )