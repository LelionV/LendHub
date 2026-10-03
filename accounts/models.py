from django.contrib.auth.models import AbstractUser
from django.db import models


class Role(models.TextChoices):
    BORROWER = "BORROWER", "Borrower"
    GUARANTOR = "GUARANTOR", "Guarantor"
    INVESTOR = "INVESTOR", "Investor"


class User(AbstractUser):
    phone = models.CharField(max_length=32, blank=True)

    def has_role(self, role) -> bool:
        return self.roles.filter(role=role, is_active=True).exists()

    @property
    def full_name(self) -> str:
        return self.get_full_name() or self.username

    def __str__(self):
        return self.full_name


class UserRole(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="roles")
    role = models.CharField(max_length=16, choices=Role.choices)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = [("user", "role")]

    def __str__(self):
        return f"{self.user} · {self.role}"


class DeviceToken(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="devices")
    token = models.CharField(max_length=255, unique=True)
    platform = models.CharField(max_length=16, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
