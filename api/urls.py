from django.urls import path
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView

from funding.models import Earning

from . import views as v

urlpatterns = [
    path("auth/register/", v.RegisterView.as_view()),
    path("auth/login/", TokenObtainPairView.as_view()),
    path("auth/refresh/", TokenRefreshView.as_view()),
    path("me/", v.MeView.as_view()),
    path("credit-score/", v.CreditScoreView.as_view()),
    path("guarantors/", v.GuarantorSearchView.as_view()),
    path("loan-products/", v.ProductListView.as_view()),
    path("loans/quote/", v.QuoteView.as_view()),
    path("loans/", v.LoanListCreateView.as_view()),
    path("loans/<int:pk>/", v.LoanDetailView.as_view()),
    path("loans/<int:pk>/repay/", v.LoanRepayView.as_view()),
    path("guarantees/requests/", v.GuaranteeRequestListView.as_view()),
    path("guarantees/requests/<int:pk>/approve/", v.GuaranteeDecisionView.as_view(approve=True)),
    path("guarantees/requests/<int:pk>/reject/", v.GuaranteeDecisionView.as_view(approve=False)),
    path("guarantor/claims/", v.GuarantorClaimsView.as_view()),
    path("guarantor/earnings/", v.EarningsView.as_view(role=Earning.Role.GUARANTOR)),
    path("investments/", v.InvestmentListCreateView.as_view()),
    path("investments/summary/", v.InvestmentSummaryView.as_view()),
    path("investments/earnings/", v.EarningsView.as_view(role=Earning.Role.INVESTOR)),
    path("investments/<int:pk>/withdraw/", v.InvestmentWithdrawView.as_view()),
    path("wallet/withdraw/", v.WalletWithdrawView.as_view()),
    path("notifications/", v.NotificationListView.as_view()),
    path("notifications/read-all/", v.NotificationReadView.as_view()),
    path("notifications/<int:pk>/read/", v.NotificationReadView.as_view()),
    path("devices/", v.DeviceTokenView.as_view()),
    path("transactions/", v.TransactionListView.as_view()),
]
