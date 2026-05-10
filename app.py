import os
import random
from datetime import datetime, timedelta
from flask import Flask, render_template, request, redirect, url_for, flash, send_from_directory, abort, send_file, Response, jsonify
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from flask_login import LoginManager, login_user, logout_user, login_required, current_user
from models import db, User, Document, Bookmark, FlashcardDeck, Flashcard, RecentView, PdfHighlight, UserCourse, TimetableEntry, Notification, Review, AppReview, Lecture
from flask_mail import Mail, Message
import json
import PyPDF2
import zipfile
import shutil
from dotenv import load_dotenv

load_dotenv() # Load variables from .env if it exists
# Cloudinary Configuration
if os.environ.get('CLOUDINARY_API_KEY'):
    import cloudinary
    import cloudinary.uploader
    import cloudinary.api
    cloudinary.config(
      cloud_name = os.environ.get('CLOUDINARY_CLOUD_NAME'),
      api_key = os.environ.get('CLOUDINARY_API_KEY'),
      api_secret = os.environ.get('CLOUDINARY_API_SECRET'),
      secure = True
    )

# Configure Gemini
if os.environ.get('GEMINI_API_KEY'):
    import google.generativeai as genai
    genai.configure(api_key=os.environ.get('GEMINI_API_KEY'))
    
    # Safety settings to prevent blocking academic content
    safety_settings = [
        {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_NONE"},
        {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "BLOCK_NONE"},
        {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "BLOCK_NONE"},
        {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_NONE"},
    ]

    model = genai.GenerativeModel(
        model_name='gemini-1.5-flash',
        safety_settings=safety_settings,
        generation_config={"response_mime_type": "application/json"}
    )
else:
    model = None

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'vui_academia_super_secret_key_2026')

# Handle database URL for production (PostgreSQL) vs development (SQLite)
database_url = os.environ.get('DATABASE_URL')
if database_url:
    # Ensure URL starts with postgresql://
    if database_url.startswith('postgres://'):
        database_url = database_url.replace('postgres://', 'postgresql://', 1)
    
    # Force SSL for Supabase if not specified
    if "sslmode" not in database_url:
        if "?" in database_url:
            database_url += "&sslmode=require"
        else:
            database_url += "?sslmode=require"
            
    app.config['SQLALCHEMY_DATABASE_URI'] = database_url
else:
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///vui_academia.db'

app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['UPLOAD_FOLDER'] = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'uploads')
app.config['AVATAR_FOLDER'] = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'static', 'img', 'avatars')
app.config['MAX_CONTENT_LENGTH'] = 50 * 1024 * 1024  # 50 MB max limit

# Flask-Mail Configuration
app.config['MAIL_SERVER'] = os.environ.get('MAIL_SERVER', 'smtp.gmail.com')
app.config['MAIL_PORT'] = int(os.environ.get('MAIL_PORT', 587))
app.config['MAIL_USE_TLS'] = os.environ.get('MAIL_USE_TLS', 'True') == 'True'
app.config['MAIL_USERNAME'] = os.environ.get('MAIL_USERNAME', '')
app.config['MAIL_PASSWORD'] = os.environ.get('MAIL_PASSWORD', '')
mail = Mail(app)

# Ensure upload folders exist (for local testing)
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
os.makedirs(app.config['AVATAR_FOLDER'], exist_ok=True)

db.init_app(app)
login_manager = LoginManager()
login_manager.login_view = 'login'
login_manager.init_app(app)

# Ensure database tables are created automatically on startup
try:
    with app.app_context():
        db.create_all()
        print("Database tables verified/created.")
except Exception as e:
    print(f"Database initialization warning (will retry on request): {e}")

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

@app.context_processor
def inject_notifications():
    if current_user.is_authenticated:
        # Get individual notifications
        individual = Notification.query.filter_by(user_id=current_user.id).all()
        
        # Get general notifications for user's courses
        user_subjects = [c.subject for c in current_user.registered_courses]
        general = Notification.query.filter(Notification.course_subject.in_(user_subjects)).all()
        
        all_notifs = sorted(individual + general, key=lambda x: x.created_at, reverse=True)
        unread_count = len([n for n in individual if not n.is_read]) # General are always "new" for display
        
        return dict(all_notifs=all_notifs, unread_count=unread_count)
    return dict(all_notifs=[], unread_count=0)

@app.context_processor
def inject_app_reviews():
    if current_user.is_authenticated:
        app_reviews_list = AppReview.query.order_by(AppReview.created_at.desc()).all()
        avg_app_rating = 0
        if app_reviews_list:
            avg_app_rating = sum(r.rating for r in app_reviews_list) / len(app_reviews_list)
        avg_app_rating = round(avg_app_rating, 1)
        user_app_review = AppReview.query.filter_by(user_id=current_user.id).first()
        return dict(app_reviews=app_reviews_list, avg_app_rating=avg_app_rating, user_app_review=user_app_review)
    return dict(app_reviews=[], avg_app_rating=0, user_app_review=None)

# Decorator to check subscription/trial status
def check_access(func):
    def wrapper(*args, **kwargs):
        if not current_user.is_authenticated:
            return redirect(url_for('login'))
            
        if current_user.is_admin:
            return func(*args, **kwargs)
        
        # Trial logic: 1 day free
        trial_duration = timedelta(days=1)
        # If user is still in trial, check if it has expired
        if current_user.subscription_status == 'trial':
            if datetime.utcnow() > current_user.trial_start_date + trial_duration:
                current_user.subscription_status = 'expired'
                db.session.commit()
                flash('Your 1-day free trial has expired. Please subscribe to continue.', 'warning')
                return redirect(url_for('checkout'))
        
        # If already expired, redirect to checkout
        elif current_user.subscription_status == 'expired':
            return redirect(url_for('checkout'))
        
        # 'active' status allows full access
        return func(*args, **kwargs)
    wrapper.__name__ = func.__name__
    return wrapper
