from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import login, authenticate, logout
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.db.models import Sum
from django.utils import timezone
from datetime import datetime
import uuid
from django.core.mail import send_mail
from django.conf import settings

from .models import User, VendorProfile, CustomerProfile, Car, Booking, Payment, Review, Complaint, CarImage

# Home / Landing view
def home(request):
    featured_cars = Car.objects.filter(status='APPROVED', is_available=True)[:6]
    return render(request, 'index.html', {'featured_cars': featured_cars})

# Custom Registration
def register_view(request):
    if request.user.is_authenticated:
        return redirect('dashboard')
        
    if request.method == 'POST':
        username = request.POST.get('username')
        email = request.POST.get('email')
        password = request.POST.get('password')
        password_confirm = request.POST.get('password_confirm')
        phone_number = request.POST.get('phone_number')
        role = request.POST.get('role')

        if password != password_confirm:
            messages.error(request, "Passwords do not match!")
            return redirect('register')
            
        if User.objects.filter(username=username).exists():
            messages.error(request, "Username already exists!")
            return redirect('register')

        first_name = request.POST.get('first_name')

        # Create Custom User
        user = User.objects.create_user(
            username=username, 
            email=email, 
            password=password,
            first_name=first_name,
            phone_number=phone_number,
            role=role
        )

        # Create Profile based on Role
        if role == 'VENDOR':
            company_name = request.POST.get('company_name')
            license_number = request.POST.get('license_number')
            VendorProfile.objects.create(
                user=user,
                company_name=company_name,
                license_number=license_number,
                is_approved=False # Requires Admin approval
            )
            messages.success(request, "Vendor account registered! Awaiting admin approval.")
        else: # CUSTOMER
            driver_license = request.POST.get('driver_license')
            address = request.POST.get('address')
            CustomerProfile.objects.create(
                user=user,
                driver_license=driver_license,
                address=address
            )
            messages.success(request, "Customer account registered successfully!")

        login(request, user)
        return redirect('dashboard')

    return render(request, 'register.html')

# Custom Login View
def login_view(request):
    if request.user.is_authenticated:
        return redirect('dashboard')

    if request.method == 'POST':
        username = request.POST.get('username')
        password = request.POST.get('password')
        
        user = authenticate(request, username=username, password=password)
        if user is not None:
            login(request, user)
            messages.success(request, f"Welcome back, {user.username}!")
            return redirect('dashboard')
        else:
            messages.error(request, "Invalid username or password.")
            return redirect('login')

    return render(request, 'login.html')

# Custom Logout View
def logout_view(request):
    logout(request)
    messages.success(request, "You have been logged out.")
    return redirect('home')

# Dashboard Redirect Router
@login_required
def dashboard(request):
    if request.user.is_superuser or request.user.role == 'ADMIN':
        return dashboard_admin(request)
    elif request.user.role == 'VENDOR':
        return dashboard_vendor(request)
    else:
        return dashboard_customer(request)

# Customer Dashboard
@login_required
def dashboard_customer(request):
    if request.user.role != 'CUSTOMER':
        return redirect('dashboard')
        
    bookings = Booking.objects.filter(customer=request.user).order_by('-created_at')
    complaints = Complaint.objects.filter(user=request.user).order_by('-created_at')
    
    # Calculate if each booking can be cancelled within 24 hours
    from datetime import timedelta
    now = timezone.now()
    for booking in bookings:
        time_elapsed = now - booking.created_at
        booking.can_cancel = (
            booking.status not in ['COMPLETED', 'REJECTED', 'CANCELLED'] and
            time_elapsed <= timedelta(hours=24)
        )
    
    # spent calculation
    total_spent = Booking.objects.filter(customer=request.user, payment_status='PAID').aggregate(Sum('total_price'))['total_price__sum'] or 0.00
    active_bookings_count = bookings.filter(status='APPROVED', payment_status='PAID').count()
    total_bookings_count = bookings.count()

    context = {
        'bookings': bookings,
        'complaints': complaints,
        'total_spent': total_spent,
        'active_bookings_count': active_bookings_count,
        'total_bookings_count': total_bookings_count,
    }
    return render(request, 'dashboard_customer.html', context)

