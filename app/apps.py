from django.apps import AppConfig as DjangoAppConfig


class BlogAppConfig(DjangoAppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "app"
