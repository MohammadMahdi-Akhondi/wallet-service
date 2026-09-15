from django.db import models


class BaseApiManager(models.Manager):
    def get_queryset(self):
        return super().get_queryset().filter(deleted_at__isnull=True)


class BaseObjectsManager(models.Manager):
    def get_queryset(self):
        return super().get_queryset().all()


class BaseModel(models.Model):
    created_at = models.DateTimeField(db_index=True, auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    deleted_at = models.DateTimeField(db_index=True, null=True, blank=True)

    objects = BaseObjectsManager()
    apis = BaseApiManager()

    class Meta:
        abstract = True
