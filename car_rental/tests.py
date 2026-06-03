from django.test import TestCase
from django.utils import timezone
from datetime import date, timedelta
from decimal import Decimal
from django.core.files.uploadedfile import SimpleUploadedFile

from .models import User, VendorProfile, CustomerProfile, Car, Booking, Payment, Review, Complaint

class CarRentalSystemTests(TestCase):
    
    def setUp(self):
        # Create users
        self.customer_user = User.objects.create_user(
            username='test_customer',
            email='cust@test.com',
            password='password123',
            role='CUSTOMER'
        )
        self.customer_profile = CustomerProfile.objects.create(
            user=self.customer_user,
            driver_license='DL-CUST123',
            address='123 Main St'
        )

        self.vendor_user = User.objects.create_user(
            username='test_vendor',
            email='vendor@test.com',
            password='password123',
            role='VENDOR'
        )
        self.vendor_profile = VendorProfile.objects.create(
            user=self.vendor_user,
            company_name='Test Rental Fleet',
            license_number='LIC-VND987',
            is_approved=True
        )

        # Create dummy image file for testing ImageField
        self.test_image = SimpleUploadedFile(
            name='test_car.jpg',
            content=b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00\x01\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82',
            content_type='image/jpeg'
        )

        # Create Car
        self.car = Car.objects.create(
            vendor=self.vendor_user,
            brand='Tesla',
            model='Model 3',
            year=2023,
            category='ELECTRIC',
            daily_rate=Decimal('100.00'),
            location='Brooklyn, NY',
            image=self.test_image,
            status='APPROVED',
            is_available=True
        )

    def test_user_roles(self):
        self.assertTrue(self.customer_user.is_customer())
        self.assertFalse(self.customer_user.is_vendor())
        self.assertTrue(self.vendor_user.is_vendor())
        self.assertFalse(self.vendor_user.is_customer())

    def test_car_creation_and_defaults(self):
        # Creating a new car should default to PENDING status
        pending_car = Car.objects.create(
            vendor=self.vendor_user,
            brand='Toyota',
            model='Camry',
            year=2022,
            category='SEDAN',
            daily_rate=Decimal('50.00'),
            location='Manhattan, NY',
            image=self.test_image
        )
        self.assertEqual(pending_car.status, 'PENDING')
        self.assertTrue(pending_car.is_available)

    def test_booking_and_pricing(self):
        start_date = date.today()
        end_date = start_date + timedelta(days=2) # 3 days rental (today, tomorrow, day-after)
        days = (end_date - start_date).days + 1
        total_price = days * self.car.daily_rate

        booking = Booking.objects.create(
            customer=self.customer_user,
            car=self.car,
            start_date=start_date,
            end_date=end_date,
            total_price=total_price,
            status='PENDING',
            payment_status='PENDING'
        )

        self.assertEqual(booking.total_price, Decimal('300.00'))
        self.assertEqual(booking.status, 'PENDING')
        self.assertEqual(booking.payment_status, 'PENDING')

    def test_double_booking_prevention(self):
        start_date = date.today()
        end_date = start_date + timedelta(days=2)
        total_price = 3 * self.car.daily_rate

        # First booking (approved)
        Booking.objects.create(
            customer=self.customer_user,
            car=self.car,
            start_date=start_date,
            end_date=end_date,
            total_price=total_price,
            status='APPROVED',
            payment_status='PAID'
        )

        # Attempt to book overlapping dates
        # Using self.client to request booking
        self.client.login(username='test_customer', password='password123')
        response = self.client.post(
            f'/car/{self.car.id}/book/',
            {
                'start_date': start_date.strftime('%Y-%m-%d'),
                'end_date': end_date.strftime('%Y-%m-%d')
            }
        )

        # Should redirect back to car detail with message
        self.assertEqual(response.status_code, 302)
        
        # Verify that NO new booking was created
        # There should only be 1 booking total (the pre-existing approved one)
        self.assertEqual(Booking.objects.filter(car=self.car).count(), 1)

    def test_multiple_car_photos(self):
        from .models import CarImage
        # Create multiple photos for a car
        CarImage.objects.create(car=self.car, image=self.test_image)
        CarImage.objects.create(car=self.car, image=self.test_image)
        
        self.assertEqual(self.car.images.count(), 2)

    def test_booking_cancellation_within_24_hours(self):
        # Create booking and mark car as unavailable
        self.car.is_available = False
        self.car.save()
        
        booking = Booking.objects.create(
            customer=self.customer_user,
            car=self.car,
            start_date=timezone.now(),
            end_date=timezone.now() + timedelta(days=2),
            total_price=Decimal('200.00'),
            status='APPROVED',
            payment_status='PAID'
        )

        self.client.login(username='test_customer', password='password123')
        response = self.client.post(f'/booking/{booking.id}/cancel/')
        
        self.assertEqual(response.status_code, 302)
        
        # Refresh and verify
        booking.refresh_from_db()
        self.assertEqual(booking.status, 'CANCELLED')
        self.assertEqual(booking.payment_status, 'REFUNDED')
        
        self.car.refresh_from_db()
        self.assertTrue(self.car.is_available)

    def test_booking_cancellation_after_24_hours(self):
        # Create booking and mark car as unavailable
        self.car.is_available = False
        self.car.save()
        
        # 25 hours ago creation
        past_time = timezone.now() - timedelta(hours=25)
        booking = Booking.objects.create(
            customer=self.customer_user,
            car=self.car,
            start_date=timezone.now(),
            end_date=timezone.now() + timedelta(days=2),
            total_price=Decimal('200.00'),
            status='APPROVED',
            payment_status='PAID',
            created_at=past_time
        )

        self.client.login(username='test_customer', password='password123')
        response = self.client.post(f'/booking/{booking.id}/cancel/')
        
        self.assertEqual(response.status_code, 302)
        
        # Refresh and verify it should NOT be cancelled
        booking.refresh_from_db()
        self.assertEqual(booking.status, 'APPROVED')
        self.assertEqual(booking.payment_status, 'PAID')
        
        self.car.refresh_from_db()
        self.assertFalse(self.car.is_available)

    def test_booking_approval_email_notification(self):
        from django.core import mail
        # Create a pending booking
        booking = Booking.objects.create(
            customer=self.customer_user,
            car=self.car,
            start_date=timezone.now(),
            end_date=timezone.now() + timedelta(days=2),
            total_price=Decimal('200.00'),
            status='PENDING',
            payment_status='PENDING'
        )

        # Vendor logs in and approves booking
        self.client.login(username='test_vendor', password='password123')
        response = self.client.post(f'/booking/{booking.id}/approve/')
        
        self.assertEqual(response.status_code, 302)
        
        # Verify that an email was sent
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("Booking Confirmed", mail.outbox[0].subject)
        self.assertIn(self.customer_user.email, mail.outbox[0].to)

    def test_payment_success_email_notification(self):
        from django.core import mail
        # Create an approved pending-payment booking
        booking = Booking.objects.create(
            customer=self.customer_user,
            car=self.car,
            start_date=timezone.now(),
            end_date=timezone.now() + timedelta(days=2),
            total_price=Decimal('200.00'),
            status='APPROVED',
            payment_status='PENDING'
        )

        # Clear outbox
        mail.outbox = []

        # Customer logs in and completes payment
        self.client.login(username='test_customer', password='password123')
        response = self.client.post(f'/booking/{booking.id}/pay/')
        
        self.assertEqual(response.status_code, 302)
        
        # Verify that an email was sent
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("Payment Confirmation", mail.outbox[0].subject)
        self.assertIn(self.customer_user.email, mail.outbox[0].to)

    def test_pay_on_visit_workflow(self):
        from django.core import mail
        # Create an approved pending-payment booking
        booking = Booking.objects.create(
            customer=self.customer_user,
            car=self.car,
            start_date=timezone.now(),
            end_date=timezone.now() + timedelta(days=2),
            total_price=Decimal('200.00'),
            status='APPROVED',
            payment_status='PENDING'
        )

        # Clear outbox
        mail.outbox = []

        # Customer logs in and completes booking via Pay on Visit
        self.client.login(username='test_customer', password='password123')
        response = self.client.post(f'/booking/{booking.id}/pay/', {
            'payment_method': 'Pay on Visit'
        })
        
        self.assertEqual(response.status_code, 302)
        
        # Verify Payment object creation
        payment = Payment.objects.get(booking=booking)
        self.assertEqual(payment.payment_method, 'Pay on Visit')
        self.assertTrue(payment.transaction_id.startswith('POV-'))
        
        # Verify Booking status updated to PAID
        booking.refresh_from_db()
        self.assertEqual(booking.payment_status, 'PAID')
        
        # Verify confirmation email was sent with correct subject
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("Booking Confirmation (Pay on Visit)", mail.outbox[0].subject)
        self.assertIn(self.customer_user.email, mail.outbox[0].to)

    def test_user_registration_with_name(self):
        # Post registration with first_name
        response = self.client.post('/register/', {
            'username': 'new_user',
            'email': 'new@test.com',
            'password': 'password123',
            'password_confirm': 'password123',
            'phone_number': '1234567',
            'role': 'CUSTOMER',
            'first_name': 'Harry Potter',
            'driver_license': 'DL-HARRY999',
            'address': 'Gryffindor Dorm'
        })
        self.assertEqual(response.status_code, 302)
        self.assertIn('/register/verify/', response.url)
        
        # Verify OTP is stored in session and send verification code
        session = self.client.session
        self.assertIn('pending_registration', session)
        self.assertIn('registration_otp', session)
        otp = session['registration_otp']
        
        # Post the correct OTP to verify view
        verify_response = self.client.post('/register/verify/', {
            'otp': otp
        })
        self.assertEqual(verify_response.status_code, 302)
        
        user = User.objects.get(username='new_user')
        self.assertEqual(user.first_name, 'Harry Potter')
        self.assertEqual(user.customer_profile.driver_license, 'DL-HARRY999')

    def test_user_registration_with_invalid_otp(self):
        response = self.client.post('/register/', {
            'username': 'new_user_2',
            'email': 'new2@test.com',
            'password': 'password123',
            'password_confirm': 'password123',
            'phone_number': '1234567',
            'role': 'CUSTOMER',
            'first_name': 'Ron Weasley',
            'driver_license': 'DL-RON888',
            'address': 'Burrow Dorm'
        })
        self.assertEqual(response.status_code, 302)
        
        # Post invalid OTP
        verify_response = self.client.post('/register/verify/', {
            'otp': '000000'
        })
        self.assertEqual(verify_response.status_code, 200)
        
        # Verify user not created
        self.assertFalse(User.objects.filter(username='new_user_2').exists())

    def test_edit_profile_view(self):
        self.client.login(username='test_customer', password='password123')
        response = self.client.post('/profile/edit/', {
            'first_name': 'Updated Customer Name',
            'email': 'cust_new@test.com',
            'phone_number': '999999',
            'driver_license': 'DL-NEW-CUST',
            'address': 'New Dorm'
        })
        self.assertEqual(response.status_code, 302)
        
        self.customer_user.refresh_from_db()
        self.customer_profile.refresh_from_db()
        
        self.assertEqual(self.customer_user.first_name, 'Updated Customer Name')
        self.assertEqual(self.customer_user.email, 'cust_new@test.com')
        self.assertEqual(self.customer_profile.driver_license, 'DL-NEW-CUST')
        self.assertEqual(self.customer_profile.address, 'New Dorm')

    def test_forgot_password_workflow_success(self):
        # Trigger forgot password with customer's email
        response = self.client.post('/password-reset/', {
            'email': 'cust@test.com'
        })
        self.assertEqual(response.status_code, 302)
        self.assertIn('/password-reset/verify/', response.url)

        # Retrieve OTP from session
        session = self.client.session
        self.assertIn('reset_email', session)
        self.assertIn('reset_otp', session)
        otp = session['reset_otp']

        # Complete reset with correct OTP
        verify_response = self.client.post('/password-reset/verify/', {
            'otp': otp,
            'new_password': 'newpassword123',
            'password_confirm': 'newpassword123'
        })
        self.assertEqual(verify_response.status_code, 302)

        # Confirm password has updated by logging in with the new password
        login_success = self.client.login(username='test_customer', password='newpassword123')
        self.assertTrue(login_success)

    def test_forgot_password_workflow_invalid_otp(self):
        # Trigger forgot password
        response = self.client.post('/password-reset/', {
            'email': 'cust@test.com'
        })
        self.assertEqual(response.status_code, 302)

        # Complete reset with INCORRECT OTP
        verify_response = self.client.post('/password-reset/verify/', {
            'otp': '000000',
            'new_password': 'newpassword123',
            'password_confirm': 'newpassword123'
        })
        self.assertEqual(verify_response.status_code, 200) # stays on same page due to error

        # Confirm password has not updated; login with old password should still work
        login_old = self.client.login(username='test_customer', password='password123')
        self.assertTrue(login_old)

    def test_time_based_pricing_calculation(self):
        # Configure rates
        self.car.daily_rate = Decimal('100.00')
        self.car.hourly_rate = Decimal('10.00')
        self.car.save()

        self.client.login(username='test_customer', password='password123')

        # Test Case 1: Rent for 5 hours (5 * ₹10.00 = ₹50.00)
        response = self.client.post(
            f'/car/{self.car.id}/book/',
            {
                'start_date': '2026-06-01T10:00',
                'end_date': '2026-06-01T15:00'
            }
        )
        self.assertEqual(response.status_code, 302)
        booking1 = Booking.objects.filter(customer=self.customer_user, car=self.car).latest('id')
        self.assertEqual(booking1.total_price, Decimal('50.00'))

        # Test Case 2: Rent for 12 hours (₹120.00 raw, capped at ₹100.00 daily rate)
        response = self.client.post(
            f'/car/{self.car.id}/book/',
            {
                'start_date': '2026-06-02T10:00',
                'end_date': '2026-06-02T22:00'
            }
        )
        self.assertEqual(response.status_code, 302)
        booking2 = Booking.objects.filter(customer=self.customer_user, car=self.car).latest('id')
        self.assertEqual(booking2.total_price, Decimal('100.00'))

        # Test Case 3: Rent for 1 day and 3 hours (27 hours total -> 1 day + 3 hours * ₹10 = ₹130.00)
        response = self.client.post(
            f'/car/{self.car.id}/book/',
            {
                'start_date': '2026-06-03T10:00',
                'end_date': '2026-06-04T13:00'
            }
        )
        self.assertEqual(response.status_code, 302)
        booking3 = Booking.objects.filter(customer=self.customer_user, car=self.car).latest('id')
        self.assertEqual(booking3.total_price, Decimal('130.00'))