# Vendor Dashboard
@login_required
def dashboard_vendor(request):
    if request.user.role != 'VENDOR':
        return redirect('dashboard')

    vendor_profile, created = VendorProfile.objects.get_or_create(
        user=request.user, 
        defaults={'license_number': 'N/A', 'is_approved': False}
    )
    cars = Car.objects.filter(vendor=request.user).order_by('-created_at')
    
    # Bookings relating to this vendor's cars
    bookings = Booking.objects.filter(car__vendor=request.user).order_by('-created_at')
    
    pending_bookings_count = bookings.filter(status='PENDING').count()
    
    # Calculate earnings (completed or approved rentals)
    total_earnings = Booking.objects.filter(
        car__vendor=request.user, 
        payment_status='PAID'
    ).aggregate(Sum('total_price'))['total_price__sum'] or 0.00

    context = {
        'vendor_profile': vendor_profile,
        'cars': cars,
        'bookings': bookings,
        'pending_bookings_count': pending_bookings_count,
        'total_earnings': total_earnings,
    }
    return render(request, 'dashboard_vendor.html', context)

# Admin Dashboard
@login_required
def dashboard_admin(request):
    if not request.user.is_superuser and request.user.role != 'ADMIN':
        return redirect('dashboard')

    pending_vendors = VendorProfile.objects.filter(is_approved=False).order_by('-joined_date')
    pending_cars = Car.objects.filter(status='PENDING').order_by('-created_at')
    active_complaints = Complaint.objects.filter(status='PENDING').order_by('-created_at')
    all_vendors = VendorProfile.objects.all().select_related('user').prefetch_related('user__cars').order_by('-joined_date')
    
    pending_vendors_count = pending_vendors.count()
    pending_cars_count = pending_cars.count()
    
    # total platform revenue (all paid bookings)
    total_revenue = Booking.objects.filter(payment_status='PAID').aggregate(Sum('total_price'))['total_price__sum'] or 0.00

    context = {
        'pending_vendors': pending_vendors,
        'pending_cars': pending_cars,
        'active_complaints': active_complaints,
        'all_vendors': all_vendors,
        'pending_vendors_count': pending_vendors_count,
        'pending_cars_count': pending_cars_count,
        'total_revenue': total_revenue,
    }
    return render(request, 'dashboard_admin.html', context)

# Add Car View
@login_required
def add_car(request):
    if request.user.role != 'VENDOR':
        messages.error(request, "Only vendors can list vehicles.")
        return redirect('dashboard')

    vendor_profile = VendorProfile.objects.filter(user=request.user).first()
    
    if request.method == 'POST':
        brand = request.POST.get('brand')
        model = request.POST.get('model')
        year = request.POST.get('year')
        category = request.POST.get('category')
        transmission = request.POST.get('transmission')
        fuel_type = request.POST.get('fuel_type')
        seats = request.POST.get('seats')
        daily_rate = request.POST.get('daily_rate')
        location = request.POST.get('location')
        images = request.FILES.getlist('images')
        document = request.FILES.get('document')

        cover_image = images[0] if images else None

        car = Car.objects.create(
            vendor=request.user,
            brand=brand,
            model=model,
            year=year,
            category=category,
            transmission=transmission,
            fuel_type=fuel_type,
            seats=seats,
            daily_rate=daily_rate,
            location=location,
            image=cover_image,
            document=document,
            status='PENDING', # Requires Admin verification
            is_available=True
        )

        # Save all uploaded images in CarImage model
        for img in images:
            CarImage.objects.create(car=car, image=img)

        messages.success(request, f"{car.brand} {car.model} uploaded with {len(images)} photos! It will be listed once reviewed by administration.")
        return redirect('dashboard')

    return redirect('dashboard')

