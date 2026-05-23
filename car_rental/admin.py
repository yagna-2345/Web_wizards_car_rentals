from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from .models import User, VendorProfile, CustomerProfile, Car, Booking, Payment, Review, Complaint, CarImage

class CustomUserAdmin(UserAdmin):
    model = User
    list_display = ['username', 'email', 'role', 'phone_number', 'is_staff']
    fieldsets = UserAdmin.fieldsets + (
        ('Custom Profile Fields', {'fields': ('role', 'phone_number', 'profile_picture')}),
    )
    add_fieldsets = UserAdmin.add_fieldsets + (
        ('Custom Profile Fields', {'fields': ('role', 'phone_number', 'profile_picture')}),
    )

admin.site.register(User, CustomUserAdmin)
admin.site.register(VendorProfile)
admin.site.register(CustomerProfile)
admin.site.register(Car)
admin.site.register(Booking)
admin.site.register(Payment)
admin.site.register(Review)
admin.site.register(Complaint)
admin.site.register(CarImage)
