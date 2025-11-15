from django.shortcuts import render, redirect, get_object_or_404, HttpResponse 
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.contrib.auth.decorators import user_passes_test
from django.http import HttpResponseForbidden, JsonResponse
from django.core.paginator import Paginator
from django.utils import timezone
import os
import json
import re
import zipfile
import tempfile
from .models import DangerousCategory, DetectionLog, ModelValidation, Report, CategoryValidation
from .forms import UploadDetectionForm , SingleImageDetectionForm , ValidationForm, CategoryForm
from .utils import run_detection
from apps.chatbot.services import get_chatbot_instructions
from apps.users.models import User
from django.conf import settings
import logging
import requests
import google.generativeai as genai
from django.template.loader import render_to_string
from datetime import datetime
import subprocess
from django.http import HttpResponseForbidden
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from django.db.models import Count, Q
import time

def is_supervisor_or_admin(user):
    return user.is_supervisor or user.is_administrator

def is_admin(user):
    return user.is_administrator

logger = logging.getLogger(__name__)


@login_required
def upload_detection(request):
    from .utils import is_video_file, is_image_file, run_video_detection
    
    if request.method == 'POST':
        form = SingleImageDetectionForm(request.POST, request.FILES)
        logger.info("Received POST request for file upload")
        if form.is_valid():
            uploaded_file = form.cleaned_data.get('image')
            location = form.cleaned_data.get('location', '')
            frame_interval = form.cleaned_data.get('video_frame_interval', 30)
            logger.info(f"Received file: {uploaded_file.name}, size: {uploaded_file.size}, type: {uploaded_file.content_type}")
            
            filename = re.sub(r'[^\w\-\. ]', '_', uploaded_file.name)
            now = timezone.now()
            relative_path = f"uploads/{now.year}/{now.month:02d}/{now.day:02d}/{filename}"
            full_path = os.path.join(settings.MEDIA_ROOT, relative_path)

            try:
                os.makedirs(os.path.dirname(full_path), exist_ok=True)
                logger.info(f"Attempting to save file to: {full_path}")
                with open(full_path, 'wb+') as destination:
                    for chunk in uploaded_file.chunks():
                        destination.write(chunk)
                if not os.path.exists(full_path):
                    logger.error(f"File not saved at: {full_path}")
                    messages.error(request, "Échec de l'enregistrement du fichier.")
                    return redirect('detection:upload')
                logger.info(f"File saved to: {full_path}")
            except Exception as e:
                logger.error(f"Failed to save file: {str(e)}")
                messages.error(request, f"Erreur lors de l'enregistrement du fichier : {str(e)}")
                return redirect('detection:upload')

            annotated_relative_path = f"detection_results/{now.year}/{now.month:02d}/{now.day:02d}/{filename}"
            annotated_full_path = os.path.join(settings.MEDIA_ROOT, annotated_relative_path)
            os.makedirs(os.path.dirname(annotated_full_path), exist_ok=True)

            try:
                start_time = time.time()
                
                # Déterminer si c'est une vidéo ou une image
                if is_video_file(filename):
                    logger.info(f"[VIDEO] Processing: {filename}")
                    detected_objects, danger_level, model_used, video_metadata, frames_analyzed = run_video_detection(
                        full_path,
                        annotated_full_path,
                        frame_interval=frame_interval
                    )
                    processing_duration = time.time() - start_time
                    media_type = 'VIDEO'
                    
                else:  # Image
                    logger.info(f"[IMAGE] Processing: {filename}")
                    detected_objects, danger_level, model_used = run_detection(full_path, annotated_full_path)
                    processing_duration = time.time() - start_time
                    media_type = 'IMAGE'
                    video_metadata = None
                    frames_analyzed = 0  # 0 pour les images au lieu de None
                
                logger.debug(f"Detected objects: {detected_objects}")
                if detected_objects and detected_objects[0].get("category") == "error":
                    logger.error("Detection returned error object")
                    messages.error(request, "Erreur lors de la détection : modèle non chargé.")
                    return redirect('detection:upload')

                normalized_objects = []
                for obj in detected_objects:
                    category = obj.get('category') or obj.get('label') or obj.get('class_name')
                    if category and isinstance(category, str) and category.strip():
                        obj_data = {
                            'category': category.strip().lower(),
                            'confidence': float(obj.get('confidence', 0.0))
                        }
                        # Ajouter frame et timestamp pour les vidéos
                        if media_type == 'VIDEO':
                            if 'frame' in obj:
                                obj_data['frame'] = obj['frame']
                            if 'timestamp' in obj:
                                obj_data['timestamp'] = obj['timestamp']
                        normalized_objects.append(obj_data)
                    else:
                        logger.warning(f"Invalid object in detection: {obj}")
                detected_objects = normalized_objects

                detection_log = DetectionLog.objects.create(
                    user=request.user,
                    media_type=media_type,
                    uploaded_file=annotated_relative_path,
                    original_file=relative_path,
                    user_location=location,
                    detected_objects=detected_objects,
                    danger_level=danger_level,
                    model_used=model_used,
                    is_simulated=True if model_used == "simulation" else False,
                    video_metadata=video_metadata,
                    frames_analyzed=frames_analyzed if frames_analyzed is not None else 0,
                    processing_duration=processing_duration
                )

                messages.success(request, "Détection terminée avec succès.")
                return redirect('detection:result', detection_id=detection_log.id)

            except Exception as e:
                logger.error(f"Detection failed: {str(e)}", exc_info=True)
                messages.error(request, f"Erreur lors de la détection : {str(e)}")
                return redirect('detection:upload')
        else:
            logger.error(f"Form invalid: {form.errors}")
            messages.error(request, f"Formulaire invalide : {form.errors}")
    else:
        form = SingleImageDetectionForm(initial={'location': ''})

    return render(request, 'detection/upload.html', {'form': form})


def generate_unique_filename(base_name, ext, directory, idx=0):
    """Generate a unique filename by appending an index or timestamp if the file exists."""
    filename = f"{base_name}_{idx}{ext}" if idx > 0 else f"{base_name}{ext}"
    full_path = os.path.join(directory, filename)
    if os.path.exists(full_path):
        timestamp = int(time.time())
        filename = f"{base_name}_{timestamp}{ext}"
        full_path = os.path.join(directory, filename)
        if os.path.exists(full_path):
            return generate_unique_filename(base_name, ext, directory, idx + 1)
    return filename


