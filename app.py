import os
from datetime import datetime
from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, session
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
app.config['SECRET_KEY'] = 'super-secret-professional-key'
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///shared_diary.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)

# --- DATABASE MODELS ---

# Association table for shared diaries (Many-to-Many or Pair-to-One)
class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(150), nullable=False)
    email = db.Column(db.String(150), unique=True, nullable=False)
    password = db.Column(db.String(256), nullable=False)
    diary_id = db.Column(db.Integer, db.ForeignKey('diary.id'), nullable=True)

class Diary(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(50), unique=True, nullable=False) # Unique code to share
    users = db.relationship('User', backref='diary', lazy=True)
    entries = db.relationship('Entry', backref='diary', lazy=True)

class Entry(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    content = db.Column(db.Text, nullable=False)
    mood = db.Column(db.String(10), nullable=False)
    date_str = db.Column(db.String(10), nullable=False) # Format: YYYY-MM-DD
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    author_name = db.Column(db.String(150), nullable=False)
    diary_id = db.Column(db.Integer, db.ForeignKey('diary.id'), nullable=False)

# --- ROUTES ---

@app.route('/')
def index():
    if 'user_id' in session:
        return redirect(url_for('dashboard'))
    return redirect(url_for('login'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form.get('email')
        password = request.form.get('password')
        user = User.query.filter_by(email=email).first()
        
        if user and check_password_hash(user.password, password):
            session['user_id'] = user.id
            session['user_name'] = user.name
            return redirect(url_for('dashboard'))
        flash('Invalid email or password.', 'error')
    return render_template('login.html')

@app.route('/register', methods=['POST'])
def register():
    name = request.form.get('name')
    email = request.form.get('email')
    password = request.form.get('password')
    
    existing_user = User.query.filter_by(email=email).first()
    if existing_user:
        flash('Email already registered.', 'error')
        return redirect(url_for('login'))
        
    hashed_password = generate_password_hash(password, method='scrypt')
    new_user = User(name=name, email=email, password=hashed_password)
    db.session.add(new_user)
    db.session.commit()
    
    session['user_id'] = new_user.id
    session['user_name'] = new_user.name
    return redirect(url_for('dashboard'))

@app.route('/dashboard')
def dashboard():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    user = db.session.get(User, session['user_id'])
    if not user.diary_id:
        return redirect(url_for('manage_diary'))
        
    return render_template('dashboard.html', user=user, diary_code=user.diary.code)

@app.route('/manage-diary', methods=['GET', 'POST'])
def manage_diary():
    if 'user_id' not in session:
        return redirect(url_for('login'))
        
    user = db.session.get(User, session['user_id'])
    
    if request.method == 'POST':
        action = request.form.get('action')
        if action == 'create':
            import uuid
            unique_code = str(uuid.uuid4())[:8].upper()
            new_diary = Diary(code=unique_code)
            db.session.add(new_diary)
            db.session.commit()
            user.diary_id = new_diary.id
            db.session.commit()
            return redirect(url_for('dashboard'))
            
        elif action == 'join':
            code = request.form.get('diary_code').strip().upper()
            diary = Diary.query.filter_by(code=code).first()
            if diary:
                user.diary_id = diary.id
                db.session.commit()
                return redirect(url_for('dashboard'))
            flash('Invalid Diary Code.', 'error')
            
    return render_template('invite.html', user=user)

# --- API ENDPOINTS FOR CALENDAR & ENTRIES ---

@app.route('/api/entries', methods=['GET'])
def get_entries():
    if 'user_id' not in session:
        return jsonify({'error': 'Unauthorized'}), 401
    user = db.session.get(User, session['user_id'])
    if not user.diary_id:
        return jsonify([])
        
    entries = Entry.query.filter_by(diary_id=user.diary_id).all()
    return jsonify([{
        'id': e.id,
        'title': e.title,
        'content': e.content,
        'mood': e.mood,
        'date_str': e.date_str,
        'author': e.author_name
    } for e in entries])

@app.route('/api/entries', methods=['POST'])
def add_entry():
    if 'user_id' not in session:
        return jsonify({'error': 'Unauthorized'}), 401
    user = db.session.get(User, session['user_id'])
    
    data = request.json
    new_entry = Entry(
        title=data.get('title'),
        content=data.get('content'),
        mood=data.get('mood'),
        date_str=data.get('date_str'), # Expecting 'YYYY-MM-DD'
        author_name=user.name,
        diary_id=user.diary_id
    )
    db.session.add(new_entry)
    db.session.commit()
    return jsonify({'success': True})

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

if __name__ == '__main__':
    with app.app_context():
        db.create_all() # Generates SQLite database file automatically
    app.run(debug=True)
