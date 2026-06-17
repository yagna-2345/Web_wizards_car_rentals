from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import login, authenticate, logout
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.db.models import Sum
from django.utils import timezone
from django.http import JsonResponse
from datetime import datetime
import uuid
import random
import json
import urllib.request
from django.core.mail import send_mail
from django.conf import settings

from .models import User, VendorProfile, CustomerProfile, Car, Booking, Payment, Review, Complaint, CarImage, Discount

# Home / Landing view
def home(request):
    featured_cars = Car.objects.filter(status='APPROVED', is_available=True)[:6]
    
    lat = request.session.get('user_latitude')
    lon = request.session.get('user_longitude')
    
    car_list = list(featured_cars)
    if lat is not None and lon is not None:
        import math
        for car in car_list:
            if car.latitude is not None and car.longitude is not None:
                R = 6371.0
                dlat = math.radians(car.latitude - lat)
                dlon = math.radians(car.longitude - lon)
                a = math.sin(dlat / 2)**2 + math.cos(math.radians(lat)) * math.cos(math.radians(car.latitude)) * math.sin(dlon / 2)**2
                c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
                car.distance = round(R * c, 1)
            else:
                car.distance = None
    else:
        for car in car_list:
            car.distance = None
            
    return render(request, 'index.html', {'featured_cars': car_list})

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

        if User.objects.filter(email=email).exists():
            messages.error(request, "Email address already registered!")
            return redirect('register')

        first_name = request.POST.get('first_name')

        # Generate a random 6-digit OTP
        otp = str(random.randint(100000, 999999))

        # Store pending data in request.session
        request.session['pending_registration'] = {
            'username': username,
            'email': email,
            'password': password,
            'first_name': first_name,
            'phone_number': phone_number,
            'role': role,
            'company_name': request.POST.get('company_name', ''),
            'license_number': request.POST.get('license_number', ''),
            'driver_license': request.POST.get('driver_license', ''),
            'address': request.POST.get('address', '')
        }
        request.session['registration_otp'] = otp

        # Send OTP email
        subject = "Verify Your Registration - Web Wizards Car Rentals"
        message = (
            f"Hello {first_name or username},\n\n"
            f"Thank you for signing up with Web Wizards Car Rentals!\n\n"
            f"To complete your registration, please verify your email using this 6-digit One-Time Password (OTP):\n\n"
            f"   >>>  {otp}  <<<\n\n"
            f"This code is valid for 10 minutes. If you did not request this, please ignore this email.\n\n"
            f"Best regards,\n"
            f"Web Wizards Car Rentals Team"
        )
        recipient_list = [email]
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

        # Print OTP to console for easy local testing/verification
        print(f"==================================================")
        print(f"  OTP GENERATED FOR {username}: {otp}")
        print(f"==================================================")

        messages.success(request, "A 6-digit verification code has been sent to your email. Please enter it to complete registration.")
        return redirect('verify_otp')

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

    # Expose active APPROVED promos across platform
    active_discounts = Discount.objects.filter(status='APPROVED').select_related('car', 'car__vendor').order_by('-discount_percentage')

    # Calculate real-time availability and formatted scheduled ranges
    for promo in active_discounts:
        car = promo.car
        # Check current date-time overlaps
        has_overlap = Booking.objects.filter(
            car=car,
            status__in=['APPROVED', 'PENDING'],
            start_date__lte=now,
            end_date__gte=now
        ).exists()
        promo.car_currently_available = car.is_available and not has_overlap

        # Fetch all future active bookings to format unavailable ranges
        future_bookings = Booking.objects.filter(
            car=car,
            status__in=['APPROVED', 'PENDING'],
            end_date__gte=now
        ).order_by('start_date')
        
        if not car.is_available:
            promo.availability_text = "Status: Temporarily Unavailable"
        elif not future_bookings.exists():
            promo.availability_text = "Available: Instantly (Everyday)"
        else:
            ranges = []
            for b in future_bookings:
                start_str = b.start_date.strftime('%b %d')
                end_str = b.end_date.strftime('%b %d')
                ranges.append(f"{start_str} to {end_str}")
            promo.availability_text = "Unavailable dates: " + ", ".join(ranges)

    context = {
        'bookings': bookings,
        'complaints': complaints,
        'total_spent': total_spent,
        'active_bookings_count': active_bookings_count,
        'total_bookings_count': total_bookings_count,
        'active_discounts': active_discounts,
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

    # Discount Management variables
    pending_admin_discounts = Discount.objects.filter(car__vendor=request.user, status='PENDING_VENDOR').select_related('car')
    active_vendor_discounts = Discount.objects.filter(car__vendor=request.user, status='APPROVED').select_related('car').order_by('-created_at')
    approved_cars = Car.objects.filter(vendor=request.user, status='APPROVED').order_by('brand', 'model')

    context = {
        'vendor_profile': vendor_profile,
        'cars': cars,
        'bookings': bookings,
        'pending_bookings_count': pending_bookings_count,
        'total_earnings': total_earnings,
        'pending_admin_discounts': pending_admin_discounts,
        'active_vendor_discounts': active_vendor_discounts,
        'approved_cars': approved_cars,
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

    # Promotions management variables
    all_discounts = Discount.objects.all().select_related('car', 'car__vendor').order_by('-created_at')
    all_approved_cars = Car.objects.filter(status='APPROVED').order_by('brand', 'model')

    context = {
        'pending_vendors': pending_vendors,
        'pending_cars': pending_cars,
        'active_complaints': active_complaints,
        'all_vendors': all_vendors,
        'pending_vendors_count': pending_vendors_count,
        'pending_cars_count': pending_cars_count,
        'total_revenue': total_revenue,
        'all_discounts': all_discounts,
        'all_approved_cars': all_approved_cars,
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
        hourly_rate = request.POST.get('hourly_rate')
        location = request.POST.get('location')
        address = request.POST.get('address')
        latitude = request.POST.get('latitude')
        longitude = request.POST.get('longitude')
        images = request.FILES.getlist('images')
        document = request.FILES.get('document')

        if not hourly_rate or float(hourly_rate) <= 0:
            hourly_rate = round(float(daily_rate) / 24, 2)

        try:
            lat = float(latitude) if latitude else None
        except ValueError:
            lat = None

        try:
            lon = float(longitude) if longitude else None
        except ValueError:
            lon = None

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
            hourly_rate=hourly_rate,
            location=location,
            address=address,
            latitude=lat,
            longitude=lon,
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
    radius = request.GET.get('radius')

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

    # Proximity Sorting and Filtering based on Customer Coordinates
    user_lat = request.GET.get('latitude') or request.session.get('user_latitude')
    user_lon = request.GET.get('longitude') or request.session.get('user_longitude')
    
    lat = None
    lon = None
    if user_lat and user_lon:
        try:
            lat = float(user_lat)
            lon = float(user_lon)
            # Store in session if not already there or changed
            request.session['user_latitude'] = lat
            request.session['user_longitude'] = lon
        except ValueError:
            pass

    car_list = list(cars)
    if lat is not None and lon is not None:
        import math
        for car in car_list:
            if car.latitude is not None and car.longitude is not None:
                # Haversine distance formula
                R = 6371.0
                dlat = math.radians(car.latitude - lat)
                dlon = math.radians(car.longitude - lon)
                a = math.sin(dlat / 2)**2 + math.cos(math.radians(lat)) * math.cos(math.radians(car.latitude)) * math.sin(dlon / 2)**2
                c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
                car.distance = round(R * c, 1)
            else:
                car.distance = None

        # Filter by radius if selected
        if radius:
            try:
                rad_val = float(radius)
                car_list = [c for c in car_list if c.distance is not None and c.distance <= rad_val]
            except ValueError:
                pass

        # Sort closest first, with None distance cars at the end
        car_list.sort(key=lambda x: (x.distance is None, x.distance))
    else:
        for car in car_list:
            car.distance = None

    return render(request, 'car_search.html', {'cars': car_list})

# Car Detail Page
def car_detail(request, car_id):
    car = get_object_or_404(Car, id=car_id)
    reviews = Review.objects.filter(car=car).order_by('-created_at')
    
    # Query approved or pending bookings to block dates
    bookings = Booking.objects.filter(car=car, status__in=['APPROVED', 'PENDING'])
    blocked_ranges = []
    for b in bookings:
        blocked_ranges.append({
            'start': b.start_date.isoformat(),
            'end': b.end_date.isoformat(),
        })
    import json
    blocked_ranges_json = json.dumps(blocked_ranges)

    # Query approved active discounts for this vehicle
    discounts = Discount.objects.filter(car=car, status='APPROVED').order_by('min_days')
    discounts_list = []
    for d in discounts:
        discounts_list.append({
            'min_days': d.min_days,
            'percentage': d.discount_percentage
        })
    discounts_json = json.dumps(discounts_list)

    return render(request, 'car_detail.html', {
        'car': car, 
        'reviews': reviews,
        'blocked_ranges_json': blocked_ranges_json,
        'discounts_json': discounts_json
    })

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
        start_time_str = request.POST.get('start_time')
        end_date_str = request.POST.get('end_date')
        end_time_str = request.POST.get('end_time')

        if start_date_str and start_time_str:
            start_datetime_str = f"{start_date_str}T{start_time_str}"
        else:
            start_datetime_str = start_date_str

        if end_date_str and end_time_str:
            end_datetime_str = f"{end_date_str}T{end_time_str}"
        else:
            end_datetime_str = end_date_str

        try:
            start_date = timezone.make_aware(datetime.strptime(start_datetime_str, "%Y-%m-%dT%H:%M"))
            end_date = timezone.make_aware(datetime.strptime(end_datetime_str, "%Y-%m-%dT%H:%M"))
        except ValueError:
            # Fallback for standard date strings (from automated unit tests)
            try:
                start_date = timezone.make_aware(datetime.strptime(start_datetime_str, "%Y-%m-%d"))
                end_date = timezone.make_aware(datetime.strptime(end_datetime_str, "%Y-%m-%d"))
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

        # Duration & price calculation based on time also (days + extra hours capped at daily rate)
        from decimal import Decimal
        duration = end_date - start_date
        total_hours = duration.total_seconds() / 3600
        
        import math
        days = int(total_hours // 24)
        remaining_hours = int(math.ceil(total_hours % 24))
        
        # Fallback for legacy database entries where hourly_rate is 0.00
        hourly_rate = car.hourly_rate if car.hourly_rate > 0 else Decimal(round(float(car.daily_rate) / 24, 2))
        
        # Calculate daily cost plus extra hours capped at a full day's rate
        extra_charge = min(Decimal(remaining_hours) * hourly_rate, car.daily_rate)
        total_price = (Decimal(days) * car.daily_rate) + extra_charge
        
        # Ensure total_price is at least 0
        if total_price <= 0:
            total_price = min(hourly_rate, car.daily_rate)

        # Apply database-driven dynamic discounts
        total_days = total_hours / 24
        discount_rate = Decimal('0.0')
        
        # Query active APPROVED discounts sorted descending by min_days
        active_promos = Discount.objects.filter(car=car, status='APPROVED').order_by('-min_days')
        for promo in active_promos:
            if total_days >= promo.min_days:
                discount_rate = Decimal(promo.discount_percentage) / Decimal('100.0')
                break
            
        discount_amount = total_price * discount_rate
        total_price = total_price - discount_amount
        total_price = round(total_price, 2)


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
        f"- Total Cost: ₹{booking.total_price:.2f}\n\n"
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
        payment_method = request.POST.get('payment_method', 'Credit Card')
        if payment_method == 'Pay on Visit':
            transaction_id = f"POV-{uuid.uuid4().hex[:8].upper()}"
        elif payment_method == 'UPI':
            transaction_id = f"UPI-{uuid.uuid4().hex[:8].upper()}"
        elif payment_method == 'Net Banking':
            transaction_id = f"NET-{uuid.uuid4().hex[:8].upper()}"
        else:
            transaction_id = f"TXN-{uuid.uuid4().hex[:8].upper()}"
        
        # Save License front/back images
        license_front_file = request.FILES.get('license_front')
        if license_front_file:
            booking.license_front = license_front_file
            
        license_back_file = request.FILES.get('license_back')
        if license_back_file:
            booking.license_back = license_back_file
            
        # Save Damage Report JSON string
        damage_report = request.POST.get('damage_report')
        if damage_report:
            booking.damage_report = damage_report
 
        # Save base64 Digital Signature image
        signature_base64 = request.POST.get('signature_base64')
        if signature_base64 and signature_base64.startswith('data:image/png;base64,'):
            import base64
            from django.core.files.base64 import ContentFile
            try:
                format, imgstr = signature_base64.split(';base64,')
                ext = format.split('/')[-1]
                sig_name = f"sig_{booking.id}_{uuid.uuid4().hex[:6]}.{ext}"
                booking.signature.save(sig_name, ContentFile(base64.b64decode(imgstr)), save=False)
            except Exception:
                pass
        
        # Save payment details
        Payment.objects.create(
            booking=booking,
            transaction_id=transaction_id,
            amount=booking.total_price,
            payment_method=payment_method
        )
 
        # Update booking
        booking.payment_status = 'PAID'
        booking.save()
 
        # Send confirmation email to customer
        if payment_method == 'Pay on Visit':
            subject = f"Booking Confirmation (Pay on Visit): Booking #{booking.id} - Web Wizards Car Rentals"
            message = (
                f"Hello {booking.customer.username},\n\n"
                f"Your booking has been confirmed! You have opted to pay on visit (upon vehicle pickup).\n\n"
                f"Booking details:\n"
                f"- Booking ID: #{booking.id}\n"
                f"- Payment Method: Pay on Visit\n"
                f"- Reference ID: {transaction_id}\n"
                f"- Amount Due: ₹{booking.total_price:.2f}\n"
                f"- Car: {booking.car.brand} {booking.car.model} ({booking.car.year})\n"
                f"- Pick-up Time: {booking.start_date.strftime('%Y-%m-%d %H:%M')}\n"
                f"- Return Time: {booking.end_date.strftime('%Y-%m-%d %H:%M')}\n\n"
                f"Please make the payment of ₹{booking.total_price:.2f} at the time of your pickup/visit.\n"
                f"Your rental is now fully active. Enjoy your ride!\n\n"
                f"Best regards,\n"
                f"Web Wizards Car Rentals Team"
            )
        else:
            subject = f"Payment Confirmation: Booking #{booking.id} - Web Wizards Car Rentals"
            message = (
                f"Hello {booking.customer.username},\n\n"
                f"Thank you for your payment! Your transaction has been processed successfully.\n\n"
                f"Payment details:\n"
                f"- Booking ID: #{booking.id}\n"
                f"- Payment Method: {payment_method}\n"
                f"- Transaction ID: {transaction_id}\n"
                f"- Amount Paid: ₹{booking.total_price:.2f}\n"
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

        if payment_method == 'Pay on Visit':
            messages.success(request, f"Booking completed! You will pay ₹{booking.total_price:.2f} on visit. Reference ID: {transaction_id}")
        else:
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

    messages.success(request, f"Vehicle successfully marked as returned!")
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
        hourly_rate = request.POST.get('hourly_rate')
        if not hourly_rate or float(hourly_rate) <= 0:
            hourly_rate = round(float(car.daily_rate) / 24, 2)
        car.hourly_rate = hourly_rate
        car.location = request.POST.get('location')
        car.address = request.POST.get('address')
        
        latitude = request.POST.get('latitude')
        longitude = request.POST.get('longitude')
        try:
            car.latitude = float(latitude) if latitude else None
        except ValueError:
            car.latitude = None
            
        try:
            car.longitude = float(longitude) if longitude else None
        except ValueError:
            car.longitude = None

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

# Verify Registration OTP (Step 2 of Register)
def verify_otp_view(request):
    if request.user.is_authenticated:
        return redirect('dashboard')

    pending_data = request.session.get('pending_registration')
    if not pending_data:
        messages.error(request, "No pending registration found. Please register first.")
        return redirect('register')

    if request.method == 'POST':
        otp_entered = request.POST.get('otp')
        saved_otp = request.session.get('registration_otp')

        if otp_entered == saved_otp:
            # OTP matches! Create User and Profile
            username = pending_data['username']
            email = pending_data['email']
            password = pending_data['password']
            first_name = pending_data['first_name']
            phone_number = pending_data['phone_number']
            role = pending_data['role']

            user = User.objects.create_user(
                username=username,
                email=email,
                password=password,
                first_name=first_name,
                phone_number=phone_number,
                role=role
            )

            # Create specific profiles
            if role == 'VENDOR':
                VendorProfile.objects.create(
                    user=user,
                    company_name=pending_data['company_name'],
                    license_number=pending_data['license_number'],
                    is_approved=False
                )
                messages.success(request, "Registration verified! Vendor account created, awaiting admin approval.")
            else:
                CustomerProfile.objects.create(
                    user=user,
                    driver_license=pending_data['driver_license'],
                    address=pending_data['address']
                )
                messages.success(request, "Registration verified! Customer account successfully activated.")

            # Clear session
            del request.session['pending_registration']
            del request.session['registration_otp']

            # Log the user in
            login(request, user)
            return redirect('dashboard')
        else:
            messages.error(request, "Invalid verification code. Please try again.")

    return render(request, 'verify_otp.html', {'pending_email': pending_data.get('email')})

# Resend OTP View
def resend_otp_view(request):
    if request.user.is_authenticated:
        return redirect('dashboard')

    pending_data = request.session.get('pending_registration')
    if not pending_data:
        messages.error(request, "No pending registration found. Please register first.")
        return redirect('register')

    username = pending_data.get('username')
    email = pending_data.get('email')
    first_name = pending_data.get('first_name')

    # Generate a new 6-digit OTP
    new_otp = str(random.randint(100000, 999999))
    request.session['registration_otp'] = new_otp

    # Send new OTP email
    subject = "Verify Your Registration - Web Wizards Car Rentals"
    message = (
        f"Hello {first_name or username},\n\n"
        f"Here is your new 6-digit One-Time Password (OTP) to complete registration:\n\n"
        f"   >>>  {new_otp}  <<<\n\n"
        f"This code is valid for 10 minutes.\n\n"
        f"Best regards,\n"
        f"Web Wizards Car Rentals Team"
    )
    recipient_list = [email]
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

    # Print to console for easy local testing
    print(f"==================================================")
    print(f"  NEW OTP GENERATED FOR {username}: {new_otp}")
    print(f"==================================================")

    messages.success(request, "A new verification code has been sent to your email.")
    return redirect('verify_otp')

# Forgot Password - Enter Email (Step 1)
def forgot_password_view(request):
    if request.user.is_authenticated:
        return redirect('dashboard')

    if request.method == 'POST':
        email = request.POST.get('email')
        user = User.objects.filter(email=email).first()

        if user:
            # Generate a 6-digit OTP code for password reset
            otp = str(random.randint(100000, 999999))
            request.session['reset_email'] = email
            request.session['reset_otp'] = otp

            # Send OTP email
            subject = "Reset Your Password - Web Wizards Car Rentals"
            message = (
                f"Hello {user.first_name or user.username},\n\n"
                f"We received a request to reset the password for your Web Wizards Car Rentals account.\n\n"
                f"Please use this 6-digit One-Time Password (OTP) to reset your password:\n\n"
                f"   >>>  {otp}  <<<\n\n"
                f"This code is valid for 10 minutes. If you did not request this, you can safely ignore this email.\n\n"
                f"Best regards,\n"
                f"Web Wizards Car Rentals Team"
            )
            recipient_list = [email]
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

            # Print to console for convenient development/testing
            print(f"==================================================")
            print(f"  PASSWORD RESET OTP FOR {email}: {otp}")
            print(f"==================================================")

            messages.success(request, "A 6-digit verification code has been sent to your email address.")
            return redirect('forgot_password_verify')
        else:
            messages.error(request, "No account was found with that email address.")

    return render(request, 'forgot_password.html')

# Forgot Password - Verify Code & Change Password (Step 2)
def forgot_password_verify_view(request):
    if request.user.is_authenticated:
        return redirect('dashboard')

    reset_email = request.session.get('reset_email')
    if not reset_email:
        messages.error(request, "Please enter your email to request a password reset first.")
        return redirect('forgot_password')

    if request.method == 'POST':
        otp_entered = request.POST.get('otp')
        saved_otp = request.session.get('reset_otp')
        new_password = request.POST.get('new_password')
        password_confirm = request.POST.get('password_confirm')

        if otp_entered == saved_otp:
            if new_password == password_confirm:
                # Find user and reset password
                user = User.objects.get(email=reset_email)
                user.set_password(new_password)
                user.save()

                # Clear session
                del request.session['reset_email']
                del request.session['reset_otp']

                messages.success(request, "Your password has been successfully reset! Please login using your new password.")
                return redirect('login')
            else:
                messages.error(request, "Passwords do not match!")
        else:
            messages.error(request, "Invalid verification code. Please check the code and try again.")

    return render(request, 'forgot_password_verify.html', {'reset_email': reset_email})

# Invoice Statement View
@login_required
def download_invoice(request, booking_id):
    booking = get_object_or_404(Booking, id=booking_id)
    
    # Renter or supplier only
    if booking.customer != request.user and booking.car.vendor != request.user:
        messages.error(request, "Unauthorized access.")
        return redirect('dashboard')
        
    return render(request, 'invoice.html', {'booking': booking})

# Vendor Add Discount View
@login_required
def vendor_add_discount(request):
    if request.user.role != 'VENDOR':
        messages.error(request, "Only vendors can manage discounts for their vehicles.")
        return redirect('dashboard')
        
    if request.method == 'POST':
        car_id = request.POST.get('car')
        discount_percentage = request.POST.get('discount_percentage')
        min_days = request.POST.get('min_days')
        
        car = get_object_or_404(Car, id=car_id, vendor=request.user)
        
        # Vendor-created discounts are approved automatically
        Discount.objects.create(
            car=car,
            discount_percentage=discount_percentage,
            min_days=min_days,
            status='APPROVED',
            created_by='VENDOR'
        )
        messages.success(request, f"New discount of {discount_percentage}% created for {car.brand} {car.model}!")
        
    return redirect('dashboard')

# Admin Add Discount View
@login_required
def admin_add_discount(request):
    if not request.user.is_superuser and request.user.role != 'ADMIN':
        messages.error(request, "Only administrators can request vehicle promotions.")
        return redirect('dashboard')
        
    if request.method == 'POST':
        car_id = request.POST.get('car')
        discount_percentage = request.POST.get('discount_percentage')
        min_days = request.POST.get('min_days')
        
        car = get_object_or_404(Car, id=car_id)
        
        # Admin-created discounts are pending vendor acceptance
        Discount.objects.create(
            car=car,
            discount_percentage=discount_percentage,
            min_days=min_days,
            status='PENDING_VENDOR',
            created_by='ADMIN'
        )
        messages.success(request, f"Promotion request of {discount_percentage}% submitted for {car.brand} {car.model}! Waiting for Supplier acceptance.")
        
    return redirect('dashboard')

# Vendor Respond Discount (Accept/Reject) View
@login_required
def vendor_respond_discount(request, discount_id, action):
    if request.user.role != 'VENDOR':
        messages.error(request, "Unauthorized access.")
        return redirect('dashboard')
        
    discount = get_object_or_404(Discount, id=discount_id, car__vendor=request.user)
    
    if action == 'ACCEPT':
        discount.status = 'APPROVED'
        discount.save()
        messages.success(request, f"Promotion offer of {discount.discount_percentage}% accepted for {discount.car.brand} {discount.car.model}!")
    elif action == 'REJECT':
        discount.status = 'REJECTED'
        discount.save()
        messages.success(request, f"Promotion offer rejected.")
        
    return redirect('dashboard')

# Delete Discount View (Both Admin & Vendor can delete)
@login_required
def delete_discount(request, discount_id):
    discount = get_object_or_404(Discount, id=discount_id)
    
    # Check authorization (Must be either the vehicle owner or an administrator)
    is_authorized = (
        discount.car.vendor == request.user or 
        request.user.role == 'ADMIN' or 
        request.user.is_superuser
    )
    
    if not is_authorized:
        messages.error(request, "Unauthorized access.")
        return redirect('dashboard')
        
    discount.delete()
    messages.success(request, "Discount promotion successfully removed.")
    return redirect('dashboard')


def detect_location(request):
    latitude = request.GET.get('latitude') or request.POST.get('latitude')
    longitude = request.GET.get('longitude') or request.POST.get('longitude')
    
    if not latitude or not longitude:
        return JsonResponse({'status': 'error', 'message': 'Coordinates missing.'}, status=400)
    
    try:
        lat = float(latitude)
        lon = float(longitude)
        request.session['user_latitude'] = lat
        request.session['user_longitude'] = lon
    except ValueError:
        return JsonResponse({'status': 'error', 'message': 'Invalid coordinates.'}, status=400)
    
    address_display = "Detected Location"
    url = f"https://nominatim.openstreetmap.org/reverse?format=json&lat={lat}&lon={lon}&zoom=12"
    try:
        req = urllib.request.Request(
            url, 
            headers={'User-Agent': 'WebWizardsCarRentals/1.0 (contact: admin@webwizardrentals.com)'}
        )
        with urllib.request.urlopen(req, timeout=3) as response:
            data = json.loads(response.read().decode())
            address_details = data.get('address', {})
            city = address_details.get('city') or address_details.get('town') or address_details.get('village') or address_details.get('county')
            state = address_details.get('state')
            if city and state:
                address_display = f"{city}, {state}"
            elif city:
                address_display = city
            elif state:
                address_display = state
            else:
                address_display = data.get('display_name', 'Detected Location')
    except Exception as e:
        print(f"Geocoding error: {e}")
        pass
        
    request.session['user_address'] = address_display
    
    return JsonResponse({
        'status': 'success', 
        'latitude': lat, 
        'longitude': lon, 
        'address': address_display
    })


def api_geocode(request):
    import urllib.parse
    query = request.GET.get('q')
    if not query:
        return JsonResponse({'status': 'error', 'message': 'Query missing.'}, status=400)
    
    url = f"https://nominatim.openstreetmap.org/search?format=json&q={urllib.parse.quote(query)}&limit=1"
    try:
        req = urllib.request.Request(
            url,
            headers={'User-Agent': 'WebWizardsCarRentals/1.0 (contact: admin@webwizardrentals.com)'}
        )
        with urllib.request.urlopen(req, timeout=3) as response:
            data = json.loads(response.read().decode())
            if data:
                result = data[0]
                return JsonResponse({
                    'status': 'success',
                    'latitude': float(result.get('lat')),
                    'longitude': float(result.get('lon')),
                    'display_name': result.get('display_name')
                })
            else:
                return JsonResponse({'status': 'error', 'message': 'Location not found.'}, status=404)
    except Exception as e:
        return JsonResponse({'status': 'error', 'message': str(e)}, status=500)


def api_reverse_geocode(request):
    latitude = request.GET.get('latitude')
    longitude = request.GET.get('longitude')
    if not latitude or not longitude:
        return JsonResponse({'status': 'error', 'message': 'Coordinates missing.'}, status=400)
    
    try:
        lat = float(latitude)
        lon = float(longitude)
    except ValueError:
        return JsonResponse({'status': 'error', 'message': 'Invalid coordinates.'}, status=400)
        
    url = f"https://nominatim.openstreetmap.org/reverse?format=json&lat={lat}&lon={lon}&zoom=18"
    try:
        req = urllib.request.Request(
            url,
            headers={'User-Agent': 'WebWizardsCarRentals/1.0 (contact: admin@webwizardrentals.com)'}
        )
        with urllib.request.urlopen(req, timeout=3) as response:
            data = json.loads(response.read().decode())
            if data:
                return JsonResponse({
                    'status': 'success',
                    'latitude': lat,
                    'longitude': lon,
                    'display_name': data.get('display_name'),
                    'address': data.get('address', {})
                })
            else:
                return JsonResponse({'status': 'error', 'message': 'Reverse geocoding failed.'}, status=404)
    except Exception as e:
        return JsonResponse({'status': 'error', 'message': str(e)}, status=500)