# Toggle Car Availability
@login_required
def toggle_car_availability(request, car_id):
    car = get_object_or_404(Car, id=car_id)
    if car.vendor != request.user:
        messages.error(request, "Unauthorized access.")
        return redirect('dashboard')
        
    car.is_available = not car.is_available
    car.save()
    messages.success(request, f"Availability status for {car.brand} {car.model} updated!")
    return redirect('dashboard')

# Browse & Filter Cars
def car_search(request):
    location = request.GET.get('location')
    category = request.GET.get('category')
    transmission = request.GET.get('transmission')
    max_price = request.GET.get('max_price')

    # Only approved and available cars
    cars = Car.objects.filter(status='APPROVED')

    if location:
        cars = cars.filter(location__icontains=location)
    if category:
        cars = cars.filter(category=category)
    if transmission:
        cars = cars.filter(transmission=transmission)
    if max_price:
        cars = cars.filter(daily_rate__lte=max_price)

    return render(request, 'car_search.html', {'cars': cars})

# Car Detail Page
def car_detail(request, car_id):
    car = get_object_or_404(Car, id=car_id)
    reviews = Review.objects.filter(car=car).order_by('-created_at')
    return render(request, 'car_detail.html', {'car': car, 'reviews': reviews})

# Book Car Flow
@login_required
def book_car(request, car_id):
    if request.user.role != 'CUSTOMER':
        messages.error(request, "Only customer accounts can book cars.")
        return redirect('car_detail', car_id=car_id)

    car = get_object_or_404(Car, id=car_id)
    if car.status != 'APPROVED':
        messages.error(request, "This vehicle listing is not currently approved for rentals.")
        return redirect('car_search')
    if not car.is_available:
        messages.error(request, "This vehicle is currently unavailable for rent.")
        return redirect('car_detail', car_id=car_id)

    if request.method == 'POST':
        start_date_str = request.POST.get('start_date')
        end_date_str = request.POST.get('end_date')

        try:
            start_date = timezone.make_aware(datetime.strptime(start_date_str, "%Y-%m-%dT%H:%M"))
            end_date = timezone.make_aware(datetime.strptime(end_date_str, "%Y-%m-%dT%H:%M"))
        except ValueError:
            # Fallback for standard date strings (from automated unit tests)
            try:
                start_date = timezone.make_aware(datetime.strptime(start_date_str, "%Y-%m-%d"))
                end_date = timezone.make_aware(datetime.strptime(end_date_str, "%Y-%m-%d"))
            except ValueError:
                messages.error(request, "Invalid date-time format.")
                return redirect('car_detail', car_id=car_id)

        if end_date < start_date:
            messages.error(request, "Return date cannot be before pickup date.")
            return redirect('car_detail', car_id=car_id)

        # Double Booking conflict check
        overlapping_bookings = Booking.objects.filter(
            car=car,
            status__in=['APPROVED', 'PENDING'],
            start_date__lte=end_date,
            end_date__gte=start_date
        ).exists()

        if overlapping_bookings:
            messages.error(request, "This vehicle is already reserved for the selected dates.")
            return redirect('car_detail', car_id=car_id)

        # Duration & price calculation based on hours rounded up to days
        duration = end_date - start_date
        hours = duration.total_seconds() / 3600
        import math
        days = math.ceil(hours / 24)
        if days <= 0:
            days = 1
        total_price = days * car.daily_rate

        booking = Booking.objects.create(
            customer=request.user,
            car=car,
            start_date=start_date,
            end_date=end_date,
            total_price=total_price,
            status='PENDING',
            payment_status='PENDING'
        )

        messages.success(request, "Rental booking requested! Awaiting Supplier approval.")
        return redirect('dashboard')

    return redirect('car_detail', car_id=car_id)

