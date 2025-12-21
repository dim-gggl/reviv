from allauth.socialaccount.providers.google.views import GoogleOAuth2Adapter
from allauth.socialaccount.providers.oauth2.client import OAuth2Client
from dj_rest_auth.registration.views import SocialLoginView

class GoogleLogin(SocialLoginView):
    adapter_class = GoogleOAuth2Adapter
    # callback_url doit correspondre EXACTEMENT à celle dans Google Console
    # Pour une API/App Mobile, on utilise souvent une URL vide ou localhost
    callback_url = "http://localhost:8000/accounts/google/login/callback/" 
    client_class = OAuth2Client