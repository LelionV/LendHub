from django.core.management.base import BaseCommand

from loans.services import process_overdue


class Command(BaseCommand):
    help = "Mark overdue installments, charge late fees, default loans, open guarantee claims (run daily)."

    def handle(self, *args, **opts):
        self.stdout.write(str(process_overdue()))
