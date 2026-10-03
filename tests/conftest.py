import pytest
from django.core.management import call_command
from rest_framework.test import APIClient

from accounts.models import Role, User, UserRole


@pytest.fixture
def seeded(db):
    call_command("seed_defaults")


def make_user(name, *roles, staff=False):
    u = User.objects.create_user(name, f"{name}@x.com", "S3cure-pass!", is_staff=staff, is_superuser=staff)
    for r in roles:
        UserRole.objects.create(user=u, role=r)
    return u


@pytest.fixture
def borrower(seeded): return make_user("bob", Role.BORROWER)
@pytest.fixture
def guarantor(seeded): return make_user("gina", Role.GUARANTOR)
@pytest.fixture
def investor(seeded): return make_user("ivan", Role.INVESTOR)
@pytest.fixture
def admin(seeded): return make_user("root", staff=True)


def client_for(user):
    c = APIClient()
    c.force_authenticate(user)
    return c


@pytest.fixture(autouse=True)
def fast_password_hashing(settings):
    settings.PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]
