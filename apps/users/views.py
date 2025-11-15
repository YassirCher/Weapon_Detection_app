from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.contrib.auth.decorators import user_passes_test
from django.urls import reverse
from django.http import HttpResponse
from .models import User
from .forms import LoginForm, UserProfileForm, UserCreationForm, UserEditForm
from apps.detection.models import DetectionLog, Report, DangerousCategory, ModelValidation
from django.utils import timezone
from datetime import datetime, timedelta
from django.db.models import Count, Q, Avg, Sum
from django.db.models.functions import TruncDate
import csv
import pdfkit
from io import BytesIO
from django.template.loader import render_to_string
import json
import logging

logger = logging.getLogger(__name__)

def login_view(request):
    """Vue de connexion utilisateur."""
    if request.user.is_authenticated:
        return redirect('users:home')  # Redirect to stats instead of profile
    
    if request.method == 'POST':
        form = LoginForm(request.POST)
        if form.is_valid():
            email = form.cleaned_data['email']
            password = form.cleaned_data['password']
            user = authenticate(request, email=email, password=password)
            
            if user is not None:
                login(request, user)
                messages.success(request, f'Bienvenue, {user.get_full_name() or user.email}!')
                next_page = request.GET.get('next', 'users:home')
                return redirect(next_page)
            else:
                messages.error(request, 'Email ou mot de passe incorrect.')
    else:
        form = LoginForm()
    
    return render(request, 'users/login.html', {'form': form})

@login_required
def logout_view(request):
    """Vue de déconnexion utilisateur."""
    logout(request)
    messages.info(request, 'Vous avez été déconnecté.')
    return redirect('users:login')

@login_required
def profile_view(request):
    """Vue du profil utilisateur."""
    if request.method == 'POST':
        form = UserProfileForm(request.POST, request.FILES, instance=request.user)
        if form.is_valid():
            form.save()
            messages.success(request, 'Votre profil a été mis à jour avec succès.')
            return redirect('users:profile')
        else:
            logger.error(f"Form errors: {form.errors}")
            messages.error(request, 'Erreur lors de la mise à jour du profil. Vérifiez les champs.')
    else:
        form = UserProfileForm(instance=request.user)
    
    return render(request, 'users/profile.html', {'form': form})


def is_admin(user):
    return user.is_administrator

@login_required
@user_passes_test(is_admin)
def manage_users(request):
    """Vue de gestion des utilisateurs (Admin uniquement)."""
    users = User.objects.all().order_by('role', 'email')
    return render(request, 'users/manage.html', {'users': users})

@login_required
@user_passes_test(is_admin)
def create_user(request):
    """Vue de création d'utilisateur (Admin uniquement)."""
    if request.method == 'POST':
        form = UserCreationForm(request.POST, request.FILES)
        if form.is_valid():
            user = form.save()
            messages.success(request, f'L\'utilisateur {user.email} a été créé avec succès.')
            return redirect('users:manage')
    else:
        form = UserCreationForm()
    
    return render(request, 'users/create_user.html', {'form': form})

@login_required
@user_passes_test(is_admin)
def edit_user(request, user_id):
    """Vue de modification d'utilisateur (Admin uniquement)."""
    user = get_object_or_404(User, id=user_id)
    
    if request.method == 'POST':
        form = UserEditForm(request.POST, request.FILES, instance=user)
        if form.is_valid():
            form.save()
            messages.success(request, f'L\'utilisateur {user.email} a été modifié avec succès.')
            return redirect('users:manage')
    else:
        form = UserEditForm(instance=user)
    
    return render(request, 'users/edit_user.html', {'form': form, 'user_obj': user})

@login_required
@user_passes_test(is_admin)
def delete_user(request, user_id):
    """Vue de suppression d'utilisateur (Admin uniquement)."""
    user = get_object_or_404(User, id=user_id)
    
    if user == request.user:
        messages.error(request, 'Vous ne pouvez pas supprimer votre propre compte.')
        return redirect('users:manage')
    
    if request.method == 'POST':
        email = user.email
        user.delete()
        messages.success(request, f'L\'utilisateur {email} a été supprimé avec succès.')
        return redirect('users:manage')
    
    return render(request, 'users/delete_user.html', {'user_obj': user})

