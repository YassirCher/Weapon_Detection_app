import requests
import logging
from django.conf import settings
from apps.core.models import AppSettings
import google.generativeai as genai

logger = logging.getLogger(__name__)

def get_chatbot_instructions(detected_objects):
    """
    Generate safety instructions using the Gemini model based on detected objects.
    
    Args:
        detected_objects (list): List of detected objects in the image
        
    Returns:
        tuple: (formatted instructions, model used)
    """
    app_settings = AppSettings.load()
    model_used = app_settings.active_chatbot_model or "gemini-2.0-flash"

    # Define weapon category information
    weapon_info = {
        "pistolet": {
            "description": "Arme à feu de poing, souvent utilisée pour des attaques rapprochées.",
            "limitations": "Risque de confusion avec des objets similaires (ex. jouets, outils). La détection dépend de la qualité de l'image et de l'angle.",
            "precautions": "Confirmez visuellement et à distance. Suivez les protocoles de sécurité pour les armes à feu et évitez toute confrontation directe."
        },
        "fusil": {
            "description": "Arme à feu longue, potentiellement utilisée pour des attaques à longue portée.",
            "limitations": "Peut être confondu avec des objets non létaux (ex. cannes, équipements sportifs). La détection peut être moins précise en faible luminosité.",
            "precautions": "Maintenez une distance de sécurité, utilisez des jumelles si possible, et appelez des renforts spécialisés."
        },
        "couteau": {
            "description": "Arme blanche utilisée pour des attaques rapprochées ou des menaces.",
            "limitations": "Difficile à distinguer dans des environnements encombrés ou si l'arme est partiellement cachée.",
            "precautions": "Évitez tout contact direct, sécurisez la zone, et vérifiez la présence d'autres menaces."
        },
        "sword": {
            "description": "Arme blanche longue, utilisée pour des attaques de mêlée.",
            "limitations": "Peut être confondue avec des objets décoratifs ou des outils. La détection dépend de la visibilité de la lame.",
            "precautions": "Maintenez une distance de sécurité, sécurisez la zone, et vérifiez l'intention du porteur."
        }
    }

    # Identify dangerous objects
    dangerous_categories = ["pistolet", "fusil", "couteau", "sword"]
    dangerous_objects = [obj for obj in detected_objects if obj.get('category').lower() in dangerous_categories]
    
    # Generate response text
    response_text = ""
    if not dangerous_objects:
        response_text = (
            "Aucun objet dangereux détecté.\n\n"
            "**Instructions générales** : Continuez la surveillance active, restez vigilant face à tout comportement suspect, et rapportez toute anomalie.\n"
            "**Limites** : La détection peut manquer des objets non identifiables ou masqués.\n"
            "**Précautions** : Maintenez une observation régulière et utilisez des sources secondaires (témoins, caméras) pour confirmer."
        )
        prompt = "Aucun objet dangereux détecté dans l'image. Fournis des instructions générales pour la surveillance urbaine."
    else:
        for obj in dangerous_objects:
            category = obj.get('category').lower()
            info = weapon_info.get(category, {
                "description": "Objet non catégorisé.",
                "limitations": "Informations limitées sur cet objet.",
                "precautions": "Suivez les protocoles standards de sécurité."
            })
            response_text += (
                f"**Catégorie détectée** : {obj['category']} (confiance : {obj.get('confidence', 0):.2f})\n"
                f"**Description** : {info['description']}\n"
                f"**Limites** : {info['limitations']}\n"
                f"**Précautions** : {info['precautions']}\n\n"
            )
        objects_info = ", ".join([f"{obj['category']} (confiance: {obj.get('confidence', 0):.2f})" for obj in dangerous_objects])
        prompt = (
            f"Objets détectés : {objects_info}. "
            "Fournis des instructions de sécurité urbaine claires et concises pour gérer la situation, "
            "en complément des informations suivantes déjà fournies : description, limites, précautions."
        )

    # Call Gemini API
    if model_used == "gemini-2.0-flash":
        try:
            genai.configure(api_key=settings.CHATBOT_API_KEY)
            model = genai.GenerativeModel('gemini-2.0-flash')
            response = model.generate_content(
                prompt,
                generation_config={
                    "max_output_tokens": 200,
                    "temperature": 0.7,
                }
            )
            api_response = response.text
            final_response = f"{response_text}**Instructions supplémentaires** : {api_response}"
            logger.info(f"Chatbot response received: {final_response}")
            return final_response, model_used
        except Exception as e:
            logger.error(f"Error calling Gemini API: {str(e)}")
            final_response = (
                f"{response_text}"
                "**Erreur** : Impossible de récupérer des instructions supplémentaires. Suivez les protocoles de sécurité standards."
            )
            return final_response, model_used
    else:
        return (
            f"{response_text}Mode simulation : Instructions génériques fournies.",
            model_used
        )

def get_chatbot_response(user_input, detected_objects):
    """
    Generate a response to a user's question using Gemini based on detected objects.
    
    Args:
        user_input (str): User's question or input
        detected_objects (list): List of detected objects
        
    Returns:
        tuple: (generated response, model used)
    """
    app_settings = AppSettings.load()
    model_used = app_settings.active_chatbot_model or "gemini-2.0-flash"

    dangerous_categories = ["pistolet", "fusil", "couteau", "sword"]
    dangerous_objects = [obj for obj in detected_objects if obj.get('category').lower() in dangerous_categories]
    objects_info = ", ".join([f"{obj['category']} (confiance: {obj.get('confidence', 0):.2f})" for obj in dangerous_objects]) if dangerous_objects else "Aucun objet dangereux"

    prompt = (
        f"Contexte : Objets détectés = {objects_info}. "
        f"Question de l'utilisateur : {user_input}. "
        "Fournis une réponse claire, concise et adaptée à un policier en contexte de sécurité urbaine."
    )

    if model_used == "gemini-2.0-flash":
        try:
            genai.configure(api_key=settings.CHATBOT_API_KEY)
            model = genai.GenerativeModel('gemini-2.0-flash')
            response = model.generate_content(
                prompt,
                generation_config={
                    "max_output_tokens": 150,
                    "temperature": 0.7,
                }
            )
            chatbot_response = response.text
            logger.info(f"Chatbot response for user input: {chatbot_response}")
            return chatbot_response, model_used
        except Exception as e:
            logger.error(f"Error calling Gemini API: {str(e)}")
            return "Erreur : Impossible de répondre. Suivez les protocoles standards.", model_used
    else:
        return (
            "Mode simulation : Réponse générique. Posez une question spécifique pour plus de détails.",
            model_used
        )