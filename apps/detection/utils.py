from ultralytics import YOLO
import os
import logging
from django.conf import settings
from apps.core.models import AppSettings
from apps.detection.models import DangerousCategory
from PIL import Image
import numpy as np
import cv2

logger = logging.getLogger(__name__)

class DetectionModel:
    _instance = None

    @classmethod
    def get_instance(cls):
        """Load the YOLO model once and cache it."""
        if cls._instance is None:
            try:
                app_settings = AppSettings.load()
                model_path = os.path.join(settings.BASE_DIR, app_settings.active_detection_model)
                if not os.path.exists(model_path):
                    logger.error(f"Model file not found: {model_path}")
                    return None
                cls._instance = YOLO(model_path)
                logger.info(f"YOLO model loaded: {model_path}")
            except Exception as e:
                logger.error(f"Failed to load YOLO model: {str(e)}")
                return None
        return cls._instance

# In utils.py, modify run_detection
def run_detection(image_path, output_path):
    logger.info(f"Starting detection for image: {image_path}")
    try:
        app_settings = AppSettings.load()
        model_path = app_settings.active_detection_model
        threshold = app_settings.dangerous_threshold
        dangerous_categories = DangerousCategory.objects.filter(is_active=True).values('name', 'category_type')

        if model_path == "simulation":
            logger.warning("Running in simulation mode")
            return (
                [{"category": "knife", "confidence": 0.9, "bbox": [100, 100, 50, 50]}],
                "DANGEROUS",
                "simulation"
            )

        # Load YOLO model
        model = DetectionModel.get_instance()
        if model is None:
            logger.error("Model loading failed, falling back to simulation")
            return (
                [{"category": "error", "confidence": 0.0, "bbox": [0, 0, 0, 0]}],
                None,
                "simulation"
            )

        # Verify image is readable
        try:
            img = cv2.imread(image_path)
            if img is None:
                logger.error(f"Failed to read image: {image_path}")
                raise ValueError("Image file is corrupted or unreadable")
        except Exception as e:
            logger.error(f"Image validation failed: {str(e)}")
            raise

        # Run detection
        results = model.predict(image_path, conf=threshold, verbose=False)

        # Save annotated image
        annotated_frame = results[0].plot()
        logger.info(f"Before saving: shape={annotated_frame.shape}, dtype={annotated_frame.dtype}")
        cv2.imwrite(output_path, annotated_frame)
        if not os.path.exists(output_path):
            logger.error(f"Failed to save annotated image: {output_path}")
            raise ValueError("Failed to save annotated image")
        logger.info(f"Annotated image saved: {output_path}")

        # Process detections
        detected_objects = []
        danger_level = None

        for result in results:
            for box in result.boxes:
                category = result.names[int(box.cls)]
                confidence = float(box.conf)
                bbox = box.xywh[0].tolist()
                detected_objects.append({
                    "category": category,
                    "confidence": confidence,
                    "bbox": bbox
                })
                # Check danger level
                for cat in dangerous_categories:
                    if category.lower() == cat['name'].lower():
                        if cat['category_type'] == 'HYPERDANGEROUS':
                            danger_level = 'HYPERDANGEROUS'
                        elif cat['category_type'] == 'DANGEROUS' and danger_level != 'HYPERDANGEROUS':
                            danger_level = 'DANGEROUS'

        logger.info(f"Detection completed: {len(detected_objects)} objects found, danger_level: {danger_level}")
        return detected_objects, danger_level, model_path

    except Exception as e:
        logger.error(f"Detection failed: {str(e)}")
        return (
            [{"category": "error", "confidence": 0.0, "bbox": [0, 0, 0, 0]}],
            None,
            "simulation"
        )


# ============ NOUVELLES FONCTIONS POUR SUPPORT VIDÉO ============

def get_video_info(video_path: str) -> dict:
    """Extrait les métadonnées d'une vidéo"""
    cap = cv2.VideoCapture(video_path)
    
    if not cap.isOpened():
        raise ValueError(f"Impossible d'ouvrir la vidéo : {video_path}")
    
    fps = cap.get(cv2.CAP_PROP_FPS)
    frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    duration = frame_count / fps if fps > 0 else 0
    
    cap.release()
    
    return {
        'fps': fps,
        'frame_count': frame_count,
        'width': width,
        'height': height,
        'duration': duration,
        'duration_formatted': f"{int(duration // 60)}m {int(duration % 60)}s"
    }


def is_video_file(filename: str) -> bool:
    """Vérifie si le fichier est une vidéo"""
    VIDEO_EXTENSIONS = ['.mp4', '.avi', '.mov', '.mkv', '.wmv', '.flv']
    ext = os.path.splitext(filename)[1].lower()
    return ext in VIDEO_EXTENSIONS


def is_image_file(filename: str) -> bool:
    """Vérifie si le fichier est une image"""
    IMAGE_EXTENSIONS = ['.jpg', '.jpeg', '.png', '.bmp', '.gif']
    ext = os.path.splitext(filename)[1].lower()
    return ext in IMAGE_EXTENSIONS


