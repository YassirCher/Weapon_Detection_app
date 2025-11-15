// JavaScript principal pour l'application de sécurité urbaine

// Fonction pour initialiser les tooltips Bootstrap
function initTooltips() {
  const tooltipTriggerList = [].slice.call(document.querySelectorAll('[data-bs-toggle="tooltip"]'));
  tooltipTriggerList.map(function (tooltipTriggerEl) {
    return new bootstrap.Tooltip(tooltipTriggerEl);
  });
}

// Fonction pour initialiser les popovers Bootstrap
function initPopovers() {
  const popoverTriggerList = [].slice.call(document.querySelectorAll('[data-bs-toggle="popover"]'));
  popoverTriggerList.map(function (popoverTriggerEl) {
    return new bootstrap.Popover(popoverTriggerEl);
  });
}

// Fonction pour afficher un indicateur de chargement
function showLoading(elementId) {
  const element = document.getElementById(elementId);
  if (element) {
    element.innerHTML = '<div class="text-center"><div class="spinner-border text-primary" role="status"><span class="visually-hidden">Chargement...</span></div><p class="mt-2">Traitement en cours...</p></div>';
  }
}

// Fonction pour masquer les alertes après un délai
function setupAlertDismiss() {
  const alerts = document.querySelectorAll('.alert:not(.alert-permanent)');
  alerts.forEach(alert => {
    setTimeout(() => {
      const bsAlert = new bootstrap.Alert(alert);
      bsAlert.close();
    }, 5000); // Fermer après 5 secondes
  });
}

// Fonction pour prévisualiser une image avant upload
function setupImagePreview() {
  const imageInput = document.getElementById('id_image');
  const previewContainer = document.getElementById('image-preview');
  
  if (imageInput && previewContainer) {
    imageInput.addEventListener('change', function() {
      previewContainer.innerHTML = '';
      
      if (this.files && this.files[0]) {
        const reader = new FileReader();
        
        reader.onload = function(e) {
          const img = document.createElement('img');
          img.src = e.target.result;
          img.classList.add('img-fluid', 'mt-2', 'mb-2', 'rounded');
          img.style.maxHeight = '300px';
          previewContainer.appendChild(img);
        }
        
        reader.readAsDataURL(this.files[0]);
      }
    });
  }
}

// Fonction pour simuler l'affichage des boîtes englobantes sur une image
function setupBoundingBoxes() {
  const canvas = document.getElementById('detection-canvas');
  const detectionImage = document.getElementById('detection-image');
  
  if (canvas && detectionImage && window.detectionResults) {
    // Attendre que l'image soit chargée
    detectionImage.onload = function() {
      // Configurer le canvas pour correspondre à l'image
      canvas.width = detectionImage.width;
      canvas.height = detectionImage.height;
      
      const ctx = canvas.getContext('2d');
      
      // Dessiner les boîtes englobantes
      window.detectionResults.forEach(result => {
        const [x, y, w, h] = result.bbox;
        const scaledX = (x / 100) * detectionImage.width;
        const scaledY = (y / 100) * detectionImage.height;
        const scaledW = (w / 100) * detectionImage.width;
        const scaledH = (h / 100) * detectionImage.height;
        
        // Couleur basée sur la catégorie (rouge pour dangereux)
        const isDangerous = window.dangerousCategories.includes(result.category);
        ctx.strokeStyle = isDangerous ? '#dc3545' : '#0d6efd';
        ctx.lineWidth = 3;
        
        // Dessiner le rectangle
        ctx.strokeRect(scaledX, scaledY, scaledW, scaledH);
        
        // Ajouter le label
        ctx.fillStyle = ctx.strokeStyle;
        ctx.font = '14px Arial';
        const confidence = Math.round(result.confidence * 100);
        const text = `${result.category} (${confidence}%)`;
        const textWidth = ctx.measureText(text).width;
        
        // Fond pour le texte
        ctx.fillRect(scaledX, scaledY - 20, textWidth + 10, 20);
        
        // Texte
        ctx.fillStyle = 'white';
        ctx.fillText(text, scaledX + 5, scaledY - 5);
      });
    };
  }
}

// Initialisation au chargement de la page
document.addEventListener('DOMContentLoaded', function() {
  initTooltips();
  initPopovers();
  setupAlertDismiss();
  setupImagePreview();
  setupBoundingBoxes();
  
  // Afficher un badge de simulation si nécessaire
  if (window.simulationMode) {
    const badge = document.createElement('div');
    badge.className = 'simulation-badge badge bg-warning text-dark';
    badge.textContent = 'Mode Simulation';
    document.body.appendChild(badge);
  }
});
