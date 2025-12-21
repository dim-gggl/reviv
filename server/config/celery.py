import os
from celery import Celery
from celery.schedules import crontab

# Set default Django settings
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')

app = Celery('reviv')

# Load configuration from Django settings
app.config_from_object('django.conf:settings', namespace='CELERY')

# Auto-discover tasks from installed apps
app.autodiscover_tasks()

# Periodic tasks schedule
app.conf.beat_schedule = {
    'cleanup-expired-restorations': {
        'task': 'reviv.tasks.cleanup_expired_restorations',
        'schedule': crontab(hour=2, minute=0),  # Daily at 2 AM UTC
    },
    'cleanup-failed-jobs': {
        'task': 'reviv.tasks.cleanup_failed_jobs',
        'schedule': crontab(hour=3, minute=0),  # Daily at 3 AM UTC
    },
}