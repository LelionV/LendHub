from django.core.management.base import BaseCommand

from accounts.models import Role, User
from scoring.services import compute_score


class Command(BaseCommand):
    help = "Recompute credit scores for all borrowers (run nightly)."

    def handle(self, *args, **opts):
        n = 0
        for u in User.objects.filter(roles__role=Role.BORROWER, roles__is_active=True).distinct():
            compute_score(u)
            n += 1
        self.stdout.write(f"Recomputed {n} scores.")
