from django.db import models
from django.contrib.auth.models import AbstractUser
from django.core.validators import MinValueValidator, MaxValueValidator
from django.utils import timezone

class User(AbstractUser):
    ROLE_CHOICES = (
        ('CUSTOMER', 'Customer'),
        ('VENDOR', 'Vendor/Supplier'),
        ('ADMIN', 'Admin'),
    )
    role = models.CharField(max_length=15, choices=ROLE_CHOICES, default='CUSTOMER')
    phone_number = models.CharField(max_length=15, blank=True, null=True)
    profile_picture = models.ImageField(upload_to='profiles/', blank=True, null=True)

    def is_vendor(self):
        return self.role == 'VENDOR'

    def is_customer(self):
        return self.role == 'CUSTOMER'

    def is_admin_role(self):
        return self.role == 'ADMIN' or self.is_superuser

class VendorProfile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='vendor_profile')
    company_name = models.CharField(max_length=100, blank=True, null=True)
    license_number = models.CharField(max_length=50)
    is_approved = models.BooleanField(default=False)
    joined_date = models.DateTimeField(default=timezone.now)

    def __str__(self):
        return f"{self.user.username} - {self.company_name or 'Independent Vendor'}"

class CustomerProfile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='customer_profile')
    driver_license = models.CharField(max_length=50)
    address = models.TextField(blank=True, null=True)

    def __str__(self):
        return f"{self.user.username} - Customer"

class Car(models.Model):
    STATUS_CHOICES = (
        ('PENDING', 'Pending Approval'),
        ('APPROVED', 'Approved'),
        ('REJECTED', 'Rejected'),
    )
    CATEGORY_CHOICES = (
        ('SEDAN', 'Sedan'),
        ('SUV', 'SUV'),
        ('LUXURY', 'Luxury'),
        ('ELECTRIC', 'Electric'),
        ('SPORTS', 'Sports'),
    )
    vendor = models.ForeignKey(User, on_delete=models.CASCADE, related_name='cars')
    brand = models.CharField(max_length=50)
    model = models.CharField(max_length=50)
    year = models.PositiveIntegerField()
    category = models.CharField(max_length=15, choices=CATEGORY_CHOICES, default='SEDAN')
    transmission = models.CharField(max_length=10, choices=(('AUTO', 'Automatic'), ('MANUAL', 'Manual')), default='AUTO')
    fuel_type = models.CharField(max_length=15, choices=(('PETROL', 'Petrol'), ('DIESEL', 'Diesel'), ('ELECTRIC', 'Electric'), ('HYBRID', 'Hybrid')), default='PETROL')
    seats = models.PositiveIntegerField(default=5)
    daily_rate = models.DecimalField(max_digits=8, decimal_places=2, validators=[MinValueValidator(0.0)])
    location = models.CharField(max_length=100)
    image = models.ImageField(upload_to='cars/')
    document = models.FileField(upload_to='car_docs/', blank=True, null=True)
    status = models.CharField(max_length=15, choices=STATUS_CHOICES, default='PENDING')
    is_available = models.BooleanField(default=True)
    created_at = models.DateTimeField(default=timezone.now)

    def __str__(self):
        return f"{self.brand} {self.model} ({self.year})"

class Booking(models.Model):
    STATUS_CHOICES = (
        ('PENDING', 'Pending Vendor Approval'),
        ('APPROVED', 'Approved / Awaiting Pickup'),
        ('REJECTED', 'Rejected'),
        ('COMPLETED', 'Completed & Returned'),
        ('CANCELLED', 'Cancelled'),
    )
    PAYMENT_STATUS_CHOICES = (
        ('PENDING', 'Pending Payment'),
        ('PAID', 'Paid'),
        ('REFUNDED', 'Refunded'),
    )
    customer = models.ForeignKey(User, on_delete=models.CASCADE, related_name='bookings')
    car = models.ForeignKey(Car, on_delete=models.CASCADE, related_name='bookings')
    start_date = models.DateTimeField()
    end_date = models.DateTimeField()
    total_price = models.DecimalField(max_digits=10, decimal_places=2)
    status = models.CharField(max_length=15, choices=STATUS_CHOICES, default='PENDING')
    payment_status = models.CharField(max_length=15, choices=PAYMENT_STATUS_CHOICES, default='PENDING')
    created_at = models.DateTimeField(default=timezone.now)

    def __str__(self):
        return f"Booking #{self.id} - {self.customer.username} for {self.car}"

class Payment(models.Model):
    booking = models.OneToOneField(Booking, on_delete=models.CASCADE, related_name='payment')
    transaction_id = models.CharField(max_length=100, unique=True)
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    payment_method = models.CharField(max_length=50, default='Credit Card')
    timestamp = models.DateTimeField(default=timezone.now)

    def __str__(self):
        return f"Payment #{self.id} - {self.amount} for Booking #{self.booking.id}"

class Review(models.Model):
    customer = models.ForeignKey(User, on_delete=models.CASCADE, related_name='reviews')
    car = models.ForeignKey(Car, on_delete=models.CASCADE, related_name='reviews')
    rating = models.PositiveIntegerField(validators=[MinValueValidator(1), MaxValueValidator(5)])
    comment = models.TextField()
    created_at = models.DateTimeField(default=timezone.now)

    def __str__(self):
        return f"Review by {self.customer.username} on {self.car} - {self.rating} Stars"

class Complaint(models.Model):
    STATUS_CHOICES = (
        ('PENDING', 'Pending Resolution'),
        ('RESOLVED', 'Resolved'),
    )
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='complaints')
    subject = models.CharField(max_length=200)
    description = models.TextField()
    status = models.CharField(max_length=15, choices=STATUS_CHOICES, default='PENDING')
    created_at = models.DateTimeField(default=timezone.now)

    def __str__(self):
        return f"Complaint #{self.id} - {self.subject} ({self.status})"

class CarImage(models.Model):
    car = models.ForeignKey(Car, on_delete=models.CASCADE, related_name='images')
    image = models.ImageField(upload_to='cars/gallery/')
    created_at = models.DateTimeField(default=timezone.now)

    def __str__(self):
        return f"Image for {self.car.brand} {self.car.model}"