@login_required
def upload_multi_detection(request):
    from .utils import is_video_file, is_image_file, run_video_detection
    
    if request.method == 'POST':
        form = UploadDetectionForm(request.POST, request.FILES)
        if form.is_valid():
            files = form.cleaned_data['files']
            location = form.cleaned_data.get('location', '')
            report_name = form.cleaned_data.get('report_name', '')
            frame_interval = form.cleaned_data.get('video_frame_interval', 30)
            now = timezone.now()

            report = Report.objects.create(
                user=request.user,
                location=location,
                name=report_name or f"Report {now.strftime('%Y-%m-%d %H:%M:%S')}"
            )
            logger.info(f"Created Report ID: {report.id}, Name: {report.name}")

            detection_logs = []
            files_to_process = []

            if len(files) == 1 and files[0].name.lower().endswith('.zip'):
                # Process ZIP file
                file = files[0]
                with tempfile.TemporaryDirectory() as temp_dir:
                    zip_path = os.path.join(temp_dir, file.name)
                    logger.info(f"Saving ZIP to temporary path: {zip_path}")
                    with open(zip_path, 'wb+') as destination:
                        for chunk in file.chunks():
                            destination.write(chunk)
                    logger.info(f"Extracting ZIP: {file.name}")
                    with zipfile.ZipFile(zip_path, 'r') as zip_ref:
                        zip_ref.extractall(temp_dir)
                        file_list = zip_ref.namelist()
                        logger.info(f"ZIP contains {len(file_list)} files: {file_list}")
                        for zip_idx, zip_file_name in enumerate(file_list):
                            if zip_file_name.endswith('/') or not os.path.splitext(zip_file_name)[1]:
                                logger.info(f"Skipping directory in ZIP: {zip_file_name}")
                                continue
                            file_ext = os.path.splitext(zip_file_name.lower())[1]
                            if file_ext in ('.png', '.jpg', '.jpeg', '.webp', '.jfif', '.mp4', '.avi', '.mov', '.mkv', '.wmv', '.flv'):
                                file_path = os.path.join(temp_dir, zip_file_name)
                                base_name = re.sub(r'[^\w\-\s. ]', '_', os.path.splitext(os.path.basename(zip_file_name))[0])
                                ext = os.path.splitext(zip_file_name)[1]
                                filename = generate_unique_filename(
                                    base_name,
                                    ext,
                                    os.path.join(settings.MEDIA_ROOT, f"uploads/{now.year}/{now.month:02d}/{now.day:02d}"),
                                    zip_idx
                                )
                                relative_path = f"uploads/{now.year}/{now.month:02d}/{now.day:02d}/{filename}"
                                full_path = os.path.join(settings.MEDIA_ROOT, relative_path)
                                os.makedirs(os.path.dirname(full_path), exist_ok=True)
                                logger.info(f"Moving {file_path} to {full_path}")
                                try:
                                    os.rename(file_path, full_path)
                                except FileExistsError:
                                    logger.warning(f"File {full_path} already exists, skipping")
                                    continue
                                files_to_process.append((filename, relative_path, full_path))
                            else:
                                logger.warning(f"Skipping unsupported file in ZIP: {zip_file_name}")
            else:
                # Process multiple images/videos
                for idx, file in enumerate(files):
                    base_name = re.sub(r'[^\w\-\s. ]', '_', os.path.splitext(file.name)[0])
                    ext = os.path.splitext(file.name)[1]
                    filename = generate_unique_filename(
                        base_name,
                        ext,
                        os.path.join(settings.MEDIA_ROOT, f"uploads/{now.year}/{now.month:02d}/{now.day:02d}"),
                        idx
                    )
                    relative_path = f"uploads/{now.year}/{now.month:02d}/{now.day:02d}/{filename}"
                    full_path = os.path.join(settings.MEDIA_ROOT, relative_path)
                    os.makedirs(os.path.dirname(full_path), exist_ok=True)
                    with open(full_path, 'wb+') as destination:
                        for chunk in file.chunks():
                            destination.write(chunk)
                    files_to_process.append((filename, relative_path, full_path))

            # Process files
            for idx, (filename, relative_path, full_path) in enumerate(files_to_process):
                logger.info(f"Processing file {idx+1}: {filename}")
                annotated_relative_path = f"detection_results/{now.year}/{now.month:02d}/{now.day:02d}/{filename}"
                annotated_full_path = os.path.join(settings.MEDIA_ROOT, annotated_relative_path)
                os.makedirs(os.path.dirname(annotated_full_path), exist_ok=True)

                try:
                    start_time = time.time()
                    
                    # Déterminer si c'est une vidéo ou une image
                    if is_video_file(filename):
                        logger.info(f"[VIDEO] Processing: {filename}")
                        detected_objects, danger_level, model_used, video_metadata, frames_analyzed = run_video_detection(
                            full_path,
                            annotated_full_path,
                            frame_interval=frame_interval
                        )
                        processing_duration = time.time() - start_time
                        media_type = 'VIDEO'
                    else:
                        logger.info(f"[IMAGE] Processing: {filename}")
                        detected_objects, danger_level, model_used = run_detection(full_path, annotated_full_path)
                        processing_duration = time.time() - start_time
                        media_type = 'IMAGE'
                        video_metadata = None
                        frames_analyzed = 0  # 0 pour les images au lieu de None
                    
                    logger.debug(f"Detected objects for {filename}: {detected_objects}")
                    if detected_objects and detected_objects[0].get("category") == "error":
                        logger.error(f"Detection error for {filename}")
                        continue

                    normalized_objects = []
                    for obj in detected_objects:
                        category = obj.get('category') or obj.get('label') or obj.get('class_name')
                        if category and isinstance(category, str) and category.strip():
                            obj_data = {
                                'category': category.strip().lower(),
                                'confidence': float(obj.get('confidence', 0.0))
                            }
                            # Ajouter frame et timestamp pour les vidéos
                            if media_type == 'VIDEO':
                                if 'frame' in obj:
                                    obj_data['frame'] = obj['frame']
                                if 'timestamp' in obj:
                                    obj_data['timestamp'] = obj['timestamp']
                            normalized_objects.append(obj_data)
                        else:
                            logger.warning(f"Invalid object in detection for {filename}: {obj}")
                    detected_objects = normalized_objects

                    detection_log = DetectionLog.objects.create(
                        user=request.user,
                        report=report,
                        media_type=media_type,
                        uploaded_file=annotated_relative_path,
                        original_file=relative_path,
                        user_location=location,
                        detected_objects=detected_objects,
                        danger_level=danger_level,
                        model_used=model_used,
                        is_simulated=True if model_used == "simulation" else False,
                        video_metadata=video_metadata,
                        frames_analyzed=frames_analyzed if frames_analyzed is not None else 0,
                        processing_duration=processing_duration
                    )
                    detection_logs.append(detection_log)
                    logger.info(f"Created DetectionLog ID: {detection_log.id} for {filename}")
                except Exception as e:
                    logger.error(f"Detection failed for {filename}: {str(e)}", exc_info=True)
                    messages.warning(request, f"Échec de la détection pour {filename}: {str(e)}")
                    continue

            if not detection_logs:
                report.delete()
                messages.error(request, "Aucune détection valide n'a été effectuée. Veuillez vérifier vos fichiers.")
                return render(request, 'detection/upload_multi.html', {'form': form})

            messages.success(request, f"{len(detection_logs)} détection(s) terminée(s) avec succès.")
            return redirect('detection:analysis_results', report_id=report.id)

        else:
            logger.error(f"Form invalid: {form.errors}")
            messages.error(request, f"Formulaire invalide : {form.errors}")
    else:
        form = UploadDetectionForm(initial={'location': ''})

    return render(request, 'detection/upload_multi.html', {'form': form})


