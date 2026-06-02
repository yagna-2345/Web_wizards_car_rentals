import os
import django

# Configure Django settings module
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'web_wizards_rentals.settings')
django.setup()

from car_rental.models import User

# Check and create default administrator superuser if not exists
if not User.objects.filter(username='yagna_2345').exists():
    User.objects.create_superuser('yagna_2345', 'admin@wizards.com', 'Yagna@2006', role='ADMIN')
    print("==================================================")
    print("  DEFAULT ADMIN CREATED: yagna_2345 / Yagna@2006")
    print("==================================================")
else:
    print("Default admin user already exists.")
