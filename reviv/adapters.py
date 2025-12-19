from allauth.account.adapter import DefaultAccountAdapter
from allauth.socialaccount.adapter import DefaultSocialAccountAdapter
from allauth.exceptions import ImmediateHttpResponse
from django.shortcuts import render

class StrictSecurityAdapter(DefaultAccountAdapter):
    def is_open_for_signup(self, request):
        # Fermeture totale de l'inscription locale explicite
        return False

class StrictSocialAdapter(DefaultSocialAccountAdapter):
    def pre_social_login(self, request, sociallogin):
        # Vérification stricte de l'email fourni par l'IdP
        email = sociallogin.user.email
        if not email:
            # Rejeter les comptes sans email (ex: config Apple mal faite)
            raise ImmediateHttpResponse(render(request, 'error_no_email.html'))

        # (Optionnel selon le texte) : Ajouter ici une logique de whitelist/blacklist de domaines