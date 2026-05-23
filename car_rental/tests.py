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
        
        user = User.objects.get(username='new_user')
        self.assertEqual(user.first_name, 'Harry Potter')
        self.assertEqual(user.customer_profile.driver_license, 'DL-HARRY999')

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