@login_required
def analysis_results(request, report_id):
    report = get_object_or_404(Report, id=report_id)
    if report.user != request.user and not is_supervisor_or_admin(request.user):
        return HttpResponseForbidden("Vous n'avez pas la permission de voir ce rapport.")
    
    detections = report.detections.all()
    
    # Calcul des classes détectées avec occurrences
    class_counts = {}
    for detection in detections:
        for obj in detection.detected_objects:
            category = obj.get('category')
            if category and isinstance(category, str) and category.strip():
                category = category.strip().lower()
                class_counts[category] = class_counts.get(category, 0) + 1
    class_choices = [(cls, f"{cls.capitalize()} ({count})") for cls, count in class_counts.items()]
    
    # Filtrage par classe
    class_filter = request.GET.get('class_filter', '').strip().lower()
    if class_filter:
        filtered_detection_ids = []
        for detection in detections:
            for obj in detection.detected_objects:
                category = obj.get('category', '').lower()
                if category == class_filter:
                    filtered_detection_ids.append(detection.id)
                    break
        detections = detections.filter(id__in=filtered_detection_ids)
    
    # Pagination
    paginator = Paginator(detections, 6)
    page_number = request.GET.get('page', 1)
    page_obj = paginator.get_page(page_number)

    # Statistiques
    stats = {
        'normal': detections.filter(danger_level__isnull=True).count(),
        'dangerous': detections.filter(danger_level='DANGEROUS').count(),
        'hyperdangerous': detections.filter(danger_level='HYPERDANGEROUS').count()
    }
    dangerous_categories = list(DangerousCategory.objects.filter(is_active=True).values_list('name', flat=True))

    context = {
        'report': report,
        'detections': page_obj,
        'stats': stats,
        'validation_form': ValidationForm(),
        'dangerous_categories': dangerous_categories,
        'dangerous_categories_json': json.dumps(dangerous_categories),
        'class_choices': class_choices,
        'class_filter': class_filter,
    }
    return render(request, 'detection/analysis_results.html', context)

@login_required
def download_report_pdf(request, report_id):
    report = get_object_or_404(Report, id=report_id)
    if report.user != request.user and not is_supervisor_or_admin(request.user):
        return HttpResponseForbidden("Vous n'avez pas la permission de voir ce rapport.")
    
    detections = report.detections.all()
    stats = {
        'normal': detections.filter(danger_level__isnull=True).count(),
        'dangerous': detections.filter(danger_level='DANGEROUS').count(),
        'hyperdangerous': detections.filter(danger_level='HYPERDANGEROUS').count()
    }
    dangerous_categories = list(DangerousCategory.objects.filter(is_active=True).values_list('name', flat=True))
    categories = {}
    for detection in detections:
        for obj in detection.detected_objects:
            category = obj.get('category') or obj.get('label') or obj.get('class_name')
            if category and isinstance(category, str):
                category = category.strip().lower()
                categories[category] = categories.get(category, 0) + 1
            else:
                logger.warning(f"Object without valid category in Detection ID {detection.id}: {obj}")

    # Créer la réponse HTTP pour le PDF
    response = HttpResponse(content_type='application/pdf')
    
    # --- LA CORRECTION EST ICI ---
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    response['Content-Disposition'] = f'attachment; filename="rapport_{report.id}_{timestamp}.pdf"'
    # --- FIN DE LA CORRECTION ---

    # Configurer le document PDF
    doc = SimpleDocTemplate(response, pagesize=A4, rightMargin=inch, leftMargin=inch, topMargin=inch, bottomMargin=inch)
    elements = []
    styles = getSampleStyleSheet()

    # Définir des styles personnalisés
    title_style = ParagraphStyle(name='Title', fontSize=24, spaceAfter=12, alignment=1)
    subtitle_style = ParagraphStyle(name='Subtitle', fontSize=14, spaceAfter=6, alignment=1)
    heading_style = ParagraphStyle(name='Heading', fontSize=16, spaceAfter=12)
    normal_style = styles['Normal']
    normal_style.spaceAfter = 6

    # Page de titre
    elements.append(Paragraph("Rapport d'Analyse de Sécurité Urbaine", title_style))
    elements.append(Spacer(1, 0.5 * inch))
    elements.append(Paragraph(f"Rapport ID: {report.id}", subtitle_style))
    elements.append(Paragraph(f"Nom du Rapport: {report.name}", subtitle_style))
    elements.append(Paragraph(f"Date de Génération: {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}", subtitle_style))
    elements.append(Spacer(1, 0.5 * inch))
    elements.append(Paragraph("Préparé par: Système de Sécurité Urbaine", subtitle_style))
    elements.append(Spacer(1, 2 * inch))

    # Résumé des statistiques
    elements.append(Paragraph("Résumé des Statistiques", heading_style))
    elements.append(Paragraph(f"Normale: {stats['normal']} détections", normal_style))
    elements.append(Paragraph(f"Dangereuse: {stats['dangerous']} détections", normal_style))
    elements.append(Paragraph(f"Hyperdangereuse: {stats['hyperdangerous']} détections", normal_style))
    elements.append(Spacer(1, 0.5 * inch))

    # Catégories détectées
    elements.append(Paragraph("Catégories Détectées", heading_style))
    if categories:
        category_data = [['Catégorie', 'Nombre d\'Instances']]
        for category, count in categories.items():
            category_data.append([category, count])
        category_table = Table(category_data, colWidths=[3 * inch, 2 * inch])
        category_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.grey),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, 0), 12),
            ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
            ('BACKGROUND', (0, 1), (-1, -1), colors.beige),
            ('GRID', (0, 0), (-1, -1), 1, colors.black),
        ]))
        elements.append(category_table)
    else:
        elements.append(Paragraph("Aucune catégorie détectée.", normal_style))
    elements.append(Spacer(1, 0.5 * inch))

    # Détails des détections
    elements.append(Paragraph("Détails des Détections", heading_style))
    if detections:
        detection_data = [['Niveau de Danger', 'Date/Heure', 'Objets Détectés', 'Validation']]
        for detection in detections:
            danger_level = detection.danger_level or "Normale"
            if detection.is_simulated:
                danger_level += " (Simulé)"
            objects = ", ".join([
                f"{obj.get('category', 'Inconnu')} ({obj.get('confidence', 0):.2f})"
                for obj in detection.detected_objects
            ]) or "Aucun"
            try:
                validation_obj = detection.validation
                validation = (
                    "Correcte" if validation_obj.is_correct
                    else f"Incorrecte ({validation_obj.corrected_category or 'Non spécifié'})"
                )
            except detection.__class__.validation.RelatedObjectDoesNotExist:
                validation = "Non validé"
            detection_data.append([
                danger_level,
                detection.detection_timestamp.strftime("%d/%m/%Y %H:%M"),
                objects,
                validation
            ])
        detection_table = Table(detection_data, colWidths=[1.5 * inch, 1.5 * inch, 2 * inch, 2 * inch])
        detection_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.grey),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, 0), 12),
            ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
            ('BACKGROUND', (0, 1), (-1, -1), colors.beige),
            ('GRID', (0, 0), (-1, -1), 1, colors.black),
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ]))
        elements.append(detection_table)
    else:
        elements.append(Paragraph("Aucune détection dans ce rapport.", normal_style))

    # Générer le PDF
    try:
        doc.build(elements)
    except Exception as e:
        logger.error(f"Erreur lors de la génération du PDF avec reportlab: {str(e)}")
        return HttpResponse("Erreur lors de la génération du PDF.", status=500)

    return response

