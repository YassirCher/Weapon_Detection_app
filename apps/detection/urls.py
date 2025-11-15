from django.urls import path
from . import views

app_name = 'detection'

urlpatterns = [
    path('upload/', views.upload_detection, name='upload'),
    path('upload-multi/', views.upload_multi_detection, name='upload_multi'),
    path('upload-unified/', views.unified_media_detection, name='upload_unified'),  # NOUVELLE ROUTE VIDÉO/IMAGE
    path('result/<int:detection_id>/', views.detection_result, name='result'),
    path('analysis-results/<int:report_id>/', views.analysis_results, name='analysis_results'),
    path('history/', views.detection_history, name='history'),
    path('reports/', views.reports_history, name='reports_history'),
    path('validate/<int:detection_id>/', views.validate_detection, name='validate'),
    path('validate-category/<int:detection_id>/', views.validate_category, name='validate_category'),  # NOUVELLE ROUTE - Validation par catégorie
    path('flagged/', views.flagged_detections, name='flagged'),
    path('categories/', views.manage_categories, name='categories'),
    path('categories/add/', views.add_category, name='add_category'),
    path('categories/edit/<int:category_id>/', views.edit_category, name='edit_category'),
    path('categories/delete/<int:category_id>/', views.delete_category, name='delete_category'),
    path('detection/<int:detection_id>/chatbot/', views.chatbot_interact, name='chatbot_interact'),
    path('detection/<int:detection_id>/', views.detection_detail, name='detection_detail'),
    path('download-report-pdf/<int:report_id>/', views.download_report_pdf, name='download_report_pdf'),
]