from django.conf import settings
from django.db.models import Q, Sum
from rest_framework import generics, status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.models import DeviceToken, Role, User
from core.exceptions import DomainError
from funding import services as funding
from funding.models import Earning, Investment
from ledger.models import Transaction
from ledger.services import wallet_balance
from loans import services as loan_services
from loans.models import GuaranteeClaim, Loan
from notifications.models import Notification
from rules.models import LoanProduct
from scoring.models import CreditScore
from scoring.services import compute_score

from . import serializers as s


class RegisterView(generics.CreateAPIView):
    serializer_class = s.RegisterSerializer
    permission_classes = [AllowAny]
    authentication_classes = []

    def create(self, request, *a, **kw):
        ser = self.get_serializer(data=request.data)
        ser.is_valid(raise_exception=True)
        user = ser.save()
        return Response(s.MeSerializer(user).data, status=201)


class MeView(generics.RetrieveUpdateAPIView):
    serializer_class = s.MeSerializer

    def get_object(self): return self.request.user


class CreditScoreView(APIView):
    def get(self, request):
        r = compute_score(request.user)
        band = r["band"]
        history = CreditScore.objects.filter(user=request.user)[:12]
        return Response({
            "score": r["score"], "band": band.name if band else None,
            "interest_rate_pct": band.interest_rate_pct if band else None,
            "max_loan_amount": band.max_loan_amount if band else None,
            "max_term_months": band.max_term_months if band else None,
            "breakdown": r["breakdown"], "history": s.CreditScoreSerializer(history, many=True).data,
        })


class GuarantorSearchView(generics.ListAPIView):
    serializer_class = s.GuarantorSerializer

    def get_queryset(self):
        qs = User.objects.filter(is_active=True, roles__role=Role.GUARANTOR, roles__is_active=True) \
            .exclude(pk=self.request.user.pk).distinct()
        q = self.request.query_params.get("q")
        if q:
            qs = qs.filter(Q(username__icontains=q) | Q(first_name__icontains=q) | Q(last_name__icontains=q)
                           | Q(phone__icontains=q))
        return qs.order_by("first_name", "username")


class ProductListView(generics.ListAPIView):
    serializer_class = s.ProductSerializer
    queryset = LoanProduct.objects.filter(active=True)
    pagination_class = None


class QuoteView(APIView):
    def post(self, request):
        inp = s.QuoteInput(data=request.data)
        inp.is_valid(raise_exception=True)
        d = inp.validated_data
        q = loan_services.quote(request.user, d["product"], d["amount"], d["term_months"])
        q["band"] = q["band"].name
        return Response(q)


class LoanListCreateView(generics.ListCreateAPIView):
    def get_serializer_class(self):
        return s.LoanListSerializer

    def get_queryset(self):
        return Loan.objects.filter(borrower=self.request.user).select_related("borrower", "guarantor")

    def create(self, request, *a, **kw):
        inp = s.ApplyInput(data=request.data)
        inp.is_valid(raise_exception=True)
        d = inp.validated_data
        loan = loan_services.apply_for_loan(borrower=request.user, guarantor=d["guarantor"], product=d["product"],
                                            amount=d["amount"], term_months=d["term_months"],
                                            purpose=d.get("purpose", ""))
        return Response(s.LoanSerializer(loan).data, status=201)


class LoanDetailView(generics.RetrieveAPIView):
    serializer_class = s.LoanSerializer

    def get_queryset(self):
        u = self.request.user
        qs = Loan.objects.select_related("borrower", "guarantor").prefetch_related("installments")
        return qs if u.is_staff else qs.filter(Q(borrower=u) | Q(guarantor=u))


class LoanRepayView(APIView):
    def post(self, request, pk):
        loan = generics.get_object_or_404(Loan, pk=pk)
        if not (request.user.is_staff or (settings.ALLOW_SELF_REPORTED_REPAYMENTS and loan.borrower_id == request.user.pk)):
            return Response({"detail": "Not allowed."}, status=403)
        inp = s.RepaymentInput(data=request.data)
        inp.is_valid(raise_exception=True)
        rep = loan_services.record_repayment(loan=loan, amount=inp.validated_data["amount"],
                                             reference=inp.validated_data.get("reference", ""),
                                             recorded_by=request.user)
        return Response(s.RepaymentSerializer(rep).data, status=201)