@login_required
def reports_history(request):
    # Récupérer les rapports en fonction des permissions
    if request.user.is_administrator or request.user.is_supervisor:
        reports = Report.objects.all().order_by('-created_at')
        all_reports = Report.objects.all()
    else:
        reports = Report.objects.filter(user=request.user).order_by('-created_at')
        all_reports = Report.objects.filter(user=request.user)

    # Récupérer les paramètres de filtrage
    name_filter = request.GET.get('name', '').strip()
    user_filter = request.GET.get('user', '')
    location_filter = request.GET.get('location', '')
    date_from = request.GET.get('date_from', '')
    date_to = request.GET.get('date_to', '')
    danger_level_filter = request.GET.get('danger_level', '')
    class_filter = request.GET.get('class', '')

    # Appliquer les filtres
    if name_filter:
        reports = reports.filter(name__icontains=name_filter)

    if user_filter and is_supervisor_or_admin(request.user):
        try:
            user_id = int(user_filter)
            reports = reports.filter(user_id=user_id)
        except ValueError:
            pass

    if location_filter:
        reports = reports.filter(location=location_filter)

    if date_from:
        try:
            date_from = datetime.strptime(date_from, '%Y-%m-%d')
            reports = reports.filter(created_at__gte=date_from)
        except ValueError:
            pass

    if date_to:
        try:
            date_to = datetime.strptime(date_to, '%Y-%m-%d')
            reports = reports.filter(created_at__lte=date_to)
        except ValueError:
            pass

    if danger_level_filter:
        if danger_level_filter == 'normal':
            reports = reports.filter(detections__danger_level__isnull=True).distinct()
        else:
            reports = reports.filter(detections__danger_level=danger_level_filter.upper()).distinct()

    if class_filter:
        filtered_report_ids = []
        for report in reports:
            for detection in report.detections.all():
                for obj in detection.detected_objects:
                    category = (obj.get('category') or obj.get('label') or obj.get('class_name') or '').lower()
                    if category == class_filter.lower():
                        filtered_report_ids.append(report.id)
                        break
        reports = reports.filter(id__in=filtered_report_ids)

    # Récupérer les localisations avec le nombre d'occurrences
    locations = (
        all_reports.values('location')
        .annotate(count=Count('id'))
        .exclude(location='')
        .order_by('location')
    )
    location_choices = [(loc['location'], f"{loc['location']} ({loc['count']})") for loc in locations]

    # Récupérer les niveaux de danger avec le nombre d'occurrences
    danger_levels = [
        {'level': 'normal', 'count': all_reports.filter(detections__danger_level__isnull=True).distinct().count()},
        {'level': 'dangerous', 'count': all_reports.filter(detections__danger_level='DANGEROUS').distinct().count()},
        {'level': 'hyperdangerous', 'count': all_reports.filter(detections__danger_level='HYPERDANGEROUS').distinct().count()},
    ]
    danger_level_choices = [(dl['level'], f"{dl['level'].capitalize()} ({dl['count']})") for dl in danger_levels if dl['count'] > 0]

    # Récupérer les classes détectées avec le nombre d'occurrences
    class_counts = {}
    for report in all_reports:
        for detection in report.detections.all():
            for obj in detection.detected_objects:
                category = (obj.get('category') or obj.get('label') or obj.get('class_name') or '').lower()
                if category:
                    class_counts[category] = class_counts.get(category, 0) + 1
    class_choices = [(cls, f"{cls.capitalize()} ({count})") for cls, count in class_counts.items()]

    # Pagination
    paginator = Paginator(reports, 10)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    # Ajouter les statistiques pour chaque rapport
    for report in page_obj:
        detections = report.detections.all()
        report.stats = {
            'normal': detections.filter(danger_level__isnull=True).count(),
            'dangerous': detections.filter(danger_level='DANGEROUS').count(),
            'hyperdangerous': detections.filter(danger_level='HYPERDANGEROUS').count(),
            'total': detections.count()
        }
        report.preview_detections = detections[:3]

    # Récupérer la liste des utilisateurs pour le filtre (si admin ou superviseur)
    users = User.objects.all().order_by('email') if is_supervisor_or_admin(request.user) else None

    return render(request, 'detection/reports_history.html', {
        'page_obj': page_obj,
        'users': users,
        'name_filter': name_filter,
        'user_filter': user_filter,
        'location_filter': location_filter,
        'date_from': date_from,
        'date_to': date_to,
        'danger_level_filter': danger_level_filter,
        'class_filter': class_filter,
        'location_choices': location_choices,
        'danger_level_choices': danger_level_choices,
        'class_choices': class_choices,
    })

