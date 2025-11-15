from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib import messages
from django import forms
from .models import AppSettings

def is_admin(user):
    return user.is_administrator

class AppSettingsForm(forms.ModelForm):
    """Formulaire pour la configuration des paramètres de l'application."""
    class Meta:
        model = AppSettings
        fields = ['active_detection_model', 'active_chatbot_model', 'dangerous_threshold']
        widgets = {
            'active_detection_model': forms.Select(attrs={'class': 'form-select'}),
            'active_chatbot_model': forms.Select(attrs={'class': 'form-select'}),
            'dangerous_threshold': forms.NumberInput(attrs={'class': 'form-control', 'min': '0.1', 'max': '1.0', 'step': '0.05'}),
        }

    def clean_dangerous_threshold(self):
        threshold = self.cleaned_data['dangerous_threshold']
        if not 0.1 <= threshold <= 1.0:
            raise forms.ValidationError("Le seuil doit être entre 0.1 et 1.0.")
        return threshold

@login_required
@user_passes_test(is_admin)
def app_settings_view(request):
    """Vue pour afficher et modifier les paramètres de l'application."""
    settings = AppSettings.load()
    
    if request.method == 'POST':
        form = AppSettingsForm(request.POST, instance=settings)
        if form.is_valid():
            form.save()
            messages.success(request, "Les paramètres de l'application ont été mis à jour avec succès.")
            return redirect('core:settings')
        else:
            messages.error(request, "Une erreur s'est produite lors de la mise à jour des paramètres.")
    else:
        form = AppSettingsForm(instance=settings)
    
    # Utiliser les choix définis dans le modèle
    detection_models = AppSettings._meta.get_field('active_detection_model').choices
    chatbot_models = AppSettings._meta.get_field('active_chatbot_model').choices
    
    return render(request, 'core/settings.html', {
        'form': form,
        'settings': settings,
        'detection_models': detection_models,
        'chatbot_models': chatbot_models,
    })

@login_required
@user_passes_test(is_admin)
def update_app_settings(request):
    """Vue pour mettre à jour les paramètres de l'application."""
    if request.method == 'POST':
        settings = AppSettings.load()
        form = AppSettingsForm(request.POST, instance=settings)
        if form.is_valid():
            form.save()
            messages.success(request, "Les paramètres de l'application ont été mis à jour avec succès.")
            return redirect('core:settings')
        else:
            messages.error(request, "Une erreur s'est produite lors de la mise à jour des paramètres.")
    
    return redirect('core:settings')