from django.contrib.auth.models import AbstractUser, BaseUserManager
from django.db import models
from django.utils.translation import gettext_lazy as _
import os

def profile_pic_path(instance, filename):
    # file will be uploaded to MEDIA_ROOT/profile_pics/<user_id>/<filename>
    _, extension = os.path.splitext(filename)
    # Utiliser instance.pk car l'ID n'est peut-être pas encore défini lors de la première sauvegarde
    user_id = instance.pk if instance.pk else 'temp'
    username = instance.email.split('@')[0] if instance.email else 'user'
    return f'profile_pics/{user_id}/{username}{extension}'

class UserManager(BaseUserManager):
    """Define a model manager for User model with no username field."""

    use_in_migrations = True

    def _create_user(self, email, password, **extra_fields):
        """Create and save a User with the given email and password."""
        if not email:
            raise ValueError(_("L'adresse e-mail doit être renseignée"))
        email = self.normalize_email(email)
        user = self.model(email=email, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_user(self, email, password=None, **extra_fields):
        """Create and save a regular User with the given email and password."""
        extra_fields.setdefault('is_staff', False)
        extra_fields.setdefault('is_superuser', False)
        return self._create_user(email, password, **extra_fields)

    def create_superuser(self, email, password, **extra_fields):
        """Create and save a SuperUser with the given email and password."""
        extra_fields.setdefault('is_staff', True)
        extra_fields.setdefault('is_superuser', True)
        extra_fields.setdefault('role', User.Role.ADMINISTRATOR) # Superusers sont Admins par défaut

        if extra_fields.get('is_staff') is not True:
            raise ValueError(_('Le superutilisateur doit avoir is_staff=True.'))
        if extra_fields.get('is_superuser') is not True:
            raise ValueError(_('Le superutilisateur doit avoir is_superuser=True.'))

        return self._create_user(email, password, **extra_fields)


class User(AbstractUser):
    """Modèle utilisateur personnalisé."""

    class Role(models.TextChoices):
        OPERATOR = 'OPERATOR', _('Opérateur (Normal Staff)') # Renommé pour clarté
        SUPERVISOR = 'SUPERVISOR', _('Superviseur (Advanced Staff)') # Renommé pour clarté
        ADMINISTRATOR = 'ADMIN', _('Administrateur')

    # Enlever le champ username standard, utiliser l'email comme identifiant unique
    username = None
    email = models.EmailField(_('adresse e-mail'), unique=True)

    # Ajouter les champs spécifiques
    role = models.CharField(_('rôle'), max_length=10, choices=Role.choices, default=Role.OPERATOR)
    profile_picture = models.ImageField(_('photo de profil'), upload_to=profile_pic_path, blank=True, null=True)
    location = models.CharField(_('localisation'), max_length=255, blank=True, null=True) # Localisation de l'opérateur

    USERNAME_FIELD = 'email'
    REQUIRED_FIELDS = [] # Email et Password sont requis par défaut.

    objects = UserManager()

    def __str__(self):
        return self.email

    # Permissions basées sur le rôle (simplifié, peut être affiné avec des groupes/permissions Django)
    @property
    def is_operator(self):
        return self.role == self.Role.OPERATOR

    @property
    def is_supervisor(self):
        return self.role == self.Role.SUPERVISOR

    @property
    def is_administrator(self):
        return self.role == self.Role.ADMINISTRATOR