@login_required
def detection_result(request, detection_id):
    detection = get_object_or_404(DetectionLog, id=detection_id)
    if detection.user != request.user and not is_supervisor_or_admin(request.user):
        return HttpResponseForbidden("Vous n'avez pas la permission de voir cette détection.")
    
    chatbot_response, chatbot_model = get_chatbot_instructions(detection.detected_objects)
    
    try:
        validation = detection.validation
        validation_form = None
    except ModelValidation.DoesNotExist:
        validation = None
        validation_form = ValidationForm()
    
    # Récupérer les objets complets DangerousCategory (pas juste les noms)
    dangerous_categories = DangerousCategory.objects.filter(is_active=True)
    
    # Récupérer les validations existantes pour chaque catégorie
    category_validations = {}
    if detection.media_type == 'VIDEO':
        validations = CategoryValidation.objects.filter(detection_log=detection)
        for val in validations:
            key = f"{val.category_name}_{val.frame_number}"
            category_validations[key] = {
                'is_valid': val.is_valid,
                'validator': val.validator.username if val.validator else 'N/A',
                'timestamp': val.validation_timestamp.strftime('%Y-%m-%d %H:%M:%S')
            }
    
    # Convertir dangerous_categories en liste pour JSON
    dangerous_categories_list = [cat.name for cat in dangerous_categories]
    
    context = {
        'detection': detection,
        'validation': validation,
        'validation_form': validation_form,
        'chatbot_response': chatbot_response,
        'chatbot_model': chatbot_model,
        'dangerous_categories': dangerous_categories,  # QuerySet pour le template
        'detection_objects_json': json.dumps(detection.detected_objects),
        'dangerous_categories_json': json.dumps(dangerous_categories_list),  # Liste pour JSON
        'category_validations_json': json.dumps(category_validations)
    }
    
    return render(request, 'detection/result.html', context)

@login_required
def validate_detection(request, detection_id):
    detection = get_object_or_404(DetectionLog, id=detection_id)
    if detection.user != request.user and not is_supervisor_or_admin(request.user):
        return HttpResponseForbidden("Vous n'avez pas la permission de valider cette détection.")
    
    try:
        validation = detection.validation
        messages.warning(request, "Cette détection a déjà été validée.")
        return redirect('detection:result', detection_id=detection.id)
    except ModelValidation.DoesNotExist:
        pass
    
    if request.method == 'POST':
        form = ValidationForm(request.POST)
        if form.is_valid():
            validation = form.save(commit=False)
            validation.detection_log = detection
            validation.validator = request.user
            validation.save()
            
            messages.success(request, "Validation enregistrée avec succès.")
            return redirect('detection:analysis_results', report_id=detection.report.id) if detection.report else redirect('detection:result', detection_id=detection.id)
    else:
        form = ValidationForm()
    
    return render(request, 'detection/validate.html', {
        'form': form,
        'detection': detection
    })

@login_required
def validate_category(request, detection_id):
    """Valide ou rejette une catégorie individuellement pour les vidéos"""
    if request.method != 'POST':
        return JsonResponse({'error': 'Méthode non autorisée'}, status=405)
    
    detection = get_object_or_404(DetectionLog, id=detection_id)
    
    # Vérifier les permissions
    if detection.user != request.user and not is_supervisor_or_admin(request.user):
        return JsonResponse({'error': 'Permission refusée'}, status=403)
    
    # Récupérer les données POST
    category_name = request.POST.get('category_name')
    is_valid_str = request.POST.get('is_valid')
    is_valid = is_valid_str == 'true'
    frame_number = request.POST.get('frame_number')
    confidence = request.POST.get('confidence', 0.0)
    
    # Log pour débogage
    logger = logging.getLogger(__name__)
    logger.info(f"Validation: category={category_name}, is_valid_str='{is_valid_str}', is_valid={is_valid}, frame={frame_number}")
    
    if not category_name:
        return JsonResponse({'error': 'Nom de catégorie manquant'}, status=400)
    
    try:
        from .models import CategoryValidation
        
        # Convertir confidence en float, gérer les valeurs null/vides
        try:
            confidence_value = float(confidence) if confidence and confidence != 'null' else 0.0
        except (ValueError, TypeError):
            confidence_value = 0.0
        
        # Créer ou mettre à jour la validation de catégorie
        validation, created = CategoryValidation.objects.update_or_create(
            detection_log=detection,
            category_name=category_name,
            frame_number=int(frame_number) if frame_number and frame_number != 'null' else None,
            defaults={
                'is_valid': is_valid,
                'validator': request.user,
                'confidence': confidence_value,
                'validation_timestamp': timezone.now()
            }
        )
        
        logger.info(f"CategoryValidation créée/mise à jour: id={validation.id}, is_valid={validation.is_valid}, created={created}")
        
        # Recalculer le niveau de danger basé sur les catégories validées
        old_danger_level = detection.danger_level
        new_danger_level = recalculate_danger_level(detection)
        
        logger.info(f"Niveau de danger: ancien={old_danger_level}, nouveau={new_danger_level}")
        
        # Mettre à jour le niveau de danger si nécessaire
        if new_danger_level != detection.danger_level:
            detection.danger_level = new_danger_level
            detection.save()
            logger.info(f"Niveau de danger mis à jour dans la BD: {new_danger_level}")
        
        return JsonResponse({
            'success': True,
            'message': f"Catégorie '{category_name}' {'validée' if is_valid else 'rejetée'} avec succès",
            'new_danger_level': new_danger_level,
            'validation_id': validation.id
        })
    
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)


