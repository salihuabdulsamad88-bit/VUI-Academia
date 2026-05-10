import os
from app import app, db
from models import User
from werkzeug.security import generate_password_hash

with app.app_context():
    db.create_all()
    admin_user = User.query.filter_by(matric_number='ADMIN-001').first()
    if not admin_user:
        hashed_password = generate_password_hash('adminpassword123', method='scrypt')
        new_admin = User(
            full_name='System Administrator',
            matric_number='ADMIN-001',
            email='admin@vui-academia.com',
            password_hash=hashed_password,
            is_admin=True,
            department='Admin'
        )
        db.session.add(new_admin)
        db.session.commit()
        print("Admin user created successfully.")
    else:
        print("Admin user already exists.")