# Approve Booking (Vendor Action)
@login_required
def approve_booking(request, booking_id):
    booking = get_object_or_404(Booking, id=booking_id)
    if booking.car.vendor != request.user:
        messages.error(request, "Unauthorized access.")
        return redirect('dashboard')

    booking.status = 'APPROVED'
    # Lock vehicle availability
    booking.car.is_available = False
    booking.car.save()
    booking.save()

    # Send confirmation email to customer
    subject = f"Booking Confirmed: Booking #{booking.id} - Web Wizards Car Rentals"
    message = (
        f"Hello {booking.customer.username},\n\n"
        f"We are excited to let you know that your rental booking for {booking.car.brand} {booking.car.model} "
        f"has been confirmed by the supplier!\n\n"
        f"Booking details:\n"
        f"- Car: {booking.car.brand} {booking.car.model} ({booking.car.year})\n"
        f"- Pick-up: {booking.start_date.strftime('%Y-%m-%d %H:%M')}\n"
        f"- Return: {booking.end_date.strftime('%Y-%m-%d %H:%M')}\n"
        f"- Total Cost: ${booking.total_price}\n\n"
        f"Please proceed to your dashboard to complete the payment and activate your rental:\n"
        f"http://127.0.0.1:8000/dashboard/\n\n"
        f"Thank you for choosing Web Wizards Car Rentals!\n"
        f"Best regards,\n"
        f"Web Wizards Car Rentals Team"
    )
    recipient_list = [booking.customer.email]
    try:
        send_mail(
            subject,
            message,
            settings.DEFAULT_FROM_EMAIL,
            recipient_list,
            fail_silently=True
        )
    except Exception:
        pass

    messages.success(request, f"Booking request #{booking.id} approved! Awaiting Customer payment.")
    return redirect('dashboard')

# Reject Booking (Vendor Action)
@login_required
def reject_booking(request, booking_id):
    booking = get_object_or_404(Booking, id=booking_id)
    if booking.car.vendor != request.user:
        messages.error(request, "Unauthorized access.")
        return redirect('dashboard')

    booking.status = 'REJECTED'
    booking.save()

    messages.success(request, f"Booking request #{booking.id} rejected.")
    return redirect('dashboard')

# Checkout Simulation
@login_required
def payment_checkout(request, booking_id):
    booking = get_object_or_404(Booking, id=booking_id, customer=request.user, status='APPROVED', payment_status='PENDING')
    return render(request, 'checkout.html', {'booking': booking})

# Complete Payment
@login_required
def payment_submit(request, booking_id):
    booking = get_object_or_404(Booking, id=booking_id, customer=request.user, status='APPROVED', payment_status='PENDING')
    
    if request.method == 'POST':
        # Simulated payment completion
        transaction_id = f"TXN-{uuid.uuid4().hex[:8].upper()}"
        
        # Save payment details
        Payment.objects.create(
            booking=booking,
            transaction_id=transaction_id,
            amount=booking.total_price,
            payment_method='Credit Card'
        )

        # Update booking
        booking.payment_status = 'PAID'
        booking.save()

        # Send payment confirmation email to customer
        subject = f"Payment Confirmation: Booking #{booking.id} - Web Wizards Car Rentals"
        message = (
            f"Hello {booking.customer.username},\n\n"
            f"Thank you for your payment! Your transaction has been processed successfully.\n\n"
            f"Payment details:\n"
            f"- Booking ID: #{booking.id}\n"
            f"- Transaction ID: {transaction_id}\n"
            f"- Amount Paid: ${booking.total_price}\n"
            f"- Car: {booking.car.brand} {booking.car.model} ({booking.car.year})\n"
            f"- Pick-up Time: {booking.start_date.strftime('%Y-%m-%d %H:%M')}\n"
            f"- Return Time: {booking.end_date.strftime('%Y-%m-%d %H:%M')}\n\n"
            f"Your rental is now fully active. Enjoy your ride!\n\n"
            f"Best regards,\n"
            f"Web Wizards Car Rentals Team"
        )
        recipient_list = [booking.customer.email]
        try:
            send_mail(
                subject,
                message,
                settings.DEFAULT_FROM_EMAIL,
                recipient_list,
                fail_silently=True
            )
        except Exception:
            pass

        messages.success(request, f"Payment successful! Transaction ID: {transaction_id}")
        return redirect('dashboard')

    return redirect('payment_checkout', booking_id=booking_id)