@login_required
def stats_view(request):
    """Vue des statistiques générales."""
    # Initialize filters
    filter_type = request.GET.get('filter', 'all')
    start_date = request.GET.get('start_date')
    end_date = request.GET.get('end_date')
    operator_id = request.GET.get('operator_id')  # For supervisors
    today = timezone.now().date()
    
    # Base querysets
    detections_qs = DetectionLog.objects.all()
    if request.user.is_supervisor and operator_id:
        detections_qs = detections_qs.filter(user_id=operator_id)
    elif not request.user.is_supervisor and not request.user.is_administrator:
        detections_qs = detections_qs.filter(user=request.user)
    
    # Apply temporal filters
    if filter_type == 'day':
        detections_qs = detections_qs.filter(detection_timestamp__date=today)
    elif filter_type == 'week':
        week_start = today - timedelta(days=today.weekday())
        detections_qs = detections_qs.filter(detection_timestamp__date__gte=week_start)
    elif filter_type == 'month':
        month_start = today.replace(day=1)
        detections_qs = detections_qs.filter(detection_timestamp__date__gte=month_start)
    elif filter_type == 'custom' and start_date and end_date:
        try:
            start = datetime.strptime(start_date, '%Y-%m-%d').date()
            end = datetime.strptime(end_date, '%Y-%m-%d').date()
            detections_qs = detections_qs.filter(detection_timestamp__date__range=[start, end])
        except ValueError:
            messages.error(request, 'Format de date invalide.')
    
    # General statistics
    total_detections = detections_qs.count()
    total_reports = Report.objects.filter(detections__in=detections_qs).distinct().count()
    
    # ==================== NOUVELLES STATS: Différenciation Images/Vidéos ====================
    total_images = detections_qs.filter(media_type='IMAGE').count()
    total_videos = detections_qs.filter(media_type='VIDEO').count()
    
    # Stats de danger par type de média
    dangerous_images = detections_qs.filter(media_type='IMAGE', danger_level='DANGEROUS').count()
    hyperdangerous_images = detections_qs.filter(media_type='IMAGE', danger_level='HYPERDANGEROUS').count()
    safe_images = detections_qs.filter(media_type='IMAGE', danger_level__isnull=True).count()
    
    dangerous_videos = detections_qs.filter(media_type='VIDEO', danger_level='DANGEROUS').count()
    hyperdangerous_videos = detections_qs.filter(media_type='VIDEO', danger_level='HYPERDANGEROUS').count()
    safe_videos = detections_qs.filter(media_type='VIDEO', danger_level__isnull=True).count()
    
    # Temps de traitement moyen (vidéos)
    avg_processing_time = detections_qs.filter(media_type='VIDEO', processing_duration__gt=0).aggregate(
        avg_time=Avg('processing_duration')
    )['avg_time'] or 0
    
    # Nombre total de frames analysées (vidéos)
    total_frames_analyzed = detections_qs.filter(media_type='VIDEO').aggregate(
        total=Sum('frames_analyzed')
    )['total'] or 0
    
    # Taux de détection (% de détections avec objets dangereux)
    detections_with_danger = detections_qs.filter(danger_level__isnull=False).count()
    danger_rate = (detections_with_danger / total_detections * 100) if total_detections > 0 else 0
    
    # Count categories from detected_objects JSON (séparé par type)
    category_counts = {}
    category_counts_images = {}
    category_counts_videos = {}
    valid_categories = set(DangerousCategory.objects.values_list('name', flat=True))
    
    for detection in detections_qs:
        if detection.detected_objects:
            try:
                objects = json.loads(detection.detected_objects) if isinstance(detection.detected_objects, str) else detection.detected_objects
                for obj in objects:
                    category = obj.get('category')
                    if category in valid_categories:
                        category_counts[category] = category_counts.get(category, 0) + 1
                        
                        # Compteurs séparés
                        if detection.media_type == 'IMAGE':
                            category_counts_images[category] = category_counts_images.get(category, 0) + 1
                        elif detection.media_type == 'VIDEO':
                            category_counts_videos[category] = category_counts_videos.get(category, 0) + 1
            except (json.JSONDecodeError, TypeError):
                continue
    
    categories_count = [
        {'name': name, 'count': count}
        for name, count in sorted(category_counts.items(), key=lambda x: x[1], reverse=True)
    ]
    
    # Validation stats
    valid_detections = detections_qs.filter(validation__is_correct=True).count()
    invalid_detections = detections_qs.filter(validation__is_correct=False).count()
    incorrect_detections = detections_qs.filter(
        validation__is_correct=False, validation__corrected_category__isnull=False
    ).count()
    
    # Today's detections
    today_detections = detections_qs.filter(detection_timestamp__date=today).count()
    
    # Day with most detections
    max_detection_day = detections_qs.annotate(
        date=TruncDate('detection_timestamp')
    ).values('date').annotate(count=Count('id')).order_by('-count').first()
    
    # Daily detections for line chart
    daily_detections = detections_qs.annotate(
        date=TruncDate('detection_timestamp')
    ).values('date').annotate(count=Count('id')).order_by('date')
    
    # Chart data
    donut_data = {
        'labels': ['Valides', 'Non valides', 'Incorrectes'],
        'data': [valid_detections, invalid_detections, incorrect_detections]
    }
    
    line_data = {
        'labels': [entry['date'].strftime('%Y-%m-%d') if entry['date'] else '' for entry in daily_detections],
        'data': [entry['count'] for entry in daily_detections]
    }
    
    bar_category_data = {
        'labels': [entry['name'] for entry in categories_count],
        'data': [entry['count'] for entry in categories_count]
    }
    
    # Supervisor-specific: Operator selection
    operators = User.objects.filter(role=User.Role.OPERATOR) if request.user.is_supervisor else []
    
    # Export functionality
    if request.GET.get('export') == 'csv':
        response = HttpResponse(content_type='text/csv')
        response['Content-Disposition'] = 'attachment; filename="stats.csv"'
        writer = csv.writer(response)
        writer.writerow(['Statistique', 'Valeur'])
        writer.writerow(['Total Detections', total_detections])
        writer.writerow(['Total Reports', total_reports])
        writer.writerow(['Valid Detections', valid_detections])
        writer.writerow(['Invalid Detections', invalid_detections])
        writer.writerow(['Incorrect Detections', incorrect_detections])
        writer.writerow(['Today\'s Detections', today_detections])
        if max_detection_day:
            writer.writerow(['Day with Most Detections', f"{max_detection_day['date']} ({max_detection_day['count']})"])
        writer.writerow(['Category', 'Count'])
        for category in categories_count:
            writer.writerow([category['name'], category['count']])
        return response
    
    if request.GET.get('export') == 'pdf':
        try:
            # Configure wkhtmltopdf path explicitly
            config = pdfkit.configuration(wkhtmltopdf=r'C:\Program Files\wkhtmltopdf\bin\wkhtmltopdf.exe')
            html = render_to_string('users/stats_pdf.html', {
                'total_detections': total_detections,
                'total_reports': total_reports,
                'valid_detections': valid_detections,
                'invalid_detections': invalid_detections,
                'incorrect_detections': incorrect_detections,
                'today_detections': today_detections,
                'max_detection_day': max_detection_day,
                'categories_count': categories_count,
            })
            pdf = pdfkit.from_string(html, False, configuration=config)
            response = HttpResponse(pdf, content_type='application/pdf')
            response['Content-Disposition'] = 'attachment; filename="stats.pdf"'
            return response
        except OSError as e:
            logger.error(f"PDF generation failed: {str(e)}")
            messages.error(request, "Erreur lors de la génération du PDF. Vérifiez que wkhtmltopdf est installé et accessible.")
            return render(request, 'users/stats.html', context)
    
    # Nouvelles données pour graphiques
    media_type_data = {
        'labels': ['Images', 'Vidéos'],
        'data': [total_images, total_videos]
    }
    
    danger_by_media_data = {
        'labels': ['Sécurisées', 'Dangereuses', 'Hyperdangereuses'],
        'images': [safe_images, dangerous_images, hyperdangerous_images],
        'videos': [safe_videos, dangerous_videos, hyperdangerous_videos]
    }
    
    context = {
        'total_detections': total_detections,
        'total_reports': total_reports,
        'categories_count': categories_count,
        'valid_detections': valid_detections,
        'invalid_detections': invalid_detections,
        'incorrect_detections': incorrect_detections,
        'today_detections': today_detections,
        'max_detection_day': max_detection_day,
        'donut_data': donut_data,
        'line_data': line_data,
        'bar_category_data': bar_category_data,
        'operators': operators,
        'selected_operator': operator_id,
        'filter_type': filter_type,
        'start_date': start_date,
        'end_date': end_date,
        # ==================== NOUVELLES STATS ====================
        'total_images': total_images,
        'total_videos': total_videos,
        'dangerous_images': dangerous_images,
        'hyperdangerous_images': hyperdangerous_images,
        'safe_images': safe_images,
        'dangerous_videos': dangerous_videos,
        'hyperdangerous_videos': hyperdangerous_videos,
        'safe_videos': safe_videos,
        'avg_processing_time': round(avg_processing_time, 2),
        'total_frames_analyzed': total_frames_analyzed,
        'danger_rate': round(danger_rate, 1),
        'detections_with_danger': detections_with_danger,
        'media_type_data': media_type_data,
        'danger_by_media_data': danger_by_media_data,
        'category_counts_images': category_counts_images,
        'category_counts_videos': category_counts_videos,
    }
    
    return render(request, 'users/stats.html', context)

