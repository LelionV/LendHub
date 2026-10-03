from django.contrib.auth.password_validation import validate_password
from rest_framework import serializers

from accounts.models import Role, User, UserRole
from funding.models import Earning, Investment
from ledger.models import Transaction
from ledger.services import wallet_balance
from loans.models import GuaranteeClaim, Installment, Loan, Repayment
from notifications.models import Notification
from rules.models import LoanProduct
from scoring.models import CreditScore


class RegisterSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True)
    roles = serializers.ListField(child=serializers.ChoiceField(choices=Role.values), min_length=1, write_only=True)

    class Meta:
        model = User
        fields = ["username", "password", "email", "phone", "first_name", "last_name", "roles"]

    def validate_password(self, v):
        validate_password(v)
        return v

    def create(self, data):
        roles = set(data.pop("roles"))
        user = User(**{k: v for k, v in data.items() if k != "password"})
        user.set_password(data["password"])
        user.save()
        UserRole.objects.bulk_create([UserRole(user=user, role=r) for r in roles])
        return user


class MeSerializer(serializers.ModelSerializer):
    roles = serializers.SerializerMethodField()
    wallet_balance = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = ["id", "username", "email", "phone", "first_name", "last_name", "roles", "wallet_balance"]
        read_only_fields = ["id", "username"]

    def get_roles(self, u): return list(u.roles.filter(is_active=True).values_list("role", flat=True))
    def get_wallet_balance(self, u): return wallet_balance(u)


class GuarantorSerializer(serializers.ModelSerializer):
    name = serializers.CharField(source="full_name")

    class Meta:
        model = User
        fields = ["id", "username", "name"]


class ProductSerializer(serializers.ModelSerializer):
    terms = serializers.ListField(child=serializers.IntegerField(), read_only=True)

    class Meta:
        model = LoanProduct
        fields = ["id", "name", "min_amount", "max_amount", "terms", "origination_fee_pct", "late_fee_pct", "grace_days"]


class QuoteInput(serializers.Serializer):
    product_id = serializers.PrimaryKeyRelatedField(queryset=LoanProduct.objects.filter(active=True), source="product")
    amount = serializers.DecimalField(max_digits=14, decimal_places=2)
    term_months = serializers.IntegerField(min_value=1)


class ApplyInput(QuoteInput):
    guarantor_id = serializers.PrimaryKeyRelatedField(queryset=User.objects.all(), source="guarantor")
    purpose = serializers.CharField(required=False, allow_blank=True, max_length=255)


class InstallmentSerializer(serializers.ModelSerializer):
    amount_due = serializers.DecimalField(max_digits=14, decimal_places=2, read_only=True)
    outstanding = serializers.DecimalField(max_digits=14, decimal_places=2, read_only=True)

    class Meta:
        model = Installment
        fields = ["number", "due_date", "principal_due", "interest_due", "late_fee_due", "amount_due",
                  "outstanding", "status", "paid_at"]


class LoanSerializer(serializers.ModelSerializer):
    borrower_name = serializers.CharField(source="borrower.full_name", read_only=True)
    guarantor_name = serializers.CharField(source="guarantor.full_name", read_only=True)
    status_display = serializers.CharField(source="get_status_display", read_only=True)
    installments = InstallmentSerializer(many=True, read_only=True)

    class Meta:
        model = Loan
        fields = ["id", "borrower", "borrower_name", "guarantor", "guarantor_name", "amount", "term_months",
                  "purpose", "interest_rate_pct", "origination_fee", "total_interest", "total_repayable",
                  "score_at_application", "status", "status_display", "guarantor_note", "admin_note",
                  "disbursed_at", "created_at", "installments"]


class LoanListSerializer(LoanSerializer):
    class Meta(LoanSerializer.Meta):
        fields = [f for f in LoanSerializer.Meta.fields if f != "installments"]


class DecisionInput(serializers.Serializer):
    note = serializers.CharField(required=False, allow_blank=True, max_length=255)


class RepaymentInput(serializers.Serializer):
    amount = serializers.DecimalField(max_digits=14, decimal_places=2)
    reference = serializers.CharField(required=False, allow_blank=True, max_length=120)


class RepaymentSerializer(serializers.ModelSerializer):
    class Meta:
        model = Repayment
        fields = ["id", "loan", "amount", "principal_part", "interest_part", "fee_part", "reference", "created_at"]


class AmountInput(serializers.Serializer):
    amount = serializers.DecimalField(max_digits=14, decimal_places=2)


class InvestmentSerializer(serializers.ModelSerializer):
    available = serializers.DecimalField(max_digits=14, decimal_places=2, read_only=True)

    class Meta:
        model = Investment
        fields = ["id", "amount", "allocated", "available", "status", "created_at"]


class EarningSerializer(serializers.ModelSerializer):
    class Meta:
        model = Earning
        fields = ["id", "loan", "role", "amount", "created_at"]


class ClaimSerializer(serializers.ModelSerializer):
    class Meta:
        model = GuaranteeClaim
        fields = ["id", "loan", "amount", "amount_paid", "status", "created_at"]


class NotificationSerializer(serializers.ModelSerializer):
    class Meta:
        model = Notification
        fields = ["id", "kind", "title", "body", "data", "is_read", "created_at"]


class TransactionSerializer(serializers.ModelSerializer):
    amount = serializers.DecimalField(max_digits=14, decimal_places=2, read_only=True)
    type_display = serializers.CharField(source="get_type_display", read_only=True)

    class Meta:
        model = Transaction
        fields = ["id", "type", "type_display", "description", "amount", "loan", "created_at"]


class CreditScoreSerializer(serializers.ModelSerializer):
    class Meta:
        model = CreditScore
        fields = ["score", "created_at"]