# Return Car (Vendor Action)
@login_required
def return_car(request, booking_id):
    booking = get_object_or_404(Booking, id=booking_id, car__vendor=request.user, status='APPROVED', payment_status='PAID')
    
    booking.status = 'COMPLETED'
    booking.save()
    
    # Release car availability
    booking.car.is_available = True
    booking.car.save()

    messages.success(request, f"Vehicle successfully marked as returned and listing availability released!")
    return redirect('dashboard')

# Write Review (Customer Action)
@login_required
def car_review(request, car_id):
    car = get_object_or_404(Car, id=car_id)
    if request.user.role != 'CUSTOMER':
        messages.error(request, "Only customer accounts can write reviews.")
        return redirect('dashboard')

    if request.method == 'POST':
        rating = request.POST.get('rating')
        comment = request.POST.get('comment')

        Review.objects.create(
            customer=request.user,
            car=car,
            rating=rating,
            comment=comment
        )
        messages.success(request, "Review submitted successfully!")
        
    return redirect('car_detail', car_id=car.id)

# Raise Complaint Dispute (Customer Action)
@login_required
def raise_complaint(request):
    if request.method == 'POST':
        subject = request.POST.get('subject')
        description = request.POST.get('description')

        Complaint.objects.create(
            user=request.user,
            subject=subject,
            description=description,
            status='PENDING'
        )
        messages.success(request, "Complaint ticket raised successfully. Admin team will review.")
        
    return redirect('dashboard')

# Verify Vendor (Admin Action)
@login_required
def verify_vendor(request, profile_id, action):
    if not request.user.is_superuser and request.user.role != 'ADMIN':
        messages.error(request, "Access restricted to administrators.")
        return redirect('dashboard')

    profile = get_object_or_404(VendorProfile, id=profile_id)
    if action == 'APPROVE':
        profile.is_approved = True
        profile.save()
        messages.success(request, f"Supplier application for {profile.user.username} approved!")
    else:
        profile.user.delete() # Deletes user account if application is rejected
        messages.success(request, "Supplier application rejected and account removed.")

    return redirect('dashboard')

# Verify Car Listing (Admin Action)
@login_required
def verify_car(request, car_id, action):
    if not request.user.is_superuser and request.user.role != 'ADMIN':
        messages.error(request, "Access restricted to administrators.")
        return redirect('dashboard')

    car = get_object_or_404(Car, id=car_id)
    if action == 'APPROVE':
        car.status = 'APPROVED'
        car.save()
        messages.success(request, f"Listing for {car.brand} {car.model} approved & visible to customers.")
    else:
        car.status = 'REJECTED'
        car.save()
        messages.success(request, f"Listing for {car.brand} {car.model} rejected.")

    return redirect('dashboard')

# Resolve Complaint (Admin Action)
@login_required
def resolve_complaint(request, complaint_id):
    if not request.user.is_superuser and request.user.role != 'ADMIN':
        messages.error(request, "Access restricted to administrators.")
        return redirect('dashboard')

    complaint = get_object_or_404(Complaint, id=complaint_id)
    complaint.status = 'RESOLVED'
    complaint.save()
    messages.success(request, f"Complaint ticket #{complaint.id} resolved.")
    return redirect('dashboard')