def recalculate_danger_level(detection):
    """
    Recalcule le niveau de danger basé sur les catégories détectées.
    
    Logique CORRECTE :
    1. Récupère toutes les catégories détectées dans detected_objects
    2. Exclut les catégories qui ont été explicitement REJETÉES (is_valid=False)
    3. Inclut les catégories :
       - Validées (is_valid=True)
       - Non encore vérifiées (pas de CategoryValidation)
    4. Détermine le niveau basé sur la catégorie la plus dangereuse restante
    
    Exemple :
    - Détecté : knife (NORMAL) + shotgun (HYPERDANGEROUS)
    - Initial : HYPERDANGEROUS
    - Si shotgun rejeté : NORMAL (basé sur knife)
    - Si shotgun validé : HYPERDANGEROUS
    - Si aucune validation : HYPERDANGEROUS (les deux comptent)
    """
    from .models import CategoryValidation, DangerousCategory
    import json
    
    # Récupérer toutes les catégories détectées
    if not detection.detected_objects:
        return None
    
    try:
        detected_objects = json.loads(detection.detected_objects) if isinstance(detection.detected_objects, str) else detection.detected_objects
    except (json.JSONDecodeError, TypeError):
        return None
    
    # Récupérer les catégories explicitement REJETÉES (is_valid=False)
    rejected_validations = CategoryValidation.objects.filter(
        detection_log=detection,
        is_valid=False
    ).values_list('category_name', flat=True)
    
    rejected_categories = set(cat.lower() for cat in rejected_validations)
    
    # Log pour débogage
    logger = logging.getLogger(__name__)
    logger.info(f"Recalcul danger: rejected_categories={rejected_categories}")
    
    # Parcourir les catégories détectées et déterminer le niveau le plus dangereux
    highest_danger_level = None
    has_remaining_categories = False  # Flag pour savoir s'il reste des catégories non rejetées
    
    for obj in detected_objects:
        category_name = obj.get('category', '').strip()
        if not category_name:
            continue
        
        # Ignorer les catégories rejetées
        if category_name.lower() in rejected_categories:
            continue
        
        # Cette catégorie n'est pas rejetée, donc elle compte
        has_remaining_categories = True
        
        # Vérifier le type de danger de cette catégorie
        try:
            dangerous_cat = DangerousCategory.objects.get(
                name__iexact=category_name,
                is_active=True
            )
            
            if dangerous_cat.category_type == 'HYPERDANGEROUS':
                return 'HYPERDANGEROUS'  # Retourner immédiatement (le plus haut niveau)
            elif dangerous_cat.category_type == 'DANGEROUS':
                highest_danger_level = 'DANGEROUS'
        except DangerousCategory.DoesNotExist:
            # Catégorie non dangereuse ou non trouvée dans DangerousCategory
            # Continue à chercher d'autres catégories potentiellement dangereuses
            pass
    
    # Si on a trouvé une catégorie dangereuse, la retourner
    if highest_danger_level:
        logger.info(f"Recalcul danger: résultat={highest_danger_level}")
        return highest_danger_level
    
    # Si on a des catégories restantes (non rejetées) mais aucune n'est dangereuse → NORMAL
    # Si TOUTES les catégories ont été rejetées → NORMAL également
    logger.info(f"Recalcul danger: résultat=NORMAL (has_remaining={has_remaining_categories})")
    return 'NORMAL'


@login_required
def detection_history(request):
    # Récupérer les détections en fonction des permissions
    if request.user.is_administrator or request.user.is_supervisor:
        detections = DetectionLog.objects.all().order_by('-detection_timestamp')
        all_detections = DetectionLog.objects.all()
    else:
        detections = DetectionLog.objects.filter(user=request.user).order_by('-detection_timestamp')
        all_detections = DetectionLog.objects.filter(user=request.user)

    # Récupérer les paramètres de filtrage
    class_filter = request.GET.get('class_filter', '').strip().lower()
    danger_level_filter = request.GET.get('danger_level_filter', '').strip().lower()
    location_filter = request.GET.get('location_filter', '').strip()
    date_from = request.GET.get('date_from', '')
    date_to = request.GET.get('date_to', '')
    # Chart-specific parameters from stats.html
    validation_status = request.GET.get('validation_status', '').strip().lower()
    date = request.GET.get('date', '').strip()
    category = request.GET.get('category', '').strip().lower()
    operator_id = request.GET.get('operator_id', '')

    # Calculer les classes détectées avec occurrences (for full page view)
    class_counts = {}
    for detection in all_detections:
        for obj in detection.detected_objects:
            category_name = obj.get('category', '').strip().lower()
            if category_name:
                class_counts[category_name] = class_counts.get(category_name, 0) + 1
    class_choices = [(cls, f"{cls.capitalize()} ({count})") for cls, count in sorted(class_counts.items())]

    # Calculer les niveaux de danger avec occurrences
    danger_levels = [
        {'level': 'normal', 'count': all_detections.filter(danger_level__isnull=True).count()},
        {'level': 'dangerous', 'count': all_detections.filter(danger_level='DANGEROUS').count()},
        {'level': 'hyperdangerous', 'count': all_detections.filter(danger_level='HYPERDANGEROUS').count()},
    ]
    danger_level_choices = [(dl['level'], f"{dl['level'].capitalize()} ({dl['count']})") for dl in danger_levels if dl['count'] > 0]

    # Calculer les localisations avec occurrences
    location_counts = (
        all_detections.values('user_location')
        .annotate(count=Count('id'))
        .exclude(user_location='')
        .order_by('user_location')
    )
    location_choices = [(loc['user_location'], f"{loc['user_location']} ({loc['count']})") for loc in location_counts]

    # Appliquer les filtres
    if class_filter or category:
        filter_value = class_filter or category
        filtered_detection_ids = []
        for detection in detections:
            for obj in detection.detected_objects:
                category_name = obj.get('category', '').lower()
                if category_name == filter_value:
                    filtered_detection_ids.append(detection.id)
                    break
        detections = detections.filter(id__in=filtered_detection_ids)

    if danger_level_filter:
        if danger_level_filter == 'normal':
            detections = detections.filter(danger_level__isnull=True)
        else:
            detections = detections.filter(danger_level=danger_level_filter.upper())

    if location_filter:
        detections = detections.filter(user_location=location_filter)

    if date_from:
        try:
            date_from_obj = datetime.strptime(date_from, '%Y-%m-%d')
            detections = detections.filter(detection_timestamp__gte=date_from_obj)
        except ValueError:
            pass

    if date_to:
        try:
            date_to_obj = datetime.strptime(date_to, '%Y-%m-%d')
            detections = detections.filter(detection_timestamp__lte=date_to_obj)
        except ValueError:
            pass

    if date:
        try:
            date_obj = datetime.strptime(date, '%Y-%m-%d').date()
            detections = detections.filter(detection_timestamp__date=date_obj)
        except ValueError:
            pass

    if validation_status:
        if validation_status == 'valides':
            detections = detections.filter(validation__is_correct=True)
        elif validation_status == 'non valides':
            detections = detections.filter(validation__is_correct=False)
        elif validation_status == 'incorrectes':
            detections = detections.filter(validation__is_correct=False, validation__corrected_category__isnull=False)

    if operator_id and request.user.is_supervisor:
        try:
            detections = detections.filter(user_id=int(operator_id))
        except ValueError:
            pass

    # Pagination
    paginator = Paginator(detections, 10)
    page_number = request.GET.get('page', 1)
    page_obj = paginator.get_page(page_number)

    # Determine template based on request type
    context = {
        'page_obj': page_obj,
        'class_filter': class_filter or category,
        'danger_level_filter': danger_level_filter,
        'location_filter': location_filter,
        'date_from': date_from,
        'date_to': date_to,
        'class_choices': class_choices,
        'danger_level_choices': danger_level_choices,
        'location_choices': location_choices,
    }

    # Return partial template for AJAX requests from stats.html
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return render(request, 'detection/history_partial.html', context)
    
    return render(request, 'detection/history.html', context)


