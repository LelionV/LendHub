from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from .models import DeviceToken, User, UserRole


class RoleInline(admin.TabularInline):
    model = UserRole
    extra = 0


@admin.register(User)
class LendUserAdmin(UserAdmin):
    inlines = [RoleInline]
    list_display = ("username", "full_name", "phone", "is_staff", "is_active")
    fieldsets = UserAdmin.fieldsets + (("Contact", {"fields": ("phone",)}),)
    search_fields = ("username", "first_name", "last_name", "phone", "email")


admin.site.register(DeviceToken)