def run_video_detection(video_path, output_path, frame_interval=30, progress_callback=None):
    """
    Détection sur vidéo frame par frame avec génération d'une vidéo annotée
    
    Args:
        video_path: Chemin vers la vidéo source
        output_path: Chemin pour la vidéo annotée de sortie
        frame_interval: Analyser 1 frame toutes les X frames (ex: 30 = 1 fps pour vidéo à 30fps)
        progress_callback: Fonction optionnelle pour feedback de progression
    
    Returns:
        (detected_objects, danger_level, model_used, video_metadata, frames_analyzed)
    """
    logger.info(f"Starting video detection: {video_path}")
    
    try:
        # Charger les paramètres de l'application
        app_settings = AppSettings.load()
        model_path = app_settings.active_detection_model
        threshold = app_settings.dangerous_threshold
        dangerous_categories = DangerousCategory.objects.filter(is_active=True).values('name', 'category_type')
        
        # Obtenir les infos de la vidéo
        video_info = get_video_info(video_path)
        logger.info(f"Video info: {video_info['duration_formatted']}, {video_info['fps']} FPS, "
                   f"{video_info['width']}x{video_info['height']}")
        
        # Mode simulation
        if model_path == "simulation":
            logger.warning("Running video detection in simulation mode")
            import shutil
            shutil.copy(video_path, output_path)
            
            return (
                [{"category": "knife", "confidence": 0.85, "frame": 30, "bbox": [100, 100, 50, 50]}],
                "DANGEROUS",
                "simulation",
                video_info,
                1
            )
        
        # Charger le modèle YOLO
        model = DetectionModel.get_instance()
        if model is None:
            raise ValueError("Model loading failed")
        
        # Ouvrir la vidéo source
        cap = cv2.VideoCapture(video_path)
        if not cap.isOpened():
            raise ValueError(f"Cannot open video: {video_path}")
        
        # Préparer le writer pour la vidéo de sortie avec codec compatible navigateur
        fps = video_info['fps']
        width = video_info['width']
        height = video_info['height']
        
        # Essayer différents codecs H.264 (compatibles navigateurs)
        codecs_to_try = [
            ('avc1', 'H.264 (avc1)'),
            ('h264', 'H.264 (h264)'),
            ('x264', 'H.264 (x264)'),
            ('H264', 'H.264 (H264)'),
            ('mp4v', 'MPEG-4 (mp4v)'),  # Fallback
        ]
        
        out = None
        codec_used = None
        for codec_code, codec_name in codecs_to_try:
            fourcc = cv2.VideoWriter_fourcc(*codec_code)
            test_out = cv2.VideoWriter(output_path, fourcc, fps, (width, height))
            if test_out.isOpened():
                out = test_out
                codec_used = codec_name
                logger.info(f"Using codec: {codec_name}")
                break
            else:
                test_out.release()
        
        if out is None or not out.isOpened():
            cap.release()
            raise ValueError(f"Cannot create output video with any codec: {output_path}")
        
        # Variables de traitement
        all_detected_objects = []
        danger_level = None
        frame_idx = 0
        frames_analyzed = 0
        total_frames = video_info['frame_count']
        
        logger.info(f"Processing {total_frames} frames, analyzing every {frame_interval} frames")
        
        while True:
            ret, frame = cap.read()
            if not ret:
                break
            
            # Analyser seulement les frames à l'intervalle spécifié
            if frame_idx % frame_interval == 0:
                # Détection YOLO sur cette frame
                results = model.predict(frame, conf=threshold, verbose=False)
                annotated_frame = results[0].plot()
                
                # Extraire les détections
                for result in results:
                    for box in result.boxes:
                        category = result.names[int(box.cls)]
                        confidence = float(box.conf)
                        bbox = box.xywh[0].tolist()
                        
                        detection_obj = {
                            "category": category,
                            "confidence": confidence,
                            "bbox": bbox,
                            "frame": frame_idx,
                            "timestamp": round(frame_idx / fps, 2)
                        }
                        all_detected_objects.append(detection_obj)
                        
                        # Vérifier le niveau de danger
                        for cat in dangerous_categories:
                            if category.lower() == cat['name'].lower():
                                if cat['category_type'] == 'HYPERDANGEROUS':
                                    danger_level = 'HYPERDANGEROUS'
                                elif cat['category_type'] == 'DANGEROUS' and danger_level != 'HYPERDANGEROUS':
                                    danger_level = 'DANGEROUS'
                
                # Écrire la frame annotée
                out.write(annotated_frame)
                frames_analyzed += 1
            else:
                # Écrire la frame originale (non analysée)
                out.write(frame)
            
            frame_idx += 1
            
            # Callback de progression (si fourni)
            if progress_callback and frame_idx % 100 == 0:
                progress = (frame_idx / total_frames) * 100
                progress_callback(progress)
        
        # Libérer les ressources
        cap.release()
        out.release()
        
        # Vérifier que le fichier de sortie existe
        import os
        if os.path.exists(output_path):
            file_size = os.path.getsize(output_path)
            logger.info(f"Output video created successfully: {output_path} (size: {file_size} bytes)")
        else:
            logger.error(f"Output video NOT created: {output_path}")
            raise FileNotFoundError(f"Video output file not created: {output_path}")
        
        logger.info(f"Video detection completed: {len(all_detected_objects)} objects in {frames_analyzed} frames")
        logger.info(f"Danger level: {danger_level}")
        
        return all_detected_objects, danger_level, model_path, video_info, frames_analyzed
        
    except Exception as e:
        logger.error(f"Video detection failed: {str(e)}")
        raise