@login_required
@user_passes_test(is_supervisor_or_admin)
def flagged_detections(request):
    # Restreindre aux détections hyperdangereuses pour tous les utilisateurs
    detections = DetectionLog.objects.filter(danger_level='HYPERDANGEROUS').order_by('-detection_timestamp')
    all_detections = detections  # Pour calculer les choix de filtres

    # Récupérer les paramètres de filtrage
    user_filter = request.GET.get('user_filter', '').strip()
    location_filter = request.GET.get('location_filter', '').strip()
    danger_level_filter = request.GET.get('danger_level_filter', '').strip().lower()
    date_from = request.GET.get('date_from', '')
    date_to = request.GET.get('date_to', '')

    # Calculer les utilisateurs avec occurrences
    user_counts = (
        all_detections.values('user__id', 'user__email', 'user__first_name', 'user__last_name')
        .annotate(count=Count('id'))
        .order_by('user__email')
    )
    user_choices = []
    for user in user_counts:
        full_name = f"{user['user__first_name']} {user['user__last_name']}".strip()
        display = f"{full_name or user['user__email']} ({user['count']})"
        user_choices.append((str(user['user__id']), display))

    # Calculer les localisations avec occurrences
    location_counts = (
        all_detections.values('user_location')
        .annotate(count=Count('id'))
        .exclude(user_location='')
        .order_by('user_location')
    )
    location_choices = [(loc['user_location'], f"{loc['user_location']} ({loc['count']})") for loc in location_counts]

    # Calculer les niveaux de danger (seulement hyperdangerous)
    danger_level_choices = [('hyperdangerous', f"Hyperdangereux ({all_detections.count()})")]

    # Appliquer les filtres
    if user_filter:
        try:
            user_id = int(user_filter)
            detections = detections.filter(user_id=user_id)
        except ValueError:
            detections = detections.none()

    if location_filter:
        detections = detections.filter(user_location=location_filter)

    if danger_level_filter and danger_level_filter != 'hyperdangerous':
        detections = detections.none()  # Seulement hyperdangerous est valide

    if date_from:
        try:
            date_from = datetime.strptime(date_from, '%Y-%m-%d')
            detections = detections.filter(detection_timestamp__gte=date_from)
        except ValueError:
            pass

    if date_to:
        try:
            date_to = datetime.strptime(date_to, '%Y-%m-%d')
            detections = detections.filter(detection_timestamp__lte=date_to)
        except ValueError:
            pass

    # Pagination
    paginator = Paginator(detections, 10)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    context = {
        'page_obj': page_obj,
        'user_filter': user_filter,
        'location_filter': location_filter,
        'danger_level_filter': danger_level_filter,
        'date_from': date_from,
        'date_to': date_to,
        'user_choices': user_choices,
        'location_choices': location_choices,
        'danger_level_choices': danger_level_choices,
    }
    return render(request, 'detection/flagged.html', context)



@login_required
@user_passes_test(is_admin)
def manage_categories(request):
    categories = DangerousCategory.objects.all().order_by('name')
    return render(request, 'detection/categories.html', {'categories': categories})

@login_required
@user_passes_test(is_admin)
def add_category(request):
    if request.method == 'POST':
        form = CategoryForm(request.POST)
        if form.is_valid():
            category = form.save(commit=False)
            category.created_by = request.user
            category.save()
            messages.success(request, f"La catégorie {category.name}' a été ajoutée avec succès.")
            return redirect('detection:categories')
    else:
        form = CategoryForm()
    
    return render(request, 'detection/category_form.html', {
        'form': form,
        'title': 'Ajouter une catégorie dangereuse'
    })

@login_required
@user_passes_test(is_admin)
def edit_category(request, category_id):
    category = get_object_or_404(DangerousCategory, id=category_id)
    if request.method == 'POST':
        form = CategoryForm(request.POST, instance=category)
        if form.is_valid():
            form.save()
            messages.success(request, f"La catégorie {category.name}' a été modifiée avec succès.")
            return redirect('detection:categories')
    else:
        form = CategoryForm(instance=category)
    
    return render(request, 'detection/category_form.html', {
        'form': form,
        'category': category,
        'title': 'Modifier une catégorie dangereuse'
    })

@login_required
@user_passes_test(is_admin)
def delete_category(request, category_id):
    category = get_object_or_404(DangerousCategory, id=category_id)
    if request.method == 'POST':
        name = category.name
        category.delete()
        messages.success(request, f"La catégorie {name}' a été supprimée avec succès.")
        return redirect('detection:categories')
    
    return render(request, 'detection/category_delete.html', {'category': category})

def chatbot_interact(request, detection_id):
    detection = get_object_or_404(DetectionLog, id=detection_id)
    if request.method != 'POST':
        return JsonResponse({'response': 'Méthode non autorisée.'}, status=405)

    user_input = request.POST.get('user_input', '')
    dangerous_categories = ["pistolet", "fusil", "couteau", "sword"]
    dangerous_objects = [obj for obj in detection.detected_objects if (obj.get('category') or obj.get('label') or obj.get('class_name') or '').lower() in dangerous_categories]
    objects_info = ", ".join([f"{obj.get('category', obj.get('label', obj.get('class_name', 'Inconnu')))} (confidence: {obj.get('confidence', 0):.2f})" for obj in dangerous_objects]) if dangerous_objects else "Aucun objet dangereux"

    prompt = (
        f"Contexte : Objets détectés = {objects_info}. "
        f"Question de l'utilisateur : {user_input}. "
        "Fournis une réponse claire, concise et adaptée à un policier en contexte de sécurité urbaine."
    )

    try:
        genai.configure(api_key=settings.CHATBOT_API_KEY)
        model = genai.GenerativeModel('gemini-2.0-flash')
        response = model.generate_content(
            prompt,
            generation_config={
                "max_output_tokens": 150,
                "temperature": 0.7
            }
        )
        chatbot_response = response.text
        logger.info(f"Chatbot response for user input: {chatbot_response}")
        return JsonResponse({'response': chatbot_response})
    except Exception as e:
        logger.error(f"Error calling Gemini API: {str(e)}")
        return JsonResponse({'response': 'Erreur : Impossible de répondre. Suivez les protocoles standards.'}, status=500)

