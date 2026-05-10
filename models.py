from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from datetime import datetime

db = SQLAlchemy()

class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    full_name = db.Column(db.String(150), nullable=False)
    matric_number = db.Column(db.String(50), unique=True, nullable=False)
    email = db.Column(db.String(150), unique=True, nullable=True)
    password_hash = db.Column(db.String(256), nullable=False)
    profile_picture = db.Column(db.String(255), default='default.png')
    is_admin = db.Column(db.Boolean, default=False)
    department = db.Column(db.String(100), nullable=True)
    trial_start_date = db.Column(db.DateTime, default=datetime.utcnow)
    subscription_status = db.Column(db.String(50), default='trial') # 'trial', 'expired', 'active'
    streak_days = db.Column(db.Integer, default=0)
    role = db.Column(db.String(20), default='student') # 'student', 'lecturer', 'admin'
    security_question = db.Column(db.String(255), nullable=True)
    security_answer = db.Column(db.String(255), nullable=True)
    
    # Relationships
    bookmarks = db.relationship('Bookmark', backref='user', lazy=True)
    flashcard_decks = db.relationship('FlashcardDeck', backref='author', lazy=True)
    registered_courses = db.relationship('UserCourse', backref='user', lazy=True)
    timetable_entries = db.relationship('TimetableEntry', backref='user', lazy=True)
    notifications = db.relationship('Notification', backref='user', lazy=True)
    
    @property
    def is_trial_expired(self):
        if self.is_admin or self.subscription_status == 'active':
            return False
        from datetime import timedelta
        return datetime.utcnow() > self.trial_start_date + timedelta(days=1)


class Document(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(255), nullable=False)
    filename = db.Column(db.String(255), nullable=False)
    department = db.Column(db.String(100), nullable=False)
    level = db.Column(db.Integer, nullable=False)
    uploader_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    upload_date = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Relationships
    bookmarks = db.relationship('Bookmark', backref='document', lazy=True)
    reviews = db.relationship('Review', backref='document', lazy=True, cascade="all, delete-orphan")

class Bookmark(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    document_id = db.Column(db.Integer, db.ForeignKey('document.id'), nullable=False)
    date_bookmarked = db.Column(db.DateTime, default=datetime.utcnow)

class FlashcardDeck(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(255), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    document_id = db.Column(db.Integer, db.ForeignKey('document.id'), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    cards = db.relationship('Flashcard', backref='deck', lazy=True, cascade="all, delete-orphan")

class Flashcard(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    deck_id = db.Column(db.Integer, db.ForeignKey('flashcard_deck.id'), nullable=False)
    front_text = db.Column(db.Text, nullable=False)
    back_text = db.Column(db.Text, nullable=False)



class RecentView(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    document_id = db.Column(db.Integer, db.ForeignKey('document.id'), nullable=False)
    viewed_at = db.Column(db.DateTime, default=datetime.utcnow)
    time_spent = db.Column(db.Integer, default=0) # in seconds
    
    document = db.relationship('Document', backref='recent_views', lazy=True)

class PdfHighlight(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    document_id = db.Column(db.Integer, db.ForeignKey('document.id'), nullable=False)
    text = db.Column(db.Text, nullable=False)
    page_num = db.Column(db.Integer, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
class UserCourse(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    subject = db.Column(db.String(100), nullable=False)
    progress = db.Column(db.Integer, default=0) # 0 to 100
    date_registered = db.Column(db.DateTime, default=datetime.utcnow)

class TimetableEntry(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    day = db.Column(db.String(20), nullable=False) # Monday, Tuesday...
    time = db.Column(db.String(50), nullable=False)
    subject = db.Column(db.String(100), nullable=False)
    task = db.Column(db.String(255), nullable=True)

class Notification(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True) # Null for General notifications
    course_subject = db.Column(db.String(100), nullable=True) # For General/Course-based notifications
    title = db.Column(db.String(255), nullable=False)
    message = db.Column(db.Text, nullable=False)
    is_read = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class Review(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    document_id = db.Column(db.Integer, db.ForeignKey('document.id'), nullable=False)
    rating = db.Column(db.Integer, nullable=False) # 1 to 5
    comment = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    user = db.relationship('User', backref='reviews', lazy=True)

class AppReview(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    rating = db.Column(db.Integer, nullable=False) # 1 to 5
    comment = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    user = db.relationship('User', backref='app_reviews', lazy=True)

class Lecture(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(255), nullable=False)
    description = db.Column(db.Text, nullable=True)
    meeting_link = db.Column(db.String(500), nullable=False)
    subject = db.Column(db.String(100), nullable=False)
    level = db.Column(db.Integer, nullable=False) # 100, 200, etc.
    scheduled_at = db.Column(db.DateTime, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    is_live = db.Column(db.Boolean, default=False)
    
    # Track who created it
    creator_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    creator = db.relationship('User', backref='lectures_created')
