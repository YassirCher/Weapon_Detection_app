from django.shortcuts import render
from django.contrib.auth.decorators import login_required, user_passes_test
from django.db.models import Count, Avg, Sum, Case, When, IntegerField, F
from django.db.models.functions import TruncDay, TruncMonth
from django.utils import timezone
from datetime import timedelta
from apps.core.models import AppSettings
from apps.detection.models import DetectionLog, ModelValidation, DangerousCategory
from apps.users.models import User

def is_admin(user):
    return user.is_administrator

@login_required
@user_passes_test(is_admin)
def stats_view(request):
    """Vue des statistiques pour l'administrateur."""
    days = int(request.GET.get('days', 30))
    start_date = timezone.now() - timedelta(days=days)
    
    total_detections = DetectionLog.objects.count()
    total_dangerous = DetectionLog.objects.filter(contains_dangerous_category=True).count()
    total_validations = ModelValidation.objects.count()
    total_correct = ModelValidation.objects.filter(is_correct=True).count()
    
    accuracy_percentage = (total_correct / total_validations * 100) if total_validations > 0 else 0
    
    detections_by_day = (
        DetectionLog.objects
        .filter(detection_timestamp__gte=start_date)
        .annotate(day=TruncDay('detection_timestamp'))
        .values('day')
        .annotate(
            total=Count('id'),
            dangerous=Count(Case(When(contains_dangerous_category=True, then=1), output_field=IntegerField()))
        )
        .order_by('day')
    )
    
    category_stats = []
    for category in DangerousCategory.objects.all():
        validations_for_category = 0
        correct_validations_for_category = 0
        
        validations_for_category = ModelValidation.objects.count() // DangerousCategory.objects.count()
        correct_validations_for_category = ModelValidation.objects.filter(is_correct=True).count() // DangerousCategory.objects.count()
        
        category_accuracy = (correct_validations_for_category / validations_for_category * 100) if validations_for_category > 0 else 0
        
        category_stats.append({
            'name': category.name,
            'total_detections': validations_for_category,
            'correct_detections': correct_validations_for_category,
            'accuracy': category_accuracy
        })
    
    user_stats = (
        DetectionLog.objects
        .values('user__email', 'user__first_name', 'user__last_name', 'user__role')
        .annotate(
            total_detections=Count('id'),
            dangerous_detections=Count(Case(When(contains_dangerous_category=True, then=1), output_field=IntegerField()))
        )
        .order_by('-total_detections')
    )
    
    context = {
        'app_settings': AppSettings.load(),
        'total_detections': total_detections,
        'total_dangerous': total_dangerous,
        'total_validations': total_validations,
        'total_correct': total_correct,
        'accuracy_percentage': accuracy_percentage,
        'detections_by_day': list(detections_by_day),
        'category_stats': category_stats,
        'user_stats': user_stats,
        'days': days,
    }
    
    return render(request, 'dashboard/stats.html', context)

@login_required
@user_passes_test(is_admin)
def model_errors_view(request):
    """Vue des erreurs du modèle pour l'administrateur."""
    incorrect_validations = ModelValidation.objects.filter(is_correct=False).select_related('detection_log', 'validator')
    
    return render(request, 'dashboard/model_errors.html', {
        'app_settings': AppSettings.load(),
        'incorrect_validations': incorrect_validations
    })