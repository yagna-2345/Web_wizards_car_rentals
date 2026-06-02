import os
import django

# Configure Django settings module
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'web_wizards_rentals.settings')
django.setup()

from car_rental.models import User

# Check and create default administrator superuser if not exists
if not User.objects.filter(username='admin').exists():
    User.objects.create_superuser('admin', 'admin@wizards.com', 'admin123', role='ADMIN')
    print("==================================================")
    print("  DEFAULT ADMIN CREATED: admin / admin123")
    print("==================================================")
else:
    print("Default admin user already exists.")
