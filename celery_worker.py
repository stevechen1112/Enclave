from celery import Celery

app = Celery('enclave')
app.config_from_object('app.celery_app')
app.autodiscover_tasks(['app.tasks'])