def detection_detail(request, detection_id):
    detection = get_object_or_404(DetectionLog, id=detection_id)
    chatbot_response, chatbot_model = get_chatbot_instructions(detection.detected_objects)
    
    context = {
        'detection': detection,
        'chatbot_response': chatbot_response,
        'chatbot_model': chatbot_model,
        'dangerous_categories': DangerousCategory.objects.filter(is_active=True),
        'detection_objects_json': json.dumps(detection.detected_objects),
        'dangerous_categories_json': [{'name': cat.name, 'category_type': cat.category_type} for cat in DangerousCategory.objects.filter(is_active=True)]
    }
    return render(request, 'detection/result.html', context)


# ============ NOUVELLES FONCTIONS POUR SUPPORT VIDÉO ============

@login_required
def unified_media_detection(request):
    """Vue unifiée pour traiter images et vidéos dans un seul formulaire"""
    from .utils import run_video_detection, is_video_file, is_image_file
    from .forms import UnifiedMediaDetectionForm
    
    if request.method == 'POST':
        form = UnifiedMediaDetectionForm(request.POST, request.FILES)
        
        if form.is_valid():
            files = request.FILES.getlist('media_files')
            location = form.cleaned_data.get('location', '')
            report_name = form.cleaned_data.get('report_name', '')
            frame_interval = form.cleaned_data.get('video_frame_interval', 30)
            
            now = timezone.now()
            
            report = Report.objects.create(
                user=request.user,
                location=location,
                name=report_name or f"Rapport {now.strftime('%Y-%m-%d %H:%M:%S')}"
            )
            logger.info(f"Created Report ID: {report.id}, Name: {report.name}")
            
            detection_logs = []
            
            for file in files:
                base_name = re.sub(r'[^\w\-\s.]', '_', os.path.splitext(file.name)[0])
                ext = os.path.splitext(file.name)[1]
                timestamp_str = str(int(time.time()))
                filename = f"{base_name}_{timestamp_str}{ext}"
                
                relative_path = f"uploads/{now.year}/{now.month:02d}/{now.day:02d}/{filename}"
                full_path = os.path.join(settings.MEDIA_ROOT, relative_path)
                os.makedirs(os.path.dirname(full_path), exist_ok=True)
                
                with open(full_path, 'wb+') as destination:
                    for chunk in file.chunks():
                        destination.write(chunk)
                
                try:
                    start_time = time.time()
                    
                    if is_video_file(filename):
                        # TRAITEMENT VIDÉO
                        annotated_relative_path = f"detection_results/{now.year}/{now.month:02d}/{now.day:02d}/{filename}"
                        annotated_full_path = os.path.join(settings.MEDIA_ROOT, annotated_relative_path)
                        os.makedirs(os.path.dirname(annotated_full_path), exist_ok=True)
                        
                        logger.info(f"[VIDEO] Processing: {filename}")
                        
                        detected_objects, danger_level, model_used, video_metadata, frames_analyzed = run_video_detection(
                            full_path,
                            annotated_full_path,
                            frame_interval=frame_interval
                        )
                        
                        processing_duration = time.time() - start_time
                        
                        normalized_objects = []
                        for obj in detected_objects:
                            category = obj.get('category', '').strip().lower()
                            if category and category != 'error':
                                normalized_objects.append({
                                    'category': category,
                                    'confidence': float(obj.get('confidence', 0.0)),
                                    'frame': obj.get('frame', 0),
                                    'timestamp': obj.get('timestamp', 0.0)
                                })
                        
                        detection_log = DetectionLog.objects.create(
                            user=request.user,
                            report=report,
                            media_type='VIDEO',
                            uploaded_file=annotated_relative_path,
                            original_file=relative_path,
                            user_location=location,
                            detected_objects=normalized_objects,
                            danger_level=danger_level,
                            model_used=model_used,
                            is_simulated=(model_used == "simulation"),
                            video_metadata=video_metadata,
                            frames_analyzed=frames_analyzed,
                            processing_duration=processing_duration
                        )
                        logger.info(f"[VIDEO] Detection log created: ID {detection_log.id}")
                        
                    elif is_image_file(filename):
                        # TRAITEMENT IMAGE
                        annotated_relative_path = f"detection_results/{now.year}/{now.month:02d}/{now.day:02d}/{filename}"
                        annotated_full_path = os.path.join(settings.MEDIA_ROOT, annotated_relative_path)
                        os.makedirs(os.path.dirname(annotated_full_path), exist_ok=True)
                        
                        logger.info(f"[IMAGE] Processing: {filename}")
                        
                        detected_objects, danger_level, model_used = run_detection(
                            full_path,
                            annotated_full_path
                        )
                        
                        processing_duration = time.time() - start_time
                        
                        normalized_objects = []
                        for obj in detected_objects:
                            category = obj.get('category', '').strip().lower()
                            if category and category != 'error':
                                normalized_objects.append({
                                    'category': category,
                                    'confidence': float(obj.get('confidence', 0.0))
                                })
                        
                        detection_log = DetectionLog.objects.create(
                            user=request.user,
                            report=report,
                            media_type='IMAGE',
                            uploaded_file=annotated_relative_path,
                            original_file=relative_path,
                            user_location=location,
                            detected_objects=normalized_objects,
                            danger_level=danger_level,
                            model_used=model_used,
                            is_simulated=(model_used == "simulation"),
                            processing_duration=processing_duration
                        )
                        logger.info(f"[IMAGE] Detection log created: ID {detection_log.id}")
                    
                    else:
                        logger.warning(f"Unsupported file type: {filename}")
                        continue
                    
                    detection_logs.append(detection_log)
                    
                except Exception as e:
                    logger.error(f"Detection failed for {filename}: {str(e)}", exc_info=True)
                    messages.warning(request, f"Échec de la détection pour {filename}: {str(e)}")
                    continue
            
            if not detection_logs:
                report.delete()
                messages.error(request, "Aucune détection valide n'a été effectuée.")
                return render(request, 'detection/unified_upload.html', {'form': form})
            
            messages.success(request, f"{len(detection_logs)} détection(s) terminée(s) avec succès.")
            return redirect('detection:analysis_results', report_id=report.id)
        
        else:
            logger.error(f"Form validation failed: {form.errors}")
            for field, errors in form.errors.items():
                for error in errors:
                    messages.error(request, f"{field}: {error}")
    
    else:
        form = UnifiedMediaDetectionForm()
    
    return render(request, 'detection/unified_upload.html', {
        'form': form,
        'page_title': 'Détection Unifiée - Images & Vidéos'
    })