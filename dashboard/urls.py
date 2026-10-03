from django.urls import path

from . import views

app_name = "dashboard"
urlpatterns = [
    path("", views.home, name="home"),
    path("loans/", views.loans, name="loans"),
    path("loans/<int:pk>/decide/", views.decide, name="decide"),
    path("process-overdue/", views.run_overdue, name="process_overdue"),
    path("export/loans.csv", views.export_loans, name="export_loans"),
    path("export/transactions.csv", views.export_transactions, name="export_transactions"),
]