class CarRentalDiscountTests(TestCase):
    def setUp(self):
        self.customer_user = User.objects.create_user(
            username='test_customer_discount',
            email='cust_discount@test.com',
            password='password123',
            role='CUSTOMER'
        )
        self.vendor_user = User.objects.create_user(
            username='test_vendor_discount',
            email='vendor_discount@test.com',
            password='password123',
            role='VENDOR'
        )
        self.vendor_profile = VendorProfile.objects.create(
            user=self.vendor_user,
            company_name='Discount Fleet LLC',
            license_number='LIC-DISC111',
            is_approved=True
        )
        self.car = Car.objects.create(
            vendor=self.vendor_user,
            brand='Nissan',
            model='Leaf',
            year=2022,
            category='ELECTRIC',
            daily_rate=Decimal('100.00'),
            hourly_rate=Decimal('5.00'),
            location='Brooklyn, NY',
            status='APPROVED',
            is_available=True
        )

    def test_discount_model_properties(self):
        from .models import Discount
        discount = Discount.objects.create(
            car=self.car,
            discount_percentage=15,
            min_days=3,
            status='APPROVED',
            created_by='VENDOR'
        )
        self.assertEqual(discount.get_discounted_rate, Decimal('85.00'))

    def test_booking_discount_application(self):
        from .models import Discount
        Discount.objects.create(
            car=self.car,
            discount_percentage=20,
            min_days=3,
            status='APPROVED',
            created_by='VENDOR'
        )

        self.client.login(username='test_customer_discount', password='password123')

        # Booking for 2 days (total_hours = 48 hours). No discount because min_days is 3.
        # Price should be 2 * 100 = 200.00
        response = self.client.post(
            f'/car/{self.car.id}/book/',
            {
                'start_date': '2026-07-01T10:00',
                'end_date': '2026-07-03T10:00'
            }
        )
        self.assertEqual(response.status_code, 302)
        booking1 = Booking.objects.filter(customer=self.customer_user, car=self.car).latest('id')
        self.assertEqual(booking1.total_price, Decimal('200.00'))

        # Booking for 3 days (total_hours = 72 hours). Should get 20% discount.
        # Raw price is 3 * 100 = 300.00. Discounted is 300 * 0.8 = 240.00.
        response = self.client.post(
            f'/car/{self.car.id}/book/',
            {
                'start_date': '2026-07-04T10:00',
                'end_date': '2026-07-07T10:00'
            }
        )
        self.assertEqual(response.status_code, 302)
        booking2 = Booking.objects.filter(customer=self.customer_user, car=self.car).latest('id')
        self.assertEqual(booking2.total_price, Decimal('240.00'))

    def test_promo_negotiation_workflow(self):
        from .models import Discount
        # 1. Admin creates pending promo
        # Log in as vendor, verify cannot access admin view (will redirect)
        self.client.login(username='test_vendor_discount', password='password123')
        response = self.client.post(
            '/discount/admin/add/',
            {'car': self.car.id, 'discount_percentage': 25, 'min_days': 5}
        )
        self.assertEqual(response.status_code, 302)
        
        # Superuser/admin login
        admin_user = User.objects.create_superuser(
            username='admin_user',
            email='admin@test.com',
            password='adminpassword',
            role='ADMIN'
        )
        self.client.login(username='admin_user', password='adminpassword')
        response = self.client.post(
            '/discount/admin/add/',
            {'car': self.car.id, 'discount_percentage': 25, 'min_days': 5}
        )
        self.assertEqual(response.status_code, 302)
        
        # Verify it is created and PENDING_VENDOR
        promo = Discount.objects.filter(car=self.car, discount_percentage=25).first()
        self.assertIsNotNone(promo)
        self.assertEqual(promo.status, 'PENDING_VENDOR')
        self.assertEqual(promo.created_by, 'ADMIN')

        # 2. Vendor responds to pending promo
        self.client.login(username='test_vendor_discount', password='password123')
        # Accept promo
        response = self.client.post(f'/discount/{promo.id}/respond/ACCEPT/')
        self.assertEqual(response.status_code, 302)
        promo.refresh_from_db()
        self.assertEqual(promo.status, 'APPROVED')

        # Delete promo
        response = self.client.post(f'/discount/{promo.id}/delete/')
        self.assertEqual(response.status_code, 302)
        self.assertFalse(Discount.objects.filter(id=promo.id).exists())