# Edit Car (Vendor Action)
@login_required
def edit_car(request, car_id):
    car = get_object_or_404(Car, id=car_id)
    if car.vendor != request.user:
        messages.error(request, "Unauthorized access.")
        return redirect('dashboard')

    if request.method == 'POST':
        car.brand = request.POST.get('brand')
        car.model = request.POST.get('model')
        car.year = request.POST.get('year')
        car.category = request.POST.get('category')
        car.transmission = request.POST.get('transmission')
        car.fuel_type = request.POST.get('fuel_type')
        car.seats = request.POST.get('seats')
        car.daily_rate = request.POST.get('daily_rate')
        car.location = request.POST.get('location')

        # Handle optional new document
        document = request.FILES.get('document')
        if document:
            car.document = document

        # Handle optional new images
        images = request.FILES.getlist('images')
        if images:
            # Overwrite current images
            car.images.all().delete()
            car.image = images[0]
            for img in images:
                CarImage.objects.create(car=car, image=img)

        # Set status back to pending since details changed
        car.status = 'PENDING'
        car.save()

        messages.success(request, f"Listing for {car.brand} {car.model} successfully updated and resubmitted for admin approval!")
        return redirect('dashboard')

    return render(request, 'edit_car.html', {'car': car})

# Delete Car (Vendor Action)
@login_required
def delete_car(request, car_id):
    if request.method == 'POST':
        car = get_object_or_404(Car, id=car_id)
        if car.vendor != request.user:
            messages.error(request, "Unauthorized access.")
            return redirect('dashboard')

        car.delete()
        messages.success(request, f"Vehicle listing deleted successfully.")
    return redirect('dashboard')

# Cancel Booking (Customer Action within 24 hours)
@login_required
def cancel_booking(request, booking_id):
    booking = get_object_or_404(Booking, id=booking_id)
    
    # Must be the customer who created the booking
    if booking.customer != request.user:
        messages.error(request, "Unauthorized access.")
        return redirect('dashboard')

    # Cannot cancel completed, already rejected, or already cancelled bookings
    if booking.status in ['COMPLETED', 'REJECTED', 'CANCELLED']:
        messages.error(request, "This booking cannot be cancelled in its current state.")
        return redirect('dashboard')

    # Time Constraint: within 24 hours of booking timestamp (created_at)
    from datetime import timedelta
    time_elapsed = timezone.now() - booking.created_at
    if time_elapsed > timedelta(hours=24):
        messages.error(request, "Cancellation window has expired. Bookings can only be cancelled within 24 hours of creation.")
        return redirect('dashboard')

    # Cancel booking
    booking.status = 'CANCELLED'
    
    # If paid, refund it
    if booking.payment_status == 'PAID':
        booking.payment_status = 'REFUNDED'
        messages.success(request, f"Booking #{booking.id} cancelled! A simulated refund has been credited to your card.")
    else:
        messages.success(request, f"Booking #{booking.id} has been cancelled successfully.")
        
    booking.save()

    # Release car availability
    booking.car.is_available = True
    booking.car.save()

    return redirect('dashboard')

# Edit Profile (Customer & Vendor Action)
@login_required
def edit_profile(request):
    user = request.user
    
    if user.role == 'VENDOR':
        profile, created = VendorProfile.objects.get_or_create(user=user)
    elif user.role == 'CUSTOMER':
        profile, created = CustomerProfile.objects.get_or_create(user=user)
    else:
        profile = None

    if request.method == 'POST':
        first_name = request.POST.get('first_name')
        email = request.POST.get('email')
        phone_number = request.POST.get('phone_number')
        
        # Update user fields
        user.first_name = first_name
        user.email = email
        user.phone_number = phone_number
        user.save()
        
        # Update specific profile fields
        if user.role == 'VENDOR':
            profile.company_name = request.POST.get('company_name')
            profile.license_number = request.POST.get('license_number')
            profile.save()
        elif user.role == 'CUSTOMER':
            profile.driver_license = request.POST.get('driver_license')
            profile.address = request.POST.get('address')
            profile.save()
            
        messages.success(request, "Your profile has been updated successfully!")
        return redirect('dashboard')
        
    context = {
        'profile': profile,
    }
    return render(request, 'edit_profile.html', context)
