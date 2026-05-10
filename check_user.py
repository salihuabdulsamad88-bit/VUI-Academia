from app import app, db
from models import User

with app.app_context():
    user = User.query.filter_by(matric_number='ADMIN-001').first()
    if user:
        print(f"User: {user.full_name}")
        print(f"Is Admin: {user.is_admin}")
        print(f"Role: {user.role}")
        print(f"Subscription: {user.subscription_status}")
    else:
        print("User ADMIN-001 not found.")