class GuaranteeRequestListView(generics.ListAPIView):
    serializer_class = s.LoanListSerializer

    def get_queryset(self):
        qs = Loan.objects.filter(guarantor=self.request.user).select_related("borrower", "guarantor")
        if self.request.query_params.get("status") == "pending":
            qs = qs.filter(status=Loan.Status.PENDING_GUARANTOR)
        return qs


class GuaranteeDecisionView(APIView):
    approve = True

    def post(self, request, pk):
        loan = generics.get_object_or_404(Loan, pk=pk, guarantor=request.user)
        inp = s.DecisionInput(data=request.data)
        inp.is_valid(raise_exception=True)
        loan = loan_services.guarantor_decide(loan, request.user, self.approve, inp.validated_data.get("note", ""))
        return Response(s.LoanListSerializer(loan).data)


class GuarantorClaimsView(generics.ListAPIView):
    serializer_class = s.ClaimSerializer

    def get_queryset(self): return GuaranteeClaim.objects.filter(guarantor=self.request.user)


class EarningsView(APIView):
    role = Earning.Role.INVESTOR

    def get(self, request):
        qs = Earning.objects.filter(user=request.user, role=self.role)
        total = qs.aggregate(t=Sum("amount"))["t"] or 0
        return Response({"total": total, "wallet_balance": wallet_balance(request.user),
                         "items": s.EarningSerializer(qs[:100], many=True).data})


class InvestmentListCreateView(generics.ListCreateAPIView):
    serializer_class = s.InvestmentSerializer

    def get_queryset(self): return Investment.objects.filter(investor=self.request.user)

    def create(self, request, *a, **kw):
        inp = s.AmountInput(data=request.data)
        inp.is_valid(raise_exception=True)
        inv = funding.invest(request.user, inp.validated_data["amount"])
        return Response(s.InvestmentSerializer(inv).data, status=201)


class InvestmentWithdrawView(APIView):
    def post(self, request, pk):
        inv = generics.get_object_or_404(Investment, pk=pk, investor=request.user)
        inp = s.AmountInput(data=request.data)
        inp.is_valid(raise_exception=True)
        return Response(s.InvestmentSerializer(funding.withdraw_investment(inv, inp.validated_data["amount"],
                                                                           request.user)).data)


class InvestmentSummaryView(APIView):
    def get(self, request):
        qs = Investment.objects.filter(investor=request.user, status=Investment.Status.ACTIVE)
        agg = qs.aggregate(invested=Sum("amount"), lent=Sum("allocated"))
        invested, lent = agg["invested"] or 0, agg["lent"] or 0
        earned = Earning.objects.filter(user=request.user, role=Earning.Role.INVESTOR).aggregate(t=Sum("amount"))["t"] or 0
        return Response({"invested": invested, "lent_out": lent, "available": invested - lent,
                         "total_earned": earned, "wallet_balance": wallet_balance(request.user)})


class WalletWithdrawView(APIView):
    def post(self, request):
        inp = s.AmountInput(data=request.data)
        inp.is_valid(raise_exception=True)
        funding.withdraw_earnings(request.user, inp.validated_data["amount"])
        return Response({"wallet_balance": wallet_balance(request.user)})


class NotificationListView(generics.ListAPIView):
    serializer_class = s.NotificationSerializer

    def get_queryset(self): return Notification.objects.filter(user=self.request.user)


class NotificationReadView(APIView):
    def post(self, request, pk=None):
        qs = Notification.objects.filter(user=request.user)
        if pk:
            qs = qs.filter(pk=pk)
        return Response({"updated": qs.update(is_read=True)})


class DeviceTokenView(APIView):
    def post(self, request):
        token = (request.data.get("token") or "").strip()
        if not token:
            raise DomainError("token is required")
        DeviceToken.objects.update_or_create(token=token, defaults={"user": request.user,
                                             "platform": request.data.get("platform", "")})
        return Response(status=status.HTTP_204_NO_CONTENT)


class TransactionListView(generics.ListAPIView):
    serializer_class = s.TransactionSerializer

    def get_queryset(self):
        u = self.request.user
        return Transaction.objects.filter(Q(entries__account__user=u) | Q(loan__borrower=u) |
                                          Q(created_by=u, type__in=["INVESTMENT", "INVESTMENT_WITHDRAWAL"])
                                          ).distinct()
