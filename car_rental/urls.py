from django.urls import path
from . import views

urlpatterns = [
    path('', views.home, name='home'),
    
    # Authentication
    path('register/', views.register_view, name='register'),
    path('login/', views.login_view, name='login'),
    path('logout/', views.logout_view, name='logout'),
    
    # Dashboards
    path('dashboard/', views.dashboard, name='dashboard'),
    path('dashboard/complaint/', views.raise_complaint, name='raise_complaint'),
    
    # Vendor Actions
    path('car/add/', views.add_car, name='add_car'),
    path('car/<int:car_id>/edit/', views.edit_car, name='edit_car'),
    path('car/<int:car_id>/delete/', views.delete_car, name='delete_car'),
    path('car/<int:car_id>/toggle/', views.toggle_car_availability, name='toggle_car_availability'),
    path('booking/<int:booking_id>/approve/', views.approve_booking, name='approve_booking'),
    path('booking/<int:booking_id>/reject/', views.reject_booking, name='reject_booking'),
    
    # Customer Booking & Checkout Actions
    path('cars/', views.car_search, name='car_search'),
    path('car/<int:car_id>/', views.car_detail, name='car_detail'),
    path('car/<int:car_id>/book/', views.book_car, name='book_car'),
    path('booking/<int:booking_id>/checkout/', views.payment_checkout, name='payment_checkout'),
    path('booking/<int:booking_id>/pay/', views.payment_submit, name='payment_submit'),
    path('booking/<int:booking_id>/cancel/', views.cancel_booking, name='cancel_booking'),
    path('booking/<int:booking_id>/return/', views.return_car, name='return_car'),
    path('car/<int:car_id>/review/', views.car_review, name='car_review'),
    path('profile/edit/', views.edit_profile, name='edit_profile'),
    
    # Admin Controls
    path('admin/vendor/<int:profile_id>/<str:action>/', views.verify_vendor, name='verify_vendor'),
    path('admin/car/<int:car_id>/<str:action>/', views.verify_car, name='verify_car'),
    path('admin/complaint/<int:complaint_id>/resolve/', views.resolve_complaint, name='resolve_complaint'),
]