@app.route('/')
def index():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))
    return render_template('index.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        matric_number = request.form.get('matric_number')
        password = request.form.get('password')
        user = User.query.filter_by(matric_number=matric_number).first()
        
        if user and check_password_hash(user.password_hash, password):
            login_user(user)
            return redirect(url_for('dashboard'))
        flash('Invalid matric number or password', 'error')
    return render_template('login.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        full_name = request.form.get('full_name')
        matric_number = request.form.get('matric_number')
        email = request.form.get('email')
        password = generate_password_hash(request.form.get('password'))
        dept = request.form.get('department')
        sq = request.form.get('security_question')
        sa = request.form.get('security_answer')
        
        existing_user = User.query.filter((User.matric_number == matric_number) | (User.email == email)).first()
        if existing_user:
            flash('Matric Number or Email already exists.', 'error')
            return redirect(url_for('register'))
            
        new_user = User(
            full_name=full_name, 
            matric_number=matric_number,
            email=email,
            password_hash=password, 
            is_admin=False, 
            department=dept,
            security_question=sq,
            security_answer=sa
        )
        db.session.add(new_user)
        db.session.commit()
        
        # Try to send a welcome email
        try:
            if app.config['MAIL_USERNAME'] and email:
                msg = Message("Welcome to VUI Academia!",
                              recipients=[email])
                msg.body = f"Hello {full_name},\n\nWelcome to VUI Academia! Your account has been created successfully.\n\nEnjoy your 1-day free trial!"
                mail.send(msg)
        except Exception as e:
            print(f"Failed to send welcome email: {e}")
        
        login_user(new_user)
        return redirect(url_for('dashboard'))
    return render_template('register.html')

@app.route('/profile', methods=['GET', 'POST'])
@login_required
def profile():
    if request.method == 'POST':
        new_full_name = request.form.get('full_name')
        new_email = request.form.get('email')
        new_dept = request.form.get('department')
        new_pass = request.form.get('new_password')
        
        # Handle avatar
        if 'profile_picture' in request.files:
            file = request.files['profile_picture']
            if file and file.filename != '':
                filename = secure_filename(f"user_{current_user.id}_{file.filename}")
                
                if os.environ.get('CLOUDINARY_API_KEY'):
                    try:
                        # Upload to Cloudinary
                        upload_result = cloudinary.uploader.upload(
                            file,
                            folder="avatars",
                            public_id=f"user_{current_user.id}",
                            overwrite=True,
                            resource_type="image"
                        )
                        current_user.profile_picture = upload_result.get('secure_url')
                    except Exception as e:
                        print(f"Cloudinary profile pic error: {e}")
                        flash("Error uploading profile picture to cloud.", "error")
                else:
                    # Local fallback
                    file.save(os.path.join(app.config['AVATAR_FOLDER'], filename))
                    current_user.profile_picture = filename
        
        if new_full_name:
            current_user.full_name = new_full_name
        current_user.email = new_email
        current_user.department = new_dept
        
        if new_pass:
            current_user.password_hash = generate_password_hash(new_pass)
            
        db.session.commit()
        flash('Profile updated successfully!', 'success')
        return redirect(url_for('profile'))
        
    return render_template('profile.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('index'))

def get_daily_quote():
    quotes = [
        {"text": "Education is the most powerful weapon which you can use to change the world.", "author": "Nelson Mandela"},
        {"text": "The secret of getting ahead is getting started.", "author": "Mark Twain"},
        {"text": "It always seems impossible until it's done.", "author": "Nelson Mandela"},
        {"text": "Believe you can and you're halfway there.", "author": "Theodore Roosevelt"},
        {"text": "The only way to do great work is to love what you do.", "author": "Steve Jobs"},
        {"text": "Don't watch the clock; do what it does. Keep going.", "author": "Sam Levenson"},
        {"text": "Your talent determines what you can do. Your motivation determines how much you are willing to do. Your attitude determines how well you do it.", "author": "Lou Holtz"},
        {"text": "Success is not final, failure is not fatal: it is the courage to continue that counts.", "author": "Winston Churchill"},
        {"text": "The beautiful thing about learning is that no one can take it away from you.", "author": "B.B. King"},
        {"text": "Start where you are. Use what you have. Do what you can.", "author": "Arthur Ashe"}
    ]
    # Pick a quote based on the day of the year
    day_of_year = datetime.utcnow().timetuple().tm_yday
    return quotes[day_of_year % len(quotes)]

@app.route('/dashboard')
@login_required
def dashboard():
    department = request.args.get('department', 'all')
    level = request.args.get('level', 'all')
    search_query = request.args.get('q', '')

    query = Document.query
    if department != 'all':
        query = query.filter_by(department=department)
    if level != 'all':
        query = query.filter_by(level=int(level))
    if search_query:
        query = query.filter(Document.title.ilike(f'%{search_query}%'))

    # Get all unique departments for the sidebar
    all_departments = [d[0] for d in db.session.query(Document.department).distinct().all()]
    
    documents = query.order_by(Document.upload_date.desc()).all()
    bookmarks = [b.document_id for b in current_user.bookmarks]
    
    # Calculate trial remaining
    trial_remaining = None
    if current_user.subscription_status == 'trial' and not current_user.is_admin:
        expiry = current_user.trial_start_date + timedelta(days=1)
        trial_remaining = expiry - datetime.utcnow()
        if trial_remaining.total_seconds() < 0:
            trial_remaining = None

    daily_quote = get_daily_quote()
    
    return render_template('dashboard.html', 
                           documents=documents, 
                           bookmarks=bookmarks, 
                           trial_remaining=trial_remaining,
                           all_departments=all_departments,
                           daily_quote=daily_quote)

@app.route('/account', methods=['GET', 'POST'])
@login_required
def account():
    if request.method == 'POST':
        email = request.form.get('email')
        
        # Check if email is already used
        if email and email != current_user.email:
            existing = User.query.filter_by(email=email).first()
            if existing:
                flash('Email is already registered by another account.', 'error')
                return redirect(url_for('account'))
            current_user.email = email
            
        if 'profile_picture' in request.files:
            file = request.files['profile_picture']
            if file and file.filename != '':
                filename = secure_filename(f"user_{current_user.id}_{file.filename}")
                file_path = os.path.join(app.config['AVATAR_FOLDER'], filename)
                file.save(file_path)
                current_user.profile_picture = filename
                
        # Security Questions
        sq = request.form.get('security_question')
        sa = request.form.get('security_answer')
        if sq: current_user.security_question = sq
        if sa: current_user.security_answer = sa

        db.session.commit()
        flash('Account updated successfully.', 'success')
        return redirect(url_for('account'))
        
    return render_template('account.html')

# --- STUDY HUB ROUTES ---

@app.route('/study')
@login_required
@check_access
def study_hub():
    decks = FlashcardDeck.query.filter_by(user_id=current_user.id).all()
    return render_template('study_hub.html', decks=decks)

@app.route('/flashcards/create', methods=['POST'])
@login_required
@check_access
def create_flashcard_deck():
    title = request.form.get('title')
    fronts = request.form.getlist('front_text[]')
    backs = request.form.getlist('back_text[]')
    
    if not title or not fronts:
        flash("Deck must have a title and at least one card.", 'error')
        return redirect(url_for('study_hub'))
        
    deck = FlashcardDeck(title=title, user_id=current_user.id)
    db.session.add(deck)
    db.session.commit() # to get deck.id
    
    for f, b in zip(fronts, backs):
        if f and b:
            card = Flashcard(deck_id=deck.id, front_text=f, back_text=b)
            db.session.add(card)
            
    db.session.commit()
    flash("Flashcard deck created!", 'success')
    return redirect(url_for('study_hub'))

@app.route('/flashcards/<int:deck_id>')
@login_required
@check_access
def view_flashcards(deck_id):
    deck = FlashcardDeck.query.get_or_404(deck_id)
    if deck.user_id != current_user.id:
        abort(403)
    return render_template('flashcards.html', deck=deck)

@app.route('/ai-generator', methods=['GET', 'POST'])
@login_required
@check_access
def ai_generator():
    generated_deck = None
    if request.method == 'POST':
        subject = request.form.get('subject')
        topic = request.form.get('topic')
        
        try:
            # Using User's Custom Prompt and Logic
            prompt = f"""
            Generate 25 comprehensive flashcards for a university student studying {subject}. 
            The specific topic is: "{topic}".
            
            Return ONLY a JSON array of objects with these keys: 
            "question" (academic question), "answer" (memorizable answer), 
            "difficulty" (EASY, MEDIUM, or HARD), and "category" (sub-topic).
            
            Format: [ {{"question": "...", "answer": "...", "difficulty": "...", "category": "..."}}, ... ]
            """
            
            # Use JSON mode if supported by the model config
            response = model.generate_content(prompt)
            
            if not response or not response.text:
                flash("AI Error: Received an empty response. Please try again.", "error")
                return redirect(url_for('ai_generator'))

            # More robust JSON extraction
            clean_text = response.text.strip()
            # If AI wrapped it in markdown ```json ... ```
            if "```" in clean_text:
                import re
                json_match = re.search(r'\[.*\]', clean_text, re.DOTALL)
                if json_match:
                    clean_text = json_match.group(0)
            
            cards_data = json.loads(clean_text)
            
            if not isinstance(cards_data, list):
                if isinstance(cards_data, dict) and 'flashcards' in cards_data:
                    cards_data = cards_data['flashcards']
                else:
                    raise ValueError("AI response is not a list of cards.")

            deck = FlashcardDeck(title=f"AI Expert Deck: {topic}", user_id=current_user.id)
            db.session.add(deck)
            db.session.flush()
            
            for data in cards_data:
                diff = str(data.get('difficulty', 'MEDIUM')).upper()
                card = Flashcard(
                    deck_id=deck.id,
                    front_text=data.get('question', 'Missing Question'),
                    back_text=f"[{diff}] {data.get('answer', 'No answer provided.')}"
                )
                db.session.add(card)
            
            db.session.commit()
            generated_deck = deck
            flash(f'Successfully generated {len(cards_data)} cards for "{topic}"!', 'success')
        except Exception as e:
            error_msg = str(e)
            print(f"Gemini Error Trace: {error_msg}")
            db.session.rollback()
            if "API_KEY" in error_msg.upper():
                flash("AI Error: Missing or Invalid API Key. Please set GEMINI_API_KEY.", "error")
            elif "429" in error_msg:
                flash("AI Error: Rate limit reached. Please wait a minute and try again.", "error")
            else:
                flash(f"AI Error: {error_msg[:100]}", "error")
        
    return render_template('ai_generator.html', generated_deck=generated_deck)



@app.route('/generate-materials/<int:doc_id>', methods=['POST'])
@login_required
@check_access
def generate_materials(doc_id):
    doc = Document.query.get_or_404(doc_id)
    file_path = os.path.join(app.config['UPLOAD_FOLDER'], doc.filename)
    
    # 1. Extract text from first 5 pages
    extracted_text = ""
    try:
        with open(file_path, 'rb') as f:
            reader = PyPDF2.PdfReader(f)
            num_pages = min(len(reader.pages), 10) # Gemini can handle more
            for i in range(num_pages):
                extracted_text += reader.pages[i].extract_text() + "\n"
    except Exception as e:
        flash(f'Error reading PDF: {str(e)}', 'error')
        return redirect(url_for('dashboard'))
        
    # 2. Call Gemini for topic extraction
    try:
        prompt = f"""
        Analyze the following academic text and provide:
        1. A concise summary of the main subject.
        2. 8-10 key academic concepts with their detailed definitions.
        
        Return ONLY a JSON array of objects, each with 'topic' and 'definition' keys.
        The first object should have the topic 'SUMMARY' and the definition as the overall summary.
        Focus strictly on text content; ignore any images or diagrams.
        
        TEXT:
        {extracted_text[:12000]} 
        """
        response = model.generate_content(prompt)
        if not response or not response.text:
            flash("AI Error: Received an empty analysis. Please try again.", "error")
            return redirect(url_for('dashboard'))

        # Robust JSON extraction
        clean_text = response.text.strip()
        if "```" in clean_text:
            import re
            json_match = re.search(r'\[.*\]', clean_text, re.DOTALL)
            if json_match:
                clean_text = json_match.group(0)
        
        cards_data = json.loads(clean_text)
        
        deck = FlashcardDeck(title=f"AI Analysis: {doc.title}", user_id=current_user.id, document_id=doc.id)
        db.session.add(deck)
        db.session.flush()
        
        for data in cards_data:
            card = Flashcard(
                deck_id=deck.id,
                front_text=data.get('topic', 'Key Concept'),
                back_text=data.get('definition', 'No definition extracted.')
            )
            db.session.add(card)
        
        db.session.commit()
        flash(f"Gemini AI has successfully analyzed the text and created a Study Deck with {len(cards_data)} key points!", 'success')
        return redirect(url_for('dashboard'))
    except Exception as e:
        error_msg = str(e)
        print(f"Gemini Material Error: {error_msg}")
        db.session.rollback()
        flash(f"AI Analysis failed: {error_msg[:100]}", "error")
        return redirect(url_for('dashboard'))
    

    
    flash("Study materials successfully generated using AI Mock Model!", 'success')
    return redirect(url_for('study_hub'))



@app.route('/admin', methods=['GET', 'POST'])
@login_required
def admin():
    if not current_user.is_admin and current_user.role not in ['admin', 'lecturer']:
        abort(403)
    
    if request.method == 'POST':
        print(f"POST request to /admin received. Files: {request.files}")
        if 'files[]' not in request.files:
            flash('No files selected', 'error')
            return redirect(request.url)
            
        files = request.files.getlist('files[]')
        
        # Limit to 10 files
        if len(files) > 10:
            flash('Maximum 10 files can be uploaded at once.', 'error')
            return redirect(request.url)
            
        title_base = request.form.get('title')
        department = request.form.get('department')
        level = request.form.get('level')
        print(f"Upload request received: title={title_base}, dept={department}, level={level}")
        
        uploaded_count = 0
        for i, file in enumerate(files):
            if file and file.filename.endswith(('.pdf', '.pptx', '.ppt')):
                filename = secure_filename(file.filename)
                # Make unique filename
                timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
                unique_filename = f"{timestamp}_{i}_{filename}"
                
                # Force local storage in development to avoid timeouts
                is_dev = os.environ.get('FLASK_ENV') == 'development'
                if os.environ.get('CLOUDINARY_API_KEY') and not is_dev:
                    try:
                        print(f"Uploading file to Cloudinary: {filename}")
                        # We use resource_type='raw' for PDFs/PPTX to preserve original file info
                        upload_result = cloudinary.uploader.upload(
                            file, 
                            public_id=unique_filename.rsplit('.', 1)[0],
                            resource_type='raw'
                        )
                        file_url = upload_result.get('secure_url')
                        final_filename = file_url
                    except Exception as e:
                        print(f"Cloudinary upload error: {e}")
                        # Fallback to local if cloud fails
                        file_path = os.path.join(app.config['UPLOAD_FOLDER'], unique_filename)
                        file.seek(0) # Reset file pointer after failed upload attempt
                        file.save(file_path)
                        final_filename = unique_filename
                else:
                    # Local storage fallback (used in development)
                    file_path = os.path.join(app.config['UPLOAD_FOLDER'], unique_filename)
                    file.save(file_path)
                    final_filename = unique_filename
                
                # Determine title: if multiple, append index
                title = title_base if len(files) == 1 else f"{title_base} - Part {i+1}"
                if not title_base:
                    title = filename.rsplit('.', 1)[0].replace('_', ' ').title()
                
                new_doc = Document(
                    title=title, 
                    filename=final_filename, 
                    department=department, 
                    level=int(level),
                    uploader_id=current_user.id
                )
                db.session.add(new_doc)
                uploaded_count += 1
        
        db.session.commit()
        if uploaded_count > 0:
            flash(f'{uploaded_count} files successfully uploaded', 'success')
        return redirect(url_for('admin'))
    
    if current_user.is_admin or current_user.role == 'admin':
        documents = Document.query.order_by(Document.upload_date.desc()).all()
    else:
        documents = Document.query.filter_by(uploader_id=current_user.id).order_by(Document.upload_date.desc()).all()
        
    users = User.query.filter_by(is_admin=False).all()
    user_count = len(users)
    lectures = Lecture.query.order_by(Lecture.scheduled_at.desc()).all()
    return render_template('admin.html', documents=documents, users=users, user_count=user_count, lectures=lectures)

@app.route('/admin/activate/<int:user_id>', methods=['POST'])
@login_required
def activate_premium(user_id):
    if not current_user.is_admin and current_user.role != 'admin':
        abort(403)
    user = User.query.get_or_404(user_id)
    user.subscription_status = 'active'
    db.session.commit()
    flash(f'Premium activated for {user.full_name}!', 'success')
    return redirect(url_for('admin'))

@app.route('/admin/make-lecturer/<int:user_id>', methods=['POST'])
@login_required
def make_lecturer(user_id):
    if not current_user.is_admin and current_user.role != 'admin':
        abort(403)
    user = User.query.get_or_404(user_id)
    user.role = 'lecturer'
    user.subscription_status = 'active'
    db.session.commit()
    flash(f'{user.full_name} is now a Lecturer and has been granted Premium access!', 'success')
    return redirect(url_for('admin'))

@app.route('/admin/notify', methods=['POST'])
@login_required
def send_notification():
    if not current_user.is_admin and current_user.role != 'admin':
        abort(403)
    
    target_type = request.form.get('target_type') # 'individual' or 'general'
    title = request.form.get('title')
    message = request.form.get('message')
    
    if target_type == 'individual':
        user_id = request.form.get('user_id')
        new_notif = Notification(user_id=user_id, title=title, message=message)
        db.session.add(new_notif)
    else:
        # General - for a specific course/subject
        course_subject = request.form.get('course_subject')
        # We store one notification record as a "General" template
        new_notif = Notification(course_subject=course_subject, title=title, message=message)
        db.session.add(new_notif)
        
    db.session.commit()
    flash('Notification sent successfully!', 'success')
    return redirect(url_for('admin'))

@app.route('/admin/email-all', methods=['POST'])
@login_required
def admin_email_all():
    if not current_user.is_admin and current_user.role != 'admin':
        abort(403)
    
    subject = request.form.get('email_subject')
    body = request.form.get('email_body')
    
    if not subject or not body:
        flash('Please provide both subject and message.', 'error')
        return redirect(url_for('admin'))
    
    if not app.config['MAIL_USERNAME']:
        flash('Email is not configured. Please add MAIL_USERNAME and MAIL_PASSWORD to your .env file.', 'error')
        return redirect(url_for('admin'))
    
    # Get all users with email addresses
    users_with_email = User.query.filter(User.email.isnot(None), User.email != '').all()
    
    sent_count = 0
    for user in users_with_email:
        try:
            msg = Message(subject, recipients=[user.email])
            msg.body = f"Hello {user.full_name},\n\n{body}\n\n— VUI Academia Team"
            mail.send(msg)
            sent_count += 1
        except Exception as e:
            print(f"Failed to email {user.email}: {e}")
    
    flash(f'Email sent successfully to {sent_count} users!', 'success')
    return redirect(url_for('admin'))

@app.route('/download/<int:doc_id>')
@login_required
def download_document(doc_id):
    doc = Document.query.get_or_404(doc_id)
    
    # Only premium/active users and admins can download
    if current_user.subscription_status != 'active' and not current_user.is_admin:
        flash('Downloading documents is a Premium feature. Please subscribe to download.', 'warning')
        return redirect(url_for('checkout'))
    
    # Handle Cloudinary URLs
    if doc.filename.startswith('http'):
        return redirect(doc.filename)
        
    file_path = os.path.join(app.config['UPLOAD_FOLDER'], doc.filename)
    if not os.path.exists(file_path):
        flash('File not found locally.', 'error')
        return redirect(url_for('dashboard'))
    
    return send_file(file_path, as_attachment=True, download_name=doc.title + os.path.splitext(doc.filename)[1])

@app.route('/admin/delete/<int:doc_id>', methods=['POST'])
@login_required
def delete_document(doc_id):
    if not current_user.is_admin and current_user.role not in ['admin', 'lecturer']:
        abort(403)
    
    doc = Document.query.get_or_404(doc_id)
    
    # Delete file
    file_path = os.path.join(app.config['UPLOAD_FOLDER'], doc.filename)
    if os.path.exists(file_path):
        os.remove(file_path)
    
    # Clean up related records first
    RecentView.query.filter_by(document_id=doc_id).delete()
    Bookmark.query.filter_by(document_id=doc_id).delete()
    Review.query.filter_by(document_id=doc_id).delete()
    PdfHighlight.query.filter_by(document_id=doc_id).delete()
        
    # Delete from DB
    db.session.delete(doc)
    db.session.commit()
    flash('Document deleted successfully', 'success')
    return redirect(url_for('admin'))

@app.route('/admin/edit-document/<int:doc_id>', methods=['POST'])
@login_required
def edit_document(doc_id):
    if not current_user.is_admin and current_user.role not in ['admin', 'lecturer']:
        abort(403)
    
    doc = Document.query.get_or_404(doc_id)
    doc.title = request.form.get('title')
    doc.subject = request.form.get('subject')
    doc.level = int(request.form.get('level'))
    
    db.session.commit()
    flash('Document updated successfully!', 'success')
    return redirect(url_for('admin'))

@app.route('/lectures')
@login_required
def lectures():
    # Show upcoming lectures first, then live ones
    upcoming = Lecture.query.filter(Lecture.scheduled_at > datetime.utcnow()).order_by(Lecture.scheduled_at.asc()).all()
    live_now = Lecture.query.filter_by(is_live=True).all()
    past = Lecture.query.filter(Lecture.scheduled_at <= datetime.utcnow(), Lecture.is_live == False).order_by(Lecture.scheduled_at.desc()).limit(10).all()
    
    return render_template('lectures.html', upcoming=upcoming, live_now=live_now, past=past)

@app.route('/admin/add-lecture', methods=['POST'])
@login_required
def add_lecture():
    if not current_user.is_admin and current_user.role not in ['admin', 'lecturer']:
        abort(403)
        
    title = request.form.get('title')
    description = request.form.get('description')
    meeting_link = request.form.get('meeting_link')
    subject = request.form.get('subject')
    level = int(request.form.get('level'))
    scheduled_at_str = request.form.get('scheduled_at') # 'YYYY-MM-DDTHH:MM'
    
    scheduled_at = datetime.strptime(scheduled_at_str, '%Y-%m-%dT%H:%M')
    
    new_lecture = Lecture(
        title=title,
        description=description,
        meeting_link=meeting_link,
        subject=subject,
        level=level,
        scheduled_at=scheduled_at,
        creator_id=current_user.id
    )
    
    db.session.add(new_lecture)
    db.session.commit()
    
    flash('Online Lecture scheduled successfully!', 'success')
    return redirect(url_for('admin'))

@app.route('/admin/lecture/live/<int:lecture_id>', methods=['POST'])
@login_required
def toggle_lecture_live(lecture_id):
    if not current_user.is_admin and current_user.role not in ['admin', 'lecturer']:
        abort(403)
        
    lecture = Lecture.query.get_or_404(lecture_id)
    lecture.is_live = not lecture.is_live
    db.session.commit()
    
    status = "is now LIVE!" if lecture.is_live else "has ended."
    flash(f'Lecture "{lecture.title}" {status}', 'success')
    return redirect(url_for('admin'))

@app.route('/admin/lecture/delete/<int:lecture_id>', methods=['POST'])
@login_required
def delete_lecture(lecture_id):
    if not current_user.is_admin and current_user.role not in ['admin', 'lecturer']:
        abort(403)
        
    lecture = Lecture.query.get_or_404(lecture_id)
    db.session.delete(lecture)
    db.session.commit()
    
    flash('Lecture removed from schedule.', 'success')
    return redirect(url_for('admin'))



@app.route('/update-study-time', methods=['POST'])
@login_required
def update_study_time():
    try:
        data = request.json
        doc_id = data.get('doc_id')
        session = RecentView.query.filter_by(user_id=current_user.id, document_id=doc_id).order_by(RecentView.last_viewed.desc()).first()
        
        if not session:
            session = RecentView(user_id=current_user.id, document_id=doc_id, time_spent=0)
            db.session.add(session)
        
        session.time_spent += 30 # Heartbeat is 30s
        session.last_viewed = datetime.utcnow()
        
        # Mark as completed if > 5 minutes
        if session.time_spent >= 300:
            session.completed = True
            
        db.session.commit()
        return jsonify({"status": "success", "time_spent": session.time_spent, "completed": session.completed})
    except Exception as e:
        print(f"Heartbeat Error: {e}")
        return jsonify({"status": "error"}), 500

@app.route('/view/<int:doc_id>')
@login_required
@check_access
def view_document(doc_id):
    doc = Document.query.get_or_404(doc_id)
    
    # Log recent view
    # Check if already exists today or just update the timestamp
    recent = RecentView.query.filter_by(user_id=current_user.id, document_id=doc.id).first()
    if recent:
        recent.last_viewed = datetime.utcnow()
    else:
        recent = RecentView(user_id=current_user.id, document_id=doc.id)
        db.session.add(recent)
    db.session.commit()
    
    highlights = PdfHighlight.query.filter_by(user_id=current_user.id, document_id=doc.id).all()
    
    # Fetch PDF reviews
    reviews = Review.query.filter_by(document_id=doc.id).order_by(Review.created_at.desc()).all()
    avg_rating = 0
    if reviews:
        avg_rating = sum(r.rating for r in reviews) / len(reviews)
    avg_rating = round(avg_rating, 1)
    
    # Check if current user has already reviewed the PDF
    user_review = Review.query.filter_by(user_id=current_user.id, document_id=doc.id).first()
    
    return render_template('view.html', document=doc, highlights=highlights, reviews=reviews, avg_rating=avg_rating, user_review=user_review)

@app.route('/pdf/<path:filename>')
@login_required
@check_access
def serve_pdf(filename):
    if filename.startswith('http'):
        return redirect(filename)
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)

@app.route('/api/pptx-slides/<int:doc_id>')
@login_required
def get_pptx_slides(doc_id):
    """Extract slide content from a PPTX file and return as JSON."""
    from pptx import Presentation
    import requests
    from io import BytesIO
    
    doc = Document.query.get_or_404(doc_id)
    
    try:
        if doc.filename.startswith('http'):
            # Fetch from Cloudinary
            response = requests.get(doc.filename)
            file_stream = BytesIO(response.content)
            prs = Presentation(file_stream)
        else:
            # Local file
            file_path = os.path.join(app.config['UPLOAD_FOLDER'], doc.filename)
            if not os.path.exists(file_path):
                return jsonify({'error': 'File not found'}), 404
            prs = Presentation(file_path)
        slides_data = []
        
        for slide_num, slide in enumerate(prs.slides, 1):
            slide_content = {
                'number': slide_num,
                'shapes': []
            }
            
            for shape in slide.shapes:
                shape_data = {
                    'left': shape.left if shape.left else 0,
                    'top': shape.top if shape.top else 0,
                    'width': shape.width if shape.width else 0,
                    'height': shape.height if shape.height else 0,
                }
                
                if shape.has_text_frame:
                    paragraphs = []
                    for para in shape.text_frame.paragraphs:
                        runs = []
                        for run in para.runs:
                            run_data = {
                                'text': run.text,
                                'bold': run.font.bold or False,
                                'italic': run.font.italic or False,
                                'size': run.font.size.pt if run.font.size else 18,
                            }
                            # Try to get font color correctly
                            try:
                                if run.font.color and run.font.color.type == 1: # RGB color
                                    rgb = run.font.color.rgb
                                    run_data['color'] = f"{rgb[0]:02x}{rgb[1]:02x}{rgb[2]:02x}"
                                elif run.font.color and run.font.color.type == 2: # Theme color
                                    # Fallback for theme colors as they are complex to map without theme definition
                                    pass
                            except Exception as e:
                                print(f"Color extraction error: {e}")
                                pass
                            runs.append(run_data)
                        
                        # Determine alignment
                        alignment = 'left'
                        if para.alignment:
                            align_val = str(para.alignment)
                            if 'CENTER' in align_val:
                                alignment = 'center'
                            elif 'RIGHT' in align_val:
                                alignment = 'right'
                        
                        paragraphs.append({
                            'runs': runs,
                            'alignment': alignment,
                            'level': para.level or 0
                        })
                    
                    shape_data['type'] = 'text'
                    shape_data['paragraphs'] = paragraphs
                    slide_content['shapes'].append(shape_data)
                    
                elif shape.has_table:
                    table = shape.table
                    rows_data = []
                    for row in table.rows:
                        cells = []
                        for cell in row.cells:
                            cells.append(cell.text)
                        rows_data.append(cells)
                    
                    shape_data['type'] = 'table'
                    shape_data['rows'] = rows_data
                    slide_content['shapes'].append(shape_data)
            
            slides_data.append(slide_content)
        
        return jsonify({
            'total_slides': len(slides_data),
            'slides': slides_data
        })
    except Exception as e:
        print(f"PPTX parse error: {e}")
        return jsonify({'error': f'Failed to parse PPTX: {str(e)}'}), 500

@app.route('/bookmark/<int:doc_id>', methods=['POST'])
@login_required
@check_access
def toggle_bookmark(doc_id):
    doc = Document.query.get_or_404(doc_id)
    existing_bookmark = Bookmark.query.filter_by(user_id=current_user.id, document_id=doc.id).first()
    
    if existing_bookmark:
        db.session.delete(existing_bookmark)
        db.session.commit()
        return {'status': 'removed'}
    else:
        new_bookmark = Bookmark(user_id=current_user.id, document_id=doc.id)
        db.session.add(new_bookmark)
        db.session.commit()
        return {'status': 'added'}

@app.route('/recent')
@login_required
def recent_history():
    recent_views = RecentView.query.filter_by(user_id=current_user.id).order_by(RecentView.viewed_at.desc()).all()
    return render_template('recent.html', recent_views=recent_views)

@app.route('/bookmarks')
@login_required
def bookmarks_view():
    user_bookmarks = Bookmark.query.filter_by(user_id=current_user.id).order_by(Bookmark.date_bookmarked.desc()).all()
    return render_template('bookmarks.html', bookmarks=user_bookmarks)

@app.route('/api/highlight', methods=['POST'])
@login_required
def save_highlight():
    data = request.json
    doc_id = data.get('doc_id')
    text = data.get('text')
    page_num = data.get('page_num', 1)
    
    if not doc_id or not text:
        return {'error': 'Missing data'}, 400
        
    highlight = PdfHighlight(user_id=current_user.id, document_id=doc_id, text=text, page_num=page_num)
    db.session.add(highlight)
    db.session.commit()
    
    return {'status': 'success', 'id': highlight.id}

@app.route('/api/highlight/<int:h_id>', methods=['DELETE'])
@login_required
def delete_highlight(h_id):
    highlight = PdfHighlight.query.get_or_404(h_id)
    if highlight.user_id != current_user.id:
        abort(403)
    db.session.delete(highlight)
    db.session.commit()
    return {'status': 'deleted'}

@app.route('/app-rating', methods=['GET'])
@login_required
def app_rating_page():
    reviews = AppReview.query.order_by(AppReview.created_at.desc()).all()
    user_review = AppReview.query.filter_by(user_id=current_user.id).first()
    
    avg_rating = 0
    if reviews:
        avg_rating = sum(r.rating for r in reviews) / len(reviews)
    avg_rating = round(avg_rating, 1)
    
    return render_template('app_rating.html', reviews=reviews, user_review=user_review, avg_rating=avg_rating)

@app.route('/api/review', methods=['POST'])
@login_required
def submit_review():
    data = request.json
    rating = data.get('rating')
    comment = data.get('comment')
    
    if not rating:
        return {'status': 'error', 'message': 'Missing data'}, 400
        
    try:
        rating = int(rating)
        if rating < 1 or rating > 5:
            return {'status': 'error', 'message': 'Invalid rating'}, 400
    except ValueError:
        return {'status': 'error', 'message': 'Invalid rating'}, 400
        
    # Check if user already reviewed the app
    existing_review = AppReview.query.filter_by(user_id=current_user.id).first()
    if existing_review:
        existing_review.rating = rating
        existing_review.comment = comment
        db.session.commit()
        return {'status': 'success', 'message': 'Review updated', 'action': 'updated'}
    
    new_review = AppReview(user_id=current_user.id, rating=rating, comment=comment)
    db.session.add(new_review)
    db.session.commit()
    
    return {
        'status': 'success', 
        'message': 'Review submitted', 
        'action': 'added'
    }

@app.route('/api/pdf_review', methods=['POST'])
@login_required
def submit_pdf_review():
    data = request.json
    doc_id = data.get('doc_id')
    rating = data.get('rating')
    comment = data.get('comment')
    
    if not doc_id or not rating:
        return {'status': 'error', 'message': 'Missing data'}, 400
        
    try:
        rating = int(rating)
        if rating < 1 or rating > 5:
            return {'status': 'error', 'message': 'Invalid rating'}, 400
    except ValueError:
        return {'status': 'error', 'message': 'Invalid rating'}, 400
        
    # Check if user already reviewed the PDF
    existing_review = Review.query.filter_by(user_id=current_user.id, document_id=doc_id).first()
    if existing_review:
        existing_review.rating = rating
        existing_review.comment = comment
        db.session.commit()
        return {'status': 'success', 'message': 'Review updated', 'action': 'updated'}
    
    new_review = Review(user_id=current_user.id, document_id=doc_id, rating=rating, comment=comment)
    db.session.add(new_review)
    db.session.commit()
    
    return {
        'status': 'success', 
        'message': 'Review submitted', 
        'action': 'added'
    }

@app.route('/checkout', methods=['GET', 'POST'])
@login_required
def checkout():
    if current_user.subscription_status == 'active':
        return redirect(url_for('dashboard'))
        
    return render_template('checkout.html')

@app.route('/verify-payment', methods=['POST'])
@login_required
def verify_payment():
    # In manual mode, this just notifies the admin or sets to pending
    # For now, we'll keep it as a simulated success or a "Notify Admin" action
    flash('Payment notification sent! Admin will verify your transfer shortly.', 'success')
    return redirect(url_for('dashboard'))

# --- PROGRESS & TIMETABLE ROUTES ---

@app.route('/progress')
@login_required
def progress_tracker():
    courses = current_user.registered_courses
    
    for course in courses:
        # Check if this "subject" is actually a specific document title
        specific_doc = Document.query.filter_by(title=course.subject).first()
        
        if specific_doc:
            # Tracking a single specific document
            total_docs = 1
            view = RecentView.query.filter_by(user_id=current_user.id, document_id=specific_doc.id).first()
            completed_docs_count = 1 if view and view.time_spent >= 300 else 0
        else:
            # Tracking an entire department/subject
            total_docs = Document.query.filter(Document.department.ilike(f'%{course.subject}%')).count()
            completed_docs_count = db.session.query(RecentView.document_id)\
                .join(Document, RecentView.document_id == Document.id)\
                .filter(RecentView.user_id == current_user.id, 
                        Document.department.ilike(f'%{course.subject}%'),
                        RecentView.time_spent >= 300)\
                .distinct()\
                .count()
            
        if total_docs > 0:
            course.progress = min(100, int((completed_docs_count / total_docs) * 100))
        else:
            course.progress = 0
            
        db.session.commit()
        
    return render_template('progress.html', courses=courses)

@app.route('/register-course', methods=['GET', 'POST'])
@login_required
def register_course():
    if request.method == 'POST':
        subject = request.form.get('subject')
        if subject:
            # Check if already registered
            existing = UserCourse.query.filter_by(user_id=current_user.id, subject=subject).first()
            if not existing:
                new_course = UserCourse(user_id=current_user.id, subject=subject)
                db.session.add(new_course)
                db.session.commit()
                flash(f'Successfully started tracking {subject}!', 'success')
            return redirect(url_for('progress_tracker'))
            
    # Pull unique departments from actual documents
    depts = [d[0] for d in db.session.query(Document.department).distinct().all()]
    
    # Pull all individual document titles
    docs = Document.query.all()
    
    return render_template('course_registration.html', subjects=sorted(depts), documents=docs)

@app.route('/timetable', methods=['GET', 'POST'])
@login_required
def timetable():
    if request.method == 'POST':
        day = request.form.get('day')
        time = request.form.get('time')
        subject = request.form.get('subject')
        task = request.form.get('task')
        
        new_entry = TimetableEntry(user_id=current_user.id, day=day, time=time, subject=subject, task=task)
        db.session.add(new_entry)
        db.session.commit()
        return redirect(url_for('timetable'))
        
    entries = {}
    days = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']
    for day in days:
        entries[day] = TimetableEntry.query.filter_by(user_id=current_user.id, day=day).all()
        
    return render_template('timetable.html', entries=entries, days=days)

@app.route('/timetable/delete/<int:entry_id>', methods=['POST'])
@login_required
def delete_timetable(entry_id):
    entry = TimetableEntry.query.get_or_404(entry_id)
    if entry.user_id != current_user.id:
        abort(403)
    db.session.delete(entry)
    db.session.commit()
    flash('Schedule entry removed.', 'success')
    return redirect(url_for('timetable'))

@app.route('/timetable/edit/<int:entry_id>', methods=['POST'])
@login_required
def edit_timetable(entry_id):
    entry = TimetableEntry.query.get_or_404(entry_id)
    if entry.user_id != current_user.id:
        abort(403)
    entry.day = request.form.get('day')
    entry.time = request.form.get('time')
    entry.subject = request.form.get('subject')
    entry.task = request.form.get('task')
    db.session.commit()
    flash('Schedule entry updated.', 'success')
    return redirect(url_for('timetable'))

@app.route('/forgot-password', methods=['GET', 'POST'])
def forgot_password():
    if request.method == 'POST':
        email = request.form.get('email')
        user = User.query.filter_by(email=email).first()
        if user:
            if not user.security_question:
                flash('This account has no security question set. Please contact admin.', 'error')
                return redirect(url_for('login'))
            return render_template('reset_password.html', user=user)
        flash('Email not found.', 'error')
    return render_template('forgot_password.html')

@app.route('/reset-password/<int:user_id>', methods=['POST'])
def reset_password(user_id):
    user = User.query.get_or_404(user_id)
    answer = request.form.get('answer')
    new_password = request.form.get('new_password')
    
    if user.security_answer and user.security_answer.lower() == answer.lower().strip():
        user.password_hash = generate_password_hash(new_password)
        db.session.commit()
        flash('Password reset successful! Please login.', 'success')
        return redirect(url_for('login'))
    else:
        flash('Incorrect security answer.', 'error')
        return redirect(url_for('forgot_password'))

@app.route('/admin/reset-password', methods=['POST'])
@login_required
def admin_reset_password():
    if not current_user.is_admin:
        flash("Unauthorized access.", "error")
        return redirect(url_for('index'))
    
    user_id = request.form.get('user_id')
    new_password = request.form.get('new_password')
    
    user = User.query.get(user_id)
    if user:
        user.password_hash = generate_password_hash(new_password)
        db.session.commit()
        flash(f"Password reset for {user.full_name} successfully!", "success")
    else:
        flash("User not found.", "error")
        
    return redirect(url_for('admin'))

if __name__ == '__main__':
    # Use port from environment variable (default to 5000)
    port = int(os.environ.get('PORT', 5000))
    debug_mode = os.environ.get('FLASK_ENV') == 'development'
    app.run(host='0.0.0.0', debug=debug_mode, port=port)
