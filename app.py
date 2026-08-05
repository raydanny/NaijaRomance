import os
import uuid
from datetime import datetime, timezone, timedelta
from flask import Flask, render_template, redirect, url_for, flash, request, abort, jsonify
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
from flask_wtf.csrf import CSRFProtect, generate_csrf
from werkzeug.security import generate_password_hash, check_password_hash
from PIL import Image
from dotenv import load_dotenv

load_dotenv()   # loads .env into os.environ

# ── SSL fix: use Windows certificate store (fixes Avira/proxy cert errors) ────
# Required for supabase-py and any HTTPS calls to work on Windows with AV software
try:
    import truststore
    truststore.inject_into_ssl()
except ImportError:
    pass

# ── App Configuration ──────────────────────────────────────────────────────────
app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'fallback-dev-key-change-in-production')

# Database — Supabase PostgreSQL when DATABASE_URL is set, else local SQLite
_db_url = os.environ.get('DATABASE_URL', '')
if _db_url.startswith('postgres://'):
    _db_url = _db_url.replace('postgres://', 'postgresql://', 1)
app.config['SQLALCHEMY_DATABASE_URI'] = _db_url or 'sqlite:///naijaromance.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {
    'pool_pre_ping': True,
    'pool_recycle':  300,
    'pool_size':     5,
    'max_overflow':  10,
}
app.config['UPLOAD_FOLDER'] = os.path.join('static', 'uploads')
app.config['MAX_CONTENT_LENGTH'] = 5 * 1024 * 1024  # 5 MB

ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'webp'}

db = SQLAlchemy(app)
csrf = CSRFProtect(app)
login_manager = LoginManager(app)
login_manager.login_view = 'login'
login_manager.login_message = 'Please log in to access this page.'
login_manager.login_message_category = 'info'

# ── Nigerian States & Lookup Data ──────────────────────────────────────────────
NIGERIAN_STATES = [
    'Abia','Adamawa','Akwa Ibom','Anambra','Bauchi','Bayelsa',
    'Benue','Borno','Cross River','Delta','Ebonyi','Edo',
    'Ekiti','Enugu','FCT - Abuja','Gombe','Imo','Jigawa',
    'Kaduna','Kano','Katsina','Kebbi','Kogi','Kwara',
    'Lagos','Nasarawa','Niger','Ogun','Ondo','Osun',
    'Oyo','Plateau','Rivers','Sokoto','Taraba','Yobe','Zamfara'
]
RELIGIONS         = ['Christianity','Islam','Traditional','Other','Prefer not to say']
EDUCATION         = ['Primary','Secondary / O-Level','OND / NCE','HND / B.Sc','Masters','PhD','Other']
BODY_TYPES        = ['Slim','Athletic','Average','Curvy','Plus Size','Prefer not to say']
RELATIONSHIP_GOALS= ['Serious Relationship','Marriage','Friendship','Casual Dating','Not Sure Yet']
ETHNICITIES       = ['Yoruba','Igbo','Hausa','Fulani','Ijaw','Kanuri','Ibibio',
                     'Tiv','Edo','Nupe','Igala','Efik','Urhobo','Mixed','Other']
INTERESTS_POOL    = [
    'Music','Football','Cooking','Travel','Reading','Movies','Dancing',
    'Photography','Fashion','Fitness','Tech','Agriculture','Art','Gaming',
    'Gospel','Prayer','Politics','Business','Poetry','Volleyball','Tennis',
    'Hiking','Swimming','Baking','Food','Cars','Comedy','Nollywood',
    'Afrobeats','Jazz','Entrepreneurship','Investments','Nature','Fishing',
    'Sewing','Drawing','Writing','Yoga','Cycling','Basketball','Badminton',
]

MAX_PHOTOS_PER_USER = 6

# ── Simple in-memory rate limiter ─────────────────────────────────────────────
from collections import defaultdict
import threading

_rate_lock  = threading.Lock()
_rate_store = defaultdict(list)   # key → [timestamp, ...]

def _rate_limited(key: str, limit: int, window: int) -> bool:
    """Return True if key has exceeded `limit` hits within `window` seconds."""
    now    = datetime.utcnow()
    cutoff = now - timedelta(seconds=window)
    with _rate_lock:
        hits = _rate_store[key]
        hits[:] = [t for t in hits if t > cutoff]
        if len(hits) >= limit:
            return True
        hits.append(now)
        return False

def _rate_template_kwargs(fname):
    """Supply minimum kwargs so rate-limited responses render correctly."""
    if fname == 'register':
        return {'states': NIGERIAN_STATES, 'form': {}}
    return {}

# ── Models ─────────────────────────────────────────────────────────────────────
class User(UserMixin, db.Model):
    __tablename__ = 'users'
    id            = db.Column(db.Integer, primary_key=True)
    username      = db.Column(db.String(50), unique=True, nullable=False)
    email         = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(256), nullable=False)
    created_at    = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    last_seen     = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    is_active_acc     = db.Column(db.Boolean, default=True)
    is_hidden         = db.Column(db.Boolean, default=False)   # hide from browse
    security_question = db.Column(db.String(200))
    security_answer   = db.Column(db.String(200))              # stored lowercase

    profile        = db.relationship('Profile',      back_populates='user',   uselist=False, cascade='all, delete-orphan')
    photos         = db.relationship('Photo',        back_populates='user',   cascade='all, delete-orphan')
    sent_msgs      = db.relationship('Message',      foreign_keys='Message.sender_id',   back_populates='sender',   cascade='all, delete-orphan')
    recv_msgs      = db.relationship('Message',      foreign_keys='Message.receiver_id', back_populates='receiver', cascade='all, delete-orphan')
    likes_given    = db.relationship('Like',         foreign_keys='Like.liker_id', back_populates='liker', cascade='all, delete-orphan')
    likes_received = db.relationship('Like',         foreign_keys='Like.liked_id', back_populates='liked', cascade='all, delete-orphan')
    notifications  = db.relationship('Notification', foreign_keys='Notification.recipient_id', back_populates='recipient', cascade='all, delete-orphan')
    views_received = db.relationship('ProfileView',  foreign_keys='ProfileView.viewed_id',  back_populates='viewed',  cascade='all, delete-orphan')
    views_given    = db.relationship('ProfileView',  foreign_keys='ProfileView.viewer_id',  back_populates='viewer',  cascade='all, delete-orphan')

    def set_password(self, p):   self.password_hash = generate_password_hash(p)
    def check_password(self, p): return check_password_hash(self.password_hash, p)

    def get_main_photo(self):
        """Return (folder, filename) tuple for use in templates."""
        p = Photo.query.filter_by(user_id=self.id, is_main=True).first() or \
            Photo.query.filter_by(user_id=self.id).first()
        if p:
            return p.filename   # served from static/uploads/
        return None             # caller should use static/img/default_avatar.png

    def get_photo_url(self):
        """Return the static URL segment for the main photo."""
        p = self.get_main_photo()
        if p:
            return 'uploads/' + p
        return 'img/default_avatar.png'

    def touch(self):
        self.last_seen = datetime.now(timezone.utc).replace(tzinfo=None)
        db.session.commit()

    def is_online(self):
        if not self.last_seen:
            return False
        ls = self.last_seen.replace(tzinfo=timezone.utc) if self.last_seen.tzinfo is None else self.last_seen
        return (datetime.now(timezone.utc) - ls).total_seconds() < 300

    def profile_strength(self):
        """Return (score 0-100, list of missing fields)."""
        if not self.profile:
            return 0, ['Complete your profile']
        p = self.profile
        fields = {
            'First name':          bool(p.first_name),
            'Date of birth':       bool(p.date_of_birth),
            'Gender':              bool(p.gender),
            'State':               bool(p.state),
            'About me':            bool(p.about_me and len(p.about_me) > 20),
            'Ethnicity':           bool(p.ethnicity),
            'Religion':            bool(p.religion),
            'Education':           bool(p.education),
            'Occupation':          bool(p.occupation),
            'Relationship goal':   bool(p.relationship_goal),
            'Interests':           bool(p.interests),
            'Profile photo':       Photo.query.filter_by(user_id=self.id).count() > 0,
        }
        missing = [k for k, v in fields.items() if not v]
        score   = int(100 * (len(fields) - len(missing)) / len(fields))
        return score, missing

    def unread_notif_count(self):
        return Notification.query.filter_by(recipient_id=self.id, is_read=False).count()


class Profile(db.Model):
    __tablename__ = 'profiles'
    id               = db.Column(db.Integer, primary_key=True)
    user_id          = db.Column(db.Integer, db.ForeignKey('users.id'), unique=True, nullable=False)
    first_name       = db.Column(db.String(50), nullable=False)
    last_name        = db.Column(db.String(50))
    gender           = db.Column(db.String(20))
    seeking          = db.Column(db.String(20))
    date_of_birth    = db.Column(db.Date)
    state            = db.Column(db.String(50))
    city             = db.Column(db.String(100))
    ethnicity        = db.Column(db.String(50))
    religion         = db.Column(db.String(50))
    education        = db.Column(db.String(50))
    occupation       = db.Column(db.String(100))
    body_type        = db.Column(db.String(30))
    height_cm        = db.Column(db.Integer)
    relationship_goal= db.Column(db.String(50))
    about_me         = db.Column(db.Text)
    interests        = db.Column(db.String(300))
    profile_complete = db.Column(db.Boolean, default=False)

    user = db.relationship('User', back_populates='profile')

    def age(self):
        if not self.date_of_birth: return None
        t = datetime.today().date()
        d = self.date_of_birth
        return t.year - d.year - ((t.month, t.day) < (d.month, d.day))

    def interests_list(self):
        return [i.strip() for i in self.interests.split(',') if i.strip()] if self.interests else []


class Photo(db.Model):
    __tablename__ = 'photos'
    id          = db.Column(db.Integer, primary_key=True)
    user_id     = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    filename    = db.Column(db.String(200), nullable=False)
    is_main     = db.Column(db.Boolean, default=False)
    uploaded_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    user        = db.relationship('User', back_populates='photos')


class Message(db.Model):
    __tablename__ = 'messages'
    id          = db.Column(db.Integer, primary_key=True)
    sender_id   = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    receiver_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    body        = db.Column(db.Text, nullable=False)
    is_read     = db.Column(db.Boolean, default=False)
    sent_at     = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    sender      = db.relationship('User', foreign_keys=[sender_id],   back_populates='sent_msgs')
    receiver    = db.relationship('User', foreign_keys=[receiver_id], back_populates='recv_msgs')


class Like(db.Model):
    __tablename__ = 'likes'
    id         = db.Column(db.Integer, primary_key=True)
    liker_id   = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    liked_id   = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    liker      = db.relationship('User', foreign_keys=[liker_id], back_populates='likes_given')
    liked      = db.relationship('User', foreign_keys=[liked_id],  back_populates='likes_received')
    __table_args__ = (db.UniqueConstraint('liker_id','liked_id', name='unique_like'),)


class Block(db.Model):
    __tablename__ = 'blocks'
    id         = db.Column(db.Integer, primary_key=True)
    blocker_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    blocked_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))


# ── NEW: Notifications ─────────────────────────────────────────────────────────
NOTIF_LIKE    = 'like'
NOTIF_MESSAGE = 'message'
NOTIF_MATCH   = 'match'
NOTIF_VIEW    = 'view'

class Notification(db.Model):
    __tablename__ = 'notifications'
    id           = db.Column(db.Integer, primary_key=True)
    recipient_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    actor_id     = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    notif_type   = db.Column(db.String(20), nullable=False)   # like / message / match / view
    is_read      = db.Column(db.Boolean, default=False)
    created_at   = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    recipient = db.relationship('User', foreign_keys=[recipient_id], back_populates='notifications')
    actor     = db.relationship('User', foreign_keys=[actor_id])

    def text(self):
        name = self.actor.profile.first_name if self.actor.profile else self.actor.username
        if self.notif_type == NOTIF_LIKE:    return f'{name} liked your profile ❤️'
        if self.notif_type == NOTIF_MATCH:   return f'You and {name} matched! 💚'
        if self.notif_type == NOTIF_MESSAGE: return f'{name} sent you a message 💬'
        if self.notif_type == NOTIF_VIEW:    return f'{name} viewed your profile 👀'
        if self.notif_type == 'wink':        return f'{name} winked at you 😉'
        return 'New notification'

    def link(self):
        if self.notif_type in (NOTIF_LIKE, NOTIF_MATCH, NOTIF_VIEW):
            return url_for('view_profile', username=self.actor.username)
        if self.notif_type == NOTIF_MESSAGE:
            return url_for('conversation', username=self.actor.username)
        return url_for('dashboard')


# ── NEW: Profile Views ─────────────────────────────────────────────────────────
class ProfileView(db.Model):
    __tablename__ = 'profile_views'
    id         = db.Column(db.Integer, primary_key=True)
    viewer_id  = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    viewed_id  = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    viewed_at  = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    viewer     = db.relationship('User', foreign_keys=[viewer_id], back_populates='views_given')
    viewed     = db.relationship('User', foreign_keys=[viewed_id], back_populates='views_received')


# ── Login Manager ──────────────────────────────────────────────────────────────
@login_manager.user_loader
def load_user(uid): return db.session.get(User, int(uid))

# ── Helpers ────────────────────────────────────────────────────────────────────
def allowed_file(f):
    return '.' in f and f.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def save_photo(file, user_id):
    ext   = file.filename.rsplit('.', 1)[1].lower()
    fname = f"{user_id}_{uuid.uuid4().hex}.{ext}"
    upload_dir = os.path.join(app.root_path, app.config['UPLOAD_FOLDER'])
    os.makedirs(upload_dir, exist_ok=True)
    img = Image.open(file)
    img.thumbnail((800, 800))
    img.save(os.path.join(upload_dir, fname))
    return fname

def push_notif(recipient_id, actor_id, ntype):
    """Create a notification, deduplicating within the last hour."""
    if recipient_id == actor_id:
        return
    cutoff = datetime.utcnow() - timedelta(hours=1)
    exists = Notification.query.filter_by(
        recipient_id=recipient_id, actor_id=actor_id, notif_type=ntype
    ).filter(Notification.created_at >= cutoff).first()
    if not exists:
        db.session.add(Notification(recipient_id=recipient_id, actor_id=actor_id, notif_type=ntype))

def record_view(viewer_id, viewed_id):
    """Record a profile view, max once per viewer per 30 min."""
    if viewer_id == viewed_id:
        return
    cutoff = datetime.utcnow() - timedelta(minutes=30)
    exists = ProfileView.query.filter_by(
        viewer_id=viewer_id, viewed_id=viewed_id
    ).filter(ProfileView.viewed_at >= cutoff).first()
    if not exists:
        db.session.add(ProfileView(viewer_id=viewer_id, viewed_id=viewed_id))
        push_notif(viewed_id, viewer_id, NOTIF_VIEW)

def unread_msg_count():
    if current_user.is_authenticated:
        return Message.query.filter_by(receiver_id=current_user.id, is_read=False).count()
    return 0

@app.context_processor
def inject_globals():
    notif_count = current_user.unread_notif_count() if current_user.is_authenticated else 0
    wink_count  = 0
    pending_reports = 0
    if current_user.is_authenticated:
        wink_count = Wink.query.filter_by(receiver_id=current_user.id, is_seen=False).count()
        if current_user.username in ADMIN_USERNAMES:
            pending_reports = Report.query.filter_by(status='pending').count()
    return dict(
        unread_count=unread_msg_count(),
        notif_count=notif_count,
        wink_count=wink_count,
        pending_reports=pending_reports,
        now=datetime.now(timezone.utc)
    )


# ── Jinja2 timeago filter ──────────────────────────────────────────────────────
@app.template_filter('timeago')
def timeago_filter(dt):
    if not dt:
        return 'Never'
    # Handle both naive (stored as UTC) and aware datetimes
    now = datetime.now(timezone.utc)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    diff = now - dt
    s = int(diff.total_seconds())
    if s < 60:          return 'Just now'
    if s < 3600:        return f'{s//60} min{"s" if s//60!=1 else ""} ago'
    if s < 86400:       return f'{s//3600} hr{"s" if s//3600!=1 else ""} ago'
    if s < 172800:      return 'Yesterday'
    if s < 604800:      return f'{s//86400} days ago'
    if s < 2592000:     return f'{s//604800} week{"s" if s//604800!=1 else ""} ago'
    return dt.strftime('%d %b %Y')

# ── Error Handlers ─────────────────────────────────────────────────────────────
@app.errorhandler(404)
def page_not_found(e):
    return render_template('404.html'), 404

@app.errorhandler(500)
def server_error(e):
    return render_template('500.html'), 500


# ══════════════════════════════════════════════════════════════════════════════
#  AUTH ROUTES
# ══════════════════════════════════════════════════════════════════════════════
@app.route('/')
def index():
    if current_user.is_authenticated:
        return redirect(url_for('browse'))
    stats = {'members': User.query.count(), 'states': len(NIGERIAN_STATES)}
    return render_template('index.html', stats=stats)


@app.route('/register', methods=['GET','POST'])
def register():
    if current_user.is_authenticated:
        return redirect(url_for('browse'))
    if request.method == 'POST':
        ip  = request.remote_addr or 'unknown'
        if _rate_limited(f'rl:register:{ip}', limit=8, window=300):
            flash('Too many registration attempts. Please wait 5 minutes.', 'warning')
            return render_template('register.html', states=NIGERIAN_STATES, form={}), 429
        username   = request.form.get('username','').strip().lower()
        email      = request.form.get('email','').strip().lower()
        password   = request.form.get('password','')
        password2  = request.form.get('password2','')
        first_name = request.form.get('first_name','').strip()
        gender     = request.form.get('gender','')
        seeking    = request.form.get('seeking','')
        dob_str    = request.form.get('date_of_birth','')
        state      = request.form.get('state','')

        errors = []
        if len(username) < 3:          errors.append('Username must be at least 3 characters.')
        if User.query.filter_by(username=username).first(): errors.append('Username already taken.')
        if '@' not in email:           errors.append('Valid email required.')
        if User.query.filter_by(email=email).first(): errors.append('Email already registered.')
        if len(password) < 6:          errors.append('Password must be at least 6 characters.')
        if password != password2:      errors.append('Passwords do not match.')
        if not first_name:             errors.append('First name is required.')

        # Age validation — must be 18+
        dob = None
        if not dob_str:
            errors.append('Date of birth is required.')
        else:
            try:
                dob = datetime.strptime(dob_str, '%Y-%m-%d').date()
                today = datetime.today().date()
                age   = today.year - dob.year - ((today.month, today.day) < (dob.month, dob.day))
                if age < 18:
                    errors.append('You must be at least 18 years old to join NaijaRomance.')
                elif age > 100:
                    errors.append('Please enter a valid date of birth.')
            except ValueError:
                errors.append('Invalid date of birth format.')

        if errors:
            for e in errors: flash(e, 'danger')
            return render_template('register.html', states=NIGERIAN_STATES, form=request.form)

        user = User(username=username, email=email)
        user.set_password(password)
        db.session.add(user)
        db.session.flush()

        db.session.add(Profile(user_id=user.id, first_name=first_name,
                               gender=gender, seeking=seeking,
                               date_of_birth=dob, state=state))
        db.session.commit()
        login_user(user)
        flash('Welcome to NaijaRomance! Complete your profile to attract matches.', 'success')
        return redirect(url_for('edit_profile'))

    return render_template('register.html', states=NIGERIAN_STATES, form={})


@app.route('/login', methods=['GET','POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('browse'))
    if request.method == 'POST':
        ip  = request.remote_addr or 'unknown'
        if _rate_limited(f'rl:login:{ip}', limit=10, window=300):
            flash('Too many login attempts. Please wait 5 minutes.', 'warning')
            return render_template('login.html'), 429
        ident    = request.form.get('identifier','').strip().lower()
        password = request.form.get('password','')
        remember = request.form.get('remember') == 'on'
        user = User.query.filter((User.username==ident)|(User.email==ident)).first()
        if user and user.check_password(password):
            if not user.is_active_acc:
                flash('Your account has been suspended. Please contact support.', 'danger')
                return render_template('login.html')
            login_user(user, remember=remember)
            user.touch()
            name = user.profile.first_name if user.profile else user.username
            flash(f'Welcome back, {name}!', 'success')
            return redirect(request.args.get('next') or url_for('browse'))
        flash('Invalid username/email or password.', 'danger')
    return render_template('login.html')


@app.route('/logout')
@login_required
def logout():
    logout_user()
    flash('You have been logged out.', 'info')
    return redirect(url_for('index'))


# ── Forgot Password (security-question based) ──────────────────────────────────
@app.route('/forgot-password', methods=['GET','POST'])
def forgot_password():
    if current_user.is_authenticated:
        return redirect(url_for('browse'))
    step = request.args.get('step', '1')

    if request.method == 'POST':
        step = request.form.get('step', '1')

        if step == '1':
            # Look up user by email
            email = request.form.get('email', '').strip().lower()
            user  = User.query.filter_by(email=email).first()
            if not user or not user.security_question:
                flash('No account with that email, or no security question set.', 'danger')
                return render_template('forgot_password.html', step='1')
            return render_template('forgot_password.html', step='2',
                                   email=email, question=user.security_question)

        elif step == '2':
            email  = request.form.get('email', '').strip().lower()
            answer = request.form.get('answer', '').strip().lower()
            user   = User.query.filter_by(email=email).first()
            if not user or (user.security_answer or '') != answer:
                flash('Incorrect answer. Please try again.', 'danger')
                return render_template('forgot_password.html', step='2',
                                       email=email,
                                       question=user.security_question if user else '')
            return render_template('forgot_password.html', step='3', email=email, answer=answer)

        elif step == '3':
            email   = request.form.get('email', '').strip().lower()
            answer  = request.form.get('answer', '').strip().lower()
            new_pw  = request.form.get('new_password', '')
            new_pw2 = request.form.get('new_password2', '')
            user    = User.query.filter_by(email=email).first()
            if not user or (user.security_answer or '') != answer:
                flash('Session expired. Please start over.', 'danger')
                return redirect(url_for('forgot_password'))
            if len(new_pw) < 6:
                flash('Password must be at least 6 characters.', 'danger')
                return render_template('forgot_password.html', step='3', email=email, answer=answer)
            if new_pw != new_pw2:
                flash('Passwords do not match.', 'danger')
                return render_template('forgot_password.html', step='3', email=email, answer=answer)
            user.set_password(new_pw)
            db.session.commit()
            flash('Password reset successfully! Please log in.', 'success')
            return redirect(url_for('login'))

    return render_template('forgot_password.html', step='1')


# ══════════════════════════════════════════════════════════════════════════════
#  PROFILE ROUTES
# ══════════════════════════════════════════════════════════════════════════════
@app.route('/profile/edit', methods=['GET','POST'])
@login_required
def edit_profile():
    current_user.touch()
    p = current_user.profile
    if not p:
        p = Profile(user_id=current_user.id, first_name=current_user.username)
        db.session.add(p); db.session.commit()

    if request.method == 'POST':
        p.first_name       = request.form.get('first_name','').strip()
        p.last_name        = request.form.get('last_name','').strip()
        p.gender           = request.form.get('gender','')
        p.seeking          = request.form.get('seeking','')
        p.state            = request.form.get('state','')
        p.city             = request.form.get('city','').strip()
        p.ethnicity        = request.form.get('ethnicity','')
        p.religion         = request.form.get('religion','')
        p.education        = request.form.get('education','')
        p.occupation       = request.form.get('occupation','').strip()
        p.body_type        = request.form.get('body_type','')
        p.relationship_goal= request.form.get('relationship_goal','')
        p.about_me         = request.form.get('about_me','').strip()
        p.interests        = request.form.get('interests','').strip()
        dob_str = request.form.get('date_of_birth','')
        try:   p.date_of_birth = datetime.strptime(dob_str,'%Y-%m-%d').date() if dob_str else p.date_of_birth
        except ValueError: pass
        try:   p.height_cm = int(request.form.get('height_cm',0)) or None
        except (ValueError,TypeError): p.height_cm = None

        p.profile_complete = all([p.first_name, p.gender, p.state, p.about_me, p.date_of_birth])

        if 'photo' in request.files:
            f = request.files['photo']
            if f and f.filename and allowed_file(f.filename):
                current_count = Photo.query.filter_by(user_id=current_user.id).count()
                if current_count >= MAX_PHOTOS_PER_USER:
                    flash(f'Photo limit reached ({MAX_PHOTOS_PER_USER} photos max). Delete one to upload another.', 'warning')
                else:
                    try:
                        fname    = save_photo(f, current_user.id)
                        is_first = current_count == 0
                        db.session.add(Photo(user_id=current_user.id, filename=fname, is_main=is_first))
                    except Exception as ex:
                        flash(f'Photo upload failed: {ex}', 'warning')

        db.session.commit()
        flash('Profile updated successfully!', 'success')
        return redirect(url_for('view_profile', username=current_user.username))

    score, missing = current_user.profile_strength()
    photo_count = Photo.query.filter_by(user_id=current_user.id).count()
    return render_template('edit_profile.html', profile=p,
                           states=NIGERIAN_STATES, religions=RELIGIONS,
                           education_levels=EDUCATION, body_types=BODY_TYPES,
                           relationship_goals=RELATIONSHIP_GOALS, ethnicities=ETHNICITIES,
                           interests_pool=INTERESTS_POOL,
                           strength_score=score, strength_missing=missing,
                           photo_count=photo_count, max_photos=MAX_PHOTOS_PER_USER)


@app.route('/profile/<username>')
@login_required
def view_profile(username):
    current_user.touch()
    user = User.query.filter_by(username=username).first_or_404()

    # Block check
    if Block.query.filter_by(blocker_id=user.id, blocked_id=current_user.id).first():
        abort(404)

    is_self = user.id == current_user.id
    if not is_self:
        record_view(current_user.id, user.id)
        db.session.commit()

    photos    = Photo.query.filter_by(user_id=user.id).all()
    has_liked = Like.query.filter_by(liker_id=current_user.id, liked_id=user.id).first() is not None
    mutual    = has_liked and Like.query.filter_by(liker_id=user.id, liked_id=current_user.id).first() is not None
    view_count = ProfileView.query.filter_by(viewed_id=user.id).count() if is_self else None

    has_winked = Wink.query.filter_by(sender_id=current_user.id, receiver_id=user.id).first() is not None
    score, missing = user.profile_strength()
    return render_template('profile.html', user=user, photos=photos,
                           has_liked=has_liked, mutual=mutual, is_self=is_self,
                           view_count=view_count, strength_score=score,
                           has_winked=has_winked)


@app.route('/photo/set-main/<int:photo_id>', methods=['POST'])
@login_required
def set_main_photo(photo_id):
    photo = Photo.query.get_or_404(photo_id)
    if photo.user_id != current_user.id: abort(403)
    Photo.query.filter_by(user_id=current_user.id).update({'is_main': False})
    photo.is_main = True
    db.session.commit()
    flash('Main photo updated.', 'success')
    return redirect(url_for('edit_profile'))


@app.route('/photo/delete/<int:photo_id>', methods=['POST'])
@login_required
def delete_photo(photo_id):
    photo = Photo.query.get_or_404(photo_id)
    if photo.user_id != current_user.id: abort(403)
    fp = os.path.join(app.root_path, app.config['UPLOAD_FOLDER'], photo.filename)
    if os.path.exists(fp): os.remove(fp)
    db.session.delete(photo)
    db.session.commit()
    flash('Photo deleted.', 'info')
    return redirect(url_for('edit_profile'))


# ── Who Viewed Me ──────────────────────────────────────────────────────────────
@app.route('/profile/viewers')
@login_required
def profile_viewers():
    current_user.touch()
    # Latest unique viewer per user
    sub = db.session.query(
        ProfileView.viewer_id,
        db.func.max(ProfileView.viewed_at).label('last_view')
    ).filter_by(viewed_id=current_user.id)\
     .group_by(ProfileView.viewer_id).subquery()

    viewers = db.session.query(User, sub.c.last_view)\
        .join(sub, User.id == sub.c.viewer_id)\
        .order_by(sub.c.last_view.desc()).limit(50).all()

    return render_template('viewers.html', viewers=viewers)


# ══════════════════════════════════════════════════════════════════════════════
#  BROWSE & SEARCH
# ══════════════════════════════════════════════════════════════════════════════
@app.route('/browse')
@login_required
def browse():
    current_user.touch()
    page    = request.args.get('page', 1, type=int)
    state   = request.args.get('state', '')
    gender  = request.args.get('gender', '')
    age_min = request.args.get('age_min', 18, type=int)
    age_max = request.args.get('age_max', 99, type=int)
    goal    = request.args.get('goal', '')
    sort    = request.args.get('sort', 'active')   # active | new | near

    blocked_ids = [b.blocked_id for b in Block.query.filter_by(blocker_id=current_user.id).all()]
    blocked_by  = [b.blocker_id for b in Block.query.filter_by(blocked_id=current_user.id).all()]
    exclude_ids = set(blocked_ids + blocked_by + [current_user.id])

    q = User.query.join(Profile).filter(
        User.id.notin_(exclude_ids),
        User.is_hidden == False,
        Profile.profile_complete == True
    )
    if state:  q = q.filter(Profile.state == state)
    if gender: q = q.filter(Profile.gender == gender)
    if goal:   q = q.filter(Profile.relationship_goal == goal)

    from datetime import date
    today = date.today()
    if age_max < 99:
        q = q.filter(Profile.date_of_birth >= date(today.year-age_max-1, today.month, today.day))
    if age_min > 18:
        q = q.filter(Profile.date_of_birth <= date(today.year-age_min, today.month, today.day))

    if sort == 'new':    q = q.order_by(User.created_at.desc())
    else:                q = q.order_by(User.last_seen.desc())

    # same-state boost — put current user's state first
    if sort == 'near' and current_user.profile and current_user.profile.state:
        my_state = current_user.profile.state
        from sqlalchemy import case
        q = q.order_by(case((Profile.state == my_state, 0), else_=1), User.last_seen.desc())

    users     = q.paginate(page=page, per_page=12, error_out=False)
    liked_ids = {l.liked_id for l in Like.query.filter_by(liker_id=current_user.id).all()}

    return render_template('browse.html', users=users, states=NIGERIAN_STATES,
                           relationship_goals=RELATIONSHIP_GOALS,
                           liked_ids=liked_ids,
                           filters={'state':state,'gender':gender,
                                    'age_min':age_min,'age_max':age_max,
                                    'goal':goal,'sort':sort})


@app.route('/search')
@login_required
def search():
    current_user.touch()
    q_str     = request.args.get('q','').strip()
    page      = request.args.get('page', 1, type=int)
    f_state   = request.args.get('state','')
    f_gender  = request.args.get('gender','')
    f_religion= request.args.get('religion','')
    f_ethnicity=request.args.get('ethnicity','')
    f_age_min = request.args.get('age_min', 18, type=int)
    f_age_max = request.args.get('age_max', 99, type=int)
    users     = None

    has_filters = any([q_str, f_state, f_gender, f_religion, f_ethnicity,
                       f_age_min != 18, f_age_max != 99])

    if has_filters:
        blocked_ids = [b.blocked_id for b in Block.query.filter_by(blocker_id=current_user.id).all()]
        blocked_by  = [b.blocker_id for b in Block.query.filter_by(blocked_id=current_user.id).all()]
        exclude_ids = set(blocked_ids + blocked_by + [current_user.id])

        base = User.query.join(Profile).filter(
            User.id.notin_(exclude_ids),
            User.is_hidden == False,
            Profile.profile_complete == True,
        )

        if q_str:
            pattern = f'%{q_str}%'
            base = base.filter(db.or_(
                User.username.ilike(pattern),
                Profile.first_name.ilike(pattern),
                Profile.last_name.ilike(pattern),
                Profile.state.ilike(pattern),
                Profile.city.ilike(pattern),
                Profile.occupation.ilike(pattern),
                Profile.interests.ilike(pattern),
            ))

        if f_state:    base = base.filter(Profile.state == f_state)
        if f_gender:   base = base.filter(Profile.gender == f_gender)
        if f_religion: base = base.filter(Profile.religion == f_religion)
        if f_ethnicity:base = base.filter(Profile.ethnicity == f_ethnicity)

        from datetime import date
        today = date.today()
        if f_age_max < 99:
            base = base.filter(Profile.date_of_birth >= date(today.year - f_age_max - 1, today.month, today.day))
        if f_age_min > 18:
            base = base.filter(Profile.date_of_birth <= date(today.year - f_age_min, today.month, today.day))

        users = base.order_by(User.last_seen.desc()).paginate(page=page, per_page=12, error_out=False)

    liked_ids = {l.liked_id for l in Like.query.filter_by(liker_id=current_user.id).all()}
    return render_template('search.html', users=users, q=q_str, liked_ids=liked_ids,
                           states=NIGERIAN_STATES, religions=RELIGIONS, ethnicities=ETHNICITIES,
                           filters={'state':f_state,'gender':f_gender,'religion':f_religion,
                                    'ethnicity':f_ethnicity,'age_min':f_age_min,'age_max':f_age_max})


# ══════════════════════════════════════════════════════════════════════════════
#  LIKES
# ══════════════════════════════════════════════════════════════════════════════
@app.route('/like/<int:user_id>', methods=['POST'])
@login_required
@csrf.exempt
def like_user(user_id):
    current_user.touch()
    if user_id == current_user.id:
        return jsonify({'status':'error','message':'Cannot like yourself'}), 400

    User.query.get_or_404(user_id)
    existing = Like.query.filter_by(liker_id=current_user.id, liked_id=user_id).first()

    if existing:
        db.session.delete(existing)
        db.session.commit()
        return jsonify({'status':'unliked','count': Like.query.filter_by(liked_id=user_id).count()})

    db.session.add(Like(liker_id=current_user.id, liked_id=user_id))
    push_notif(user_id, current_user.id, NOTIF_LIKE)
    mutual = Like.query.filter_by(liker_id=user_id, liked_id=current_user.id).first()
    if mutual:
        push_notif(user_id,           current_user.id, NOTIF_MATCH)
        push_notif(current_user.id,   user_id,          NOTIF_MATCH)
    db.session.commit()
    return jsonify({'status':'liked','mutual': mutual is not None,
                    'count': Like.query.filter_by(liked_id=user_id).count()})


@app.route('/likes')
@login_required
def my_likes():
    current_user.touch()
    i_liked  = User.query.join(Like, Like.liked_id==User.id).filter(Like.liker_id==current_user.id).all()
    liked_me = User.query.join(Like, Like.liker_id==User.id).filter(Like.liked_id==current_user.id).all()
    i_ids    = {u.id for u in i_liked}
    me_ids   = {u.id for u in liked_me}
    mutual   = [u for u in i_liked if u.id in me_ids]
    return render_template('likes.html', i_liked=i_liked, liked_me=liked_me, mutual_users=mutual)


# ══════════════════════════════════════════════════════════════════════════════
#  MESSAGES
# ══════════════════════════════════════════════════════════════════════════════
@app.route('/messages')
@login_required
def inbox():
    current_user.touch()
    sent  = db.session.query(Message.receiver_id).filter_by(sender_id=current_user.id)
    recv  = db.session.query(Message.sender_id).filter_by(receiver_id=current_user.id)
    pids  = {r[0] for r in sent.all()} | {r[0] for r in recv.all()}

    convs = []
    for pid in pids:
        partner = db.session.get(User, pid)
        if not partner: continue
        last = Message.query.filter(
            ((Message.sender_id==current_user.id)&(Message.receiver_id==pid))|
            ((Message.sender_id==pid)&(Message.receiver_id==current_user.id))
        ).order_by(Message.sent_at.desc()).first()
        unread = Message.query.filter_by(sender_id=pid, receiver_id=current_user.id, is_read=False).count()
        convs.append({'partner':partner,'last_msg':last,'unread':unread})

    convs.sort(key=lambda x: x['last_msg'].sent_at if x['last_msg'] else datetime.min, reverse=True)
    return render_template('inbox.html', conversations=convs)


@app.route('/messages/<username>', methods=['GET','POST'])
@login_required
def conversation(username):
    current_user.touch()
    partner = User.query.filter_by(username=username).first_or_404()
    if partner.id == current_user.id: return redirect(url_for('inbox'))

    block = Block.query.filter(
        ((Block.blocker_id==current_user.id)&(Block.blocked_id==partner.id))|
        ((Block.blocker_id==partner.id)&(Block.blocked_id==current_user.id))
    ).first()
    if block:
        flash('You cannot message this user.', 'danger')
        return redirect(url_for('inbox'))

    if request.method == 'POST':
        body = request.form.get('body','').strip()
        if body:
            db.session.add(Message(sender_id=current_user.id, receiver_id=partner.id, body=body))
            push_notif(partner.id, current_user.id, NOTIF_MESSAGE)
            db.session.commit()
        # Return JSON when requested by AJAX (X-Requested-With header or Accept: application/json)
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest' or \
           'application/json' in request.headers.get('Accept', ''):
            return jsonify({'status': 'ok'})
        return redirect(url_for('conversation', username=username))

    Message.query.filter_by(sender_id=partner.id, receiver_id=current_user.id, is_read=False)\
        .update({'is_read': True})
    db.session.commit()

    messages = Message.query.filter(
        ((Message.sender_id==current_user.id)&(Message.receiver_id==partner.id))|
        ((Message.sender_id==partner.id)&(Message.receiver_id==current_user.id))
    ).order_by(Message.sent_at.asc()).all()

    return render_template('conversation.html', partner=partner, messages=messages)


@app.route('/messages/<username>/delete', methods=['POST'])
@login_required
def delete_conversation(username):
    partner = User.query.filter_by(username=username).first_or_404()
    Message.query.filter(
        ((Message.sender_id==current_user.id)&(Message.receiver_id==partner.id))|
        ((Message.sender_id==partner.id)&(Message.receiver_id==current_user.id))
    ).delete(synchronize_session='fetch')
    db.session.commit()
    flash(f'Conversation with {partner.profile.first_name if partner.profile else partner.username} deleted.', 'info')
    return redirect(url_for('inbox'))


@app.route('/message/<int:message_id>/delete', methods=['POST'])
@login_required
@csrf.exempt
def delete_message(message_id):
    """Delete a single message (only sender can delete, within 10 minutes of sending)."""
    msg = db.session.get(Message, message_id)
    if not msg:
        return jsonify({'status': 'error', 'message': 'Message not found'}), 404
    if msg.sender_id != current_user.id:
        return jsonify({'status': 'error', 'message': 'Not authorised'}), 403
    age = (datetime.utcnow() - msg.sent_at.replace(tzinfo=None)).total_seconds()
    if age > 600:   # 10-minute window
        return jsonify({'status': 'error', 'message': 'Messages can only be deleted within 10 minutes of sending'}), 400
    # delete any reactions first
    MessageReaction.query.filter_by(message_id=message_id).delete()
    db.session.delete(msg)
    db.session.commit()
    return jsonify({'status': 'deleted', 'message_id': message_id})


# ══════════════════════════════════════════════════════════════════════════════
#  NOTIFICATIONS
# ══════════════════════════════════════════════════════════════════════════════
@app.route('/notifications')
@login_required
def notifications():
    current_user.touch()
    page = request.args.get('page', 1, type=int)
    notifs_q = Notification.query.filter_by(recipient_id=current_user.id)\
        .order_by(Notification.created_at.desc())
    # Count unread before marking read (only on page 1)
    unread_count_before = Notification.query.filter_by(
        recipient_id=current_user.id, is_read=False).count() if page == 1 else 0
    # Mark all read
    if page == 1:
        Notification.query.filter_by(recipient_id=current_user.id, is_read=False)\
            .update({'is_read': True})
        db.session.commit()
    notifs = notifs_q.paginate(page=page, per_page=20, error_out=False)
    return render_template('notifications.html', notifs=notifs,
                           unread_before=unread_count_before)


@app.route('/notifications/clear', methods=['POST'])
@login_required
def notifications_clear():
    """Delete all notifications for the current user."""
    Notification.query.filter_by(recipient_id=current_user.id).delete()
    db.session.commit()
    flash('All notifications cleared.', 'info')
    return redirect(url_for('notifications'))


@app.route('/notifications/json')
@login_required
def notifications_json():
    notifs = Notification.query.filter_by(recipient_id=current_user.id, is_read=False)\
        .order_by(Notification.created_at.desc()).limit(10).all()
    data = [{'text': n.text(), 'link': n.link(),
             'time': n.created_at.strftime('%d %b %H:%M')} for n in notifs]
    return jsonify({'count': len(data), 'items': data})


# ══════════════════════════════════════════════════════════════════════════════
#  BLOCK / UNBLOCK
# ══════════════════════════════════════════════════════════════════════════════
@app.route('/block/<int:user_id>', methods=['POST'])
@login_required
def block_user(user_id):
    if user_id == current_user.id:
        flash('Cannot block yourself.','warning')
        return redirect(url_for('browse'))
    target = db.session.get(User, user_id)
    if not Block.query.filter_by(blocker_id=current_user.id, blocked_id=user_id).first():
        db.session.add(Block(blocker_id=current_user.id, blocked_id=user_id))
        db.session.commit()
        flash('User has been blocked.', 'info')
    # Redirect back to the referring page, falling back to browse
    next_url = request.form.get('next') or request.referrer
    if next_url and next_url != request.url:
        return redirect(next_url)
    return redirect(url_for('browse'))


@app.route('/unblock/<int:user_id>', methods=['POST'])
@login_required
def unblock_user(user_id):
    Block.query.filter_by(blocker_id=current_user.id, blocked_id=user_id).delete()
    db.session.commit()
    flash('User has been unblocked.', 'info')
    return redirect(url_for('blocked_users'))


@app.route('/blocked')
@login_required
def blocked_users():
    current_user.touch()
    blocks = Block.query.filter_by(blocker_id=current_user.id).order_by(Block.created_at.desc()).all()
    blocked = []
    for b in blocks:
        u = db.session.get(User, b.blocked_id)
        if u:
            blocked.append({'user': u, 'since': b.created_at})
    return render_template('blocked.html', blocked=blocked)


# ══════════════════════════════════════════════════════════════════════════════
#  DASHBOARD & SETTINGS
# ══════════════════════════════════════════════════════════════════════════════
@app.route('/dashboard')
@login_required
def dashboard():
    current_user.touch()
    likes_recv  = Like.query.filter_by(liked_id=current_user.id).count()
    likes_given = Like.query.filter_by(liker_id=current_user.id).count()
    msg_unread  = Message.query.filter_by(receiver_id=current_user.id, is_read=False).count()
    msg_total   = Message.query.filter(
        (Message.sender_id==current_user.id)|(Message.receiver_id==current_user.id)).count()
    i_ids   = {l.liked_id for l in Like.query.filter_by(liker_id=current_user.id).all()}
    me_ids  = {l.liker_id for l in Like.query.filter_by(liked_id=current_user.id).all()}
    mutual  = len(i_ids & me_ids)
    views   = ProfileView.query.filter_by(viewed_id=current_user.id).count()
    score, missing = current_user.profile_strength()

    recent_likes = User.query.join(Like, Like.liker_id==User.id)\
        .filter(Like.liked_id==current_user.id)\
        .order_by(Like.created_at.desc()).limit(6).all()
    recent_viewers = db.session.query(User)\
        .join(ProfileView, ProfileView.viewer_id==User.id)\
        .filter(ProfileView.viewed_id==current_user.id)\
        .order_by(ProfileView.viewed_at.desc()).limit(6).all()

    # Suggested people — top compatibility matches not yet liked
    p = current_user.profile
    liked_ids = {l.liked_id for l in Like.query.filter_by(liker_id=current_user.id).all()}
    blocked_ids = {b.blocked_id for b in Block.query.filter_by(blocker_id=current_user.id).all()}
    exclude = liked_ids | blocked_ids | {current_user.id}

    suggest_q = User.query.join(Profile).filter(
        User.id.notin_(exclude),
        User.is_hidden == False,
        Profile.profile_complete == True,
    )
    if p and p.seeking and p.seeking != 'Both':
        suggest_q = suggest_q.filter(Profile.gender == p.seeking)
    if p and p.state:
        suggest_q = suggest_q.filter(Profile.state == p.state)
    suggested = suggest_q.order_by(User.last_seen.desc()).limit(8).all()
    if len(suggested) < 4 and p:
        # Fallback: any gender, any state
        suggest_q2 = User.query.join(Profile).filter(
            User.id.notin_(exclude | {u.id for u in suggested}),
            User.is_hidden == False,
            Profile.profile_complete == True,
        ).order_by(User.last_seen.desc()).limit(4 - len(suggested)).all()
        suggested.extend(suggest_q2)

    return render_template('dashboard.html',
                           likes_received=likes_recv, likes_given=likes_given,
                           messages_unread=msg_unread, total_messages=msg_total,
                           mutual_count=mutual, profile_views=views,
                           recent_likes=recent_likes, recent_viewers=recent_viewers,
                           strength_score=score, strength_missing=missing,
                           suggested_users=suggested[:4],
                           liked_ids=liked_ids)


@app.route('/settings', methods=['GET','POST'])
@login_required
def settings():
    current_user.touch()
    if request.method == 'POST':
        action = request.form.get('action')
        if action == 'change_password':
            old  = request.form.get('old_password','')
            new  = request.form.get('new_password','')
            new2 = request.form.get('new_password2','')
            if not current_user.check_password(old):  flash('Current password is incorrect.','danger')
            elif len(new) < 6:                         flash('New password must be at least 6 characters.','danger')
            elif new != new2:                          flash('New passwords do not match.','danger')
            else:
                current_user.set_password(new); db.session.commit()
                flash('Password changed successfully.','success')
        elif action == 'change_email':
            new_email = request.form.get('new_email','').strip().lower()
            pw = request.form.get('password','')
            if not current_user.check_password(pw):            flash('Password is incorrect.','danger')
            elif User.query.filter_by(email=new_email).first(): flash('Email already in use.','danger')
            else:
                current_user.email = new_email; db.session.commit()
                flash('Email updated.','success')
        elif action == 'privacy':
            current_user.is_hidden = request.form.get('is_hidden') == 'on'
            db.session.commit()
            flash('Privacy settings saved.','success')
        elif action == 'security_question':
            pw       = request.form.get('password','')
            question = request.form.get('security_question','').strip()
            answer   = request.form.get('security_answer','').strip().lower()
            if not current_user.check_password(pw):
                flash('Password is incorrect.','danger')
            elif not question or not answer:
                flash('Please provide both a question and an answer.','danger')
            else:
                current_user.security_question = question
                current_user.security_answer   = answer
                db.session.commit()
                flash('Security question saved.','success')
        elif action == 'delete_account':
            pw = request.form.get('password','')
            if not current_user.check_password(pw): flash('Password is incorrect.','danger')
            else:
                db.session.delete(current_user); db.session.commit(); logout_user()
                flash('Your account has been deleted.','info')
                return redirect(url_for('index'))
    return render_template('settings.html')


# ══════════════════════════════════════════════════════════════════════════════
#  NEW MODELS — Wink, Report
# ══════════════════════════════════════════════════════════════════════════════
NOTIF_WINK = 'wink'

class Wink(db.Model):
    __tablename__ = 'winks'
    id          = db.Column(db.Integer, primary_key=True)
    sender_id   = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    receiver_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    created_at  = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    is_seen     = db.Column(db.Boolean, default=False)
    sender      = db.relationship('User', foreign_keys=[sender_id])
    receiver    = db.relationship('User', foreign_keys=[receiver_id])
    __table_args__ = (db.UniqueConstraint('sender_id','receiver_id', name='unique_wink'),)


REPORT_REASONS = [
    'Fake profile / Scammer',
    'Harassment or threatening behaviour',
    'Inappropriate photos',
    'Underage user',
    'Spam / Advertising',
    'Hate speech or abuse',
    'Other',
]

class Report(db.Model):
    __tablename__ = 'reports'
    id          = db.Column(db.Integer, primary_key=True)
    reporter_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    reported_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    reason      = db.Column(db.String(100), nullable=False)
    details     = db.Column(db.Text)
    status      = db.Column(db.String(20), default='pending')   # pending / reviewed / dismissed
    created_at  = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    reporter    = db.relationship('User', foreign_keys=[reporter_id])
    reported    = db.relationship('User', foreign_keys=[reported_id])


# ══════════════════════════════════════════════════════════════════════════════
#  WINK ROUTES
# ══════════════════════════════════════════════════════════════════════════════
@app.route('/wink/<int:user_id>', methods=['POST'])
@login_required
@csrf.exempt
def send_wink(user_id):
    current_user.touch()
    if user_id == current_user.id:
        return jsonify({'status': 'error', 'message': 'Cannot wink at yourself'}), 400
    target = User.query.get_or_404(user_id)
    existing = Wink.query.filter_by(sender_id=current_user.id, receiver_id=user_id).first()
    if existing:
        return jsonify({'status': 'already_sent', 'message': 'Wink already sent!'})
    db.session.add(Wink(sender_id=current_user.id, receiver_id=user_id))
    push_notif(user_id, current_user.id, NOTIF_WINK)
    db.session.commit()
    name = target.profile.first_name if target.profile else target.username
    return jsonify({'status': 'sent', 'message': f'Wink sent to {name}! 😉'})


@app.route('/winks')
@login_required
def my_winks():
    current_user.touch()
    # Inner-join against User ensures winks whose sender/receiver was deleted
    # (orphaned rows that SQLite's unenforced FK left behind) are silently skipped.
    received = Wink.query.join(User, Wink.sender_id == User.id)\
                   .filter(Wink.receiver_id == current_user.id,
                           User.id != None)\
                   .order_by(Wink.created_at.desc()).all()
    sent     = Wink.query.join(User, Wink.receiver_id == User.id)\
                   .filter(Wink.sender_id == current_user.id,
                           User.id != None)\
                   .order_by(Wink.created_at.desc()).all()
    # Mark all as seen
    for w in received:
        if not w.is_seen:
            w.is_seen = True
    db.session.commit()
    return render_template('winks.html', received=received, sent=sent)


# ══════════════════════════════════════════════════════════════════════════════
#  DAILY MATCHES
# ══════════════════════════════════════════════════════════════════════════════
@app.route('/matches')
@login_required
def daily_matches():
    current_user.touch()
    p = current_user.profile
    if not p:
        flash('Complete your profile to see matches.', 'info')
        return redirect(url_for('edit_profile'))

    blocked_ids = [b.blocked_id for b in Block.query.filter_by(blocker_id=current_user.id).all()]
    blocked_by  = [b.blocker_id for b in Block.query.filter_by(blocked_id=current_user.id).all()]
    exclude_ids = set(blocked_ids + blocked_by + [current_user.id])

    liked_ids   = {l.liked_id for l in Like.query.filter_by(liker_id=current_user.id).all()}

    # Tier 1: same state + compatible seeking
    def build_query(state_match=True, strict_seek=True):
        q = User.query.join(Profile).filter(
            User.id.notin_(exclude_ids),
            User.is_hidden == False,
            Profile.profile_complete == True,
        )
        if p.seeking and p.seeking != 'Both' and strict_seek:
            q = q.filter(Profile.gender == p.seeking)
        if state_match and p.state:
            q = q.filter(Profile.state == p.state)
        return q

    tier1 = build_query(state_match=True,  strict_seek=True ).order_by(User.last_seen.desc()).limit(8).all()
    tier2 = build_query(state_match=False, strict_seek=True ).order_by(User.last_seen.desc()).limit(8).all()
    tier3 = build_query(state_match=False, strict_seek=False).order_by(User.last_seen.desc()).limit(4).all()

    # Merge, deduplicate, keep best 20
    seen_ids = set()
    matches  = []
    for u in tier1 + tier2 + tier3:
        if u.id not in seen_ids:
            seen_ids.add(u.id)
            matches.append(u)
        if len(matches) >= 20:
            break

    # Compatibility score per match
    def compat_score(u):
        score = 0
        up = u.profile
        if not up: return 0
        if p.state and up.state == p.state:                      score += 30
        if p.seeking and (p.seeking == 'Both' or up.gender == p.seeking): score += 20
        if p.religion and up.religion == p.religion:             score += 15
        if p.ethnicity and up.ethnicity == p.ethnicity:          score += 10
        if p.relationship_goal and up.relationship_goal == p.relationship_goal: score += 15
        my_i   = set(p.interests_list())
        their_i= set(up.interests_list())
        shared = len(my_i & their_i)
        score += min(shared * 5, 10)
        return score

    matches = sorted(matches, key=compat_score, reverse=True)
    match_scores = {u.id: compat_score(u) for u in matches}

    return render_template('daily_matches.html', matches=matches,
                           match_scores=match_scores, liked_ids=liked_ids)


# ══════════════════════════════════════════════════════════════════════════════
#  ONLINE MEMBERS
# ══════════════════════════════════════════════════════════════════════════════
@app.route('/online')
@login_required
def online_members():
    current_user.touch()
    cutoff = datetime.utcnow() - timedelta(minutes=5)

    blocked_ids = [b.blocked_id for b in Block.query.filter_by(blocker_id=current_user.id).all()]
    blocked_by  = [b.blocker_id for b in Block.query.filter_by(blocked_id=current_user.id).all()]
    exclude_ids = set(blocked_ids + blocked_by + [current_user.id])

    gender = request.args.get('gender', '')

    q = User.query.join(Profile).filter(
        User.id.notin_(exclude_ids),
        User.last_seen >= cutoff,
        User.is_hidden == False,
        Profile.profile_complete == True,
    )
    if gender:
        q = q.filter(Profile.gender == gender)

    online = q.order_by(User.last_seen.desc()).all()
    liked_ids = {l.liked_id for l in Like.query.filter_by(liker_id=current_user.id).all()}

    return render_template('online.html', online=online, liked_ids=liked_ids,
                           gender=gender, total=len(online))


# ══════════════════════════════════════════════════════════════════════════════
#  REPORT USER
# ══════════════════════════════════════════════════════════════════════════════
@app.route('/report/<int:user_id>', methods=['GET','POST'])
@login_required
def report_user(user_id):
    current_user.touch()
    if user_id == current_user.id:
        flash('You cannot report yourself.', 'warning')
        return redirect(url_for('browse'))
    target = User.query.get_or_404(user_id)

    if request.method == 'POST':
        reason  = request.form.get('reason','').strip()
        details = request.form.get('details','').strip()
        if not reason:
            flash('Please select a reason.', 'danger')
        else:
            # One report per pair per week
            cutoff = datetime.utcnow() - timedelta(days=7)
            existing = Report.query.filter_by(
                reporter_id=current_user.id, reported_id=user_id
            ).filter(Report.created_at >= cutoff).first()
            if existing:
                flash('You have already reported this user recently.', 'warning')
            else:
                db.session.add(Report(
                    reporter_id=current_user.id, reported_id=user_id,
                    reason=reason, details=details
                ))
                db.session.commit()
                flash('Report submitted. Our team will review it shortly.', 'success')
                return redirect(url_for('view_profile', username=target.username))

    return render_template('report.html', target=target, reasons=REPORT_REASONS)


# ══════════════════════════════════════════════════════════════════════════════
#  ADMIN PANEL
# ══════════════════════════════════════════════════════════════════════════════
ADMIN_USERNAMES = {'admin', 'naijaadmin'}   # add your username here

def admin_required(f):
    from functools import wraps
    @wraps(f)
    def decorated(*args, **kwargs):
        if not current_user.is_authenticated or current_user.username not in ADMIN_USERNAMES:
            abort(403)
        return f(*args, **kwargs)
    return decorated


@app.route('/admin')
@login_required
@admin_required
def admin_dashboard():
    cutoff_24h   = datetime.utcnow() - timedelta(hours=24)
    cutoff_7d    = datetime.utcnow() - timedelta(days=7)
    cutoff_online= datetime.utcnow() - timedelta(minutes=5)

    stats = {
        'total_users':    User.query.count(),
        'new_today':      User.query.filter(User.created_at >= cutoff_24h).count(),
        'new_week':       User.query.filter(User.created_at >= cutoff_7d).count(),
        'online_now':     User.query.filter(User.last_seen >= cutoff_online).count(),
        'total_messages': Message.query.count(),
        'total_likes':    Like.query.count(),
        'total_reports':  Report.query.count(),
        'pending_reports':Report.query.filter_by(status='pending').count(),
        'total_winks':    Wink.query.count(),
        'total_views':    ProfileView.query.count(),
        'views_today':    ProfileView.query.filter(ProfileView.viewed_at >= cutoff_24h).count(),
    }

    # State breakdown
    from sqlalchemy import func
    state_counts = db.session.query(Profile.state, func.count(Profile.id))\
        .group_by(Profile.state).order_by(func.count(Profile.id).desc()).limit(10).all()

    recent_users = User.query.order_by(User.created_at.desc()).limit(10).all()
    return render_template('admin/dashboard.html', stats=stats,
                           state_counts=state_counts, recent_users=recent_users)


@app.route('/admin/users')
@login_required
@admin_required
def admin_users():
    page    = request.args.get('page', 1, type=int)
    search  = request.args.get('q', '')
    q = User.query.join(Profile, isouter=True)
    if search:
        q = q.filter(User.username.ilike(f'%{search}%') | User.email.ilike(f'%{search}%'))
    users = q.order_by(User.created_at.desc()).paginate(page=page, per_page=20, error_out=False)
    return render_template('admin/users.html', users=users, search=search)


@app.route('/admin/users/toggle/<int:user_id>', methods=['POST'])
@login_required
@admin_required
def admin_toggle_user(user_id):
    user = User.query.get_or_404(user_id)
    user.is_active_acc = not user.is_active_acc
    db.session.commit()
    status = 'activated' if user.is_active_acc else 'deactivated'
    flash(f'User {user.username} has been {status}.', 'success')
    return redirect(url_for('admin_users'))


@app.route('/admin/users/hide/<int:user_id>', methods=['POST'])
@login_required
@admin_required
def admin_hide_user(user_id):
    user = User.query.get_or_404(user_id)
    user.is_hidden = not user.is_hidden
    db.session.commit()
    status = 'hidden from browse' if user.is_hidden else 'visible in browse'
    flash(f'User {user.username} is now {status}.', 'success')
    return redirect(url_for('admin_users'))


@app.route('/admin/users/delete/<int:user_id>', methods=['POST'])
@login_required
@admin_required
def admin_delete_user(user_id):
    user = User.query.get_or_404(user_id)
    uname = user.username
    db.session.delete(user)
    db.session.commit()
    flash(f'User {uname} permanently deleted.', 'success')
    return redirect(url_for('admin_users'))


@app.route('/admin/reports')
@login_required
@admin_required
def admin_reports():
    page    = request.args.get('page', 1, type=int)
    status  = request.args.get('status', 'pending')
    reports = Report.query.filter_by(status=status)\
                   .order_by(Report.created_at.desc())\
                   .paginate(page=page, per_page=20, error_out=False)
    return render_template('admin/reports.html', reports=reports, status=status)


@app.route('/admin/reports/action/<int:report_id>', methods=['POST'])
@login_required
@admin_required
def admin_report_action(report_id):
    report = Report.query.get_or_404(report_id)
    action = request.form.get('action')
    if action == 'reviewed':
        report.status = 'reviewed'
        flash('Report marked as reviewed.', 'success')
    elif action == 'dismissed':
        report.status = 'dismissed'
        flash('Report dismissed.', 'info')
    elif action == 'ban_user':
        report.status = 'reviewed'
        report.reported.is_active_acc = False
        flash(f'User {report.reported.username} has been banned and report closed.', 'success')
    db.session.commit()
    return redirect(url_for('admin_reports'))


# ══════════════════════════════════════════════════════════════════════════════
#  CHAT REACTIONS
# ══════════════════════════════════════════════════════════════════════════════
ALLOWED_REACTIONS = {'❤️', '😂', '😮', '👍', '🔥', '😢'}

class MessageReaction(db.Model):
    __tablename__ = 'message_reactions'
    id         = db.Column(db.Integer, primary_key=True)
    message_id = db.Column(db.Integer, db.ForeignKey('messages.id', ondelete='CASCADE'), nullable=False)
    user_id    = db.Column(db.Integer, db.ForeignKey('users.id',    ondelete='CASCADE'), nullable=False)
    emoji      = db.Column(db.String(10), nullable=False)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    __table_args__ = (db.UniqueConstraint('message_id','user_id', name='unique_reaction'),)


@app.route('/react/<int:message_id>', methods=['POST'])
@login_required
@csrf.exempt
def react_message(message_id):
    emoji = request.json.get('emoji','') if request.is_json else request.form.get('emoji','')
    if emoji not in ALLOWED_REACTIONS:
        return jsonify({'status':'error','message':'Invalid reaction'}), 400

    msg = Message.query.get_or_404(message_id)
    # Only participants can react
    if current_user.id not in (msg.sender_id, msg.receiver_id):
        abort(403)

    existing = MessageReaction.query.filter_by(message_id=message_id, user_id=current_user.id).first()
    if existing:
        if existing.emoji == emoji:          # toggle off
            db.session.delete(existing)
            db.session.commit()
            return jsonify({'status':'removed','emoji':emoji})
        else:                                # change reaction
            existing.emoji = emoji
            db.session.commit()
            return jsonify({'status':'changed','emoji':emoji})

    db.session.add(MessageReaction(message_id=message_id, user_id=current_user.id, emoji=emoji))
    db.session.commit()
    return jsonify({'status':'added','emoji':emoji})


# ══════════════════════════════════════════════════════════════════════════════
#  MESSAGES — AJAX POLL (new messages since a timestamp)
# ══════════════════════════════════════════════════════════════════════════════
@app.route('/messages/<username>/poll')
@login_required
def conversation_poll(username):
    partner  = User.query.filter_by(username=username).first_or_404()
    since_id = request.args.get('since', 0, type=int)
    msgs = Message.query.filter(
        Message.id > since_id,
        ((Message.sender_id==partner.id)&(Message.receiver_id==current_user.id))|
        ((Message.sender_id==current_user.id)&(Message.receiver_id==partner.id))
    ).order_by(Message.sent_at.asc()).all()

    # Mark incoming as read
    for m in msgs:
        if m.receiver_id == current_user.id and not m.is_read:
            m.is_read = True
    db.session.commit()

    # Highest ID of our messages that partner has read
    read_up_to = db.session.query(db.func.max(Message.id)).filter(
        Message.sender_id   == current_user.id,
        Message.receiver_id == partner.id,
        Message.is_read     == True
    ).scalar() or 0

    return jsonify({
        'messages': [{
            'id':      m.id,
            'body':    m.body,
            'mine':    m.sender_id == current_user.id,
            'time':    m.sent_at.strftime('%d %b, %H:%M'),
            'is_read': m.is_read,
        } for m in msgs],
        'read_up_to':     read_up_to,
        'partner_online': partner.is_online(),
    })


# ══════════════════════════════════════════════════════════════════════════════
#  UTILITY API ROUTES
# ══════════════════════════════════════════════════════════════════════════════
@app.route('/api/unread-counts')
@login_required
def unread_counts():
    """AJAX endpoint: returns unread message + notification counts for navbar badge polling."""
    msg_count   = Message.query.filter_by(receiver_id=current_user.id, is_read=False).count()
    notif_count = Notification.query.filter_by(recipient_id=current_user.id, is_read=False).count()
    wink_count  = Wink.query.filter_by(receiver_id=current_user.id, is_seen=False).count()
    return jsonify({'messages': msg_count, 'notifications': notif_count, 'winks': wink_count})

@app.route('/api/check-username')
def check_username():
    """AJAX username availability check used on register page."""
    username = request.args.get('username','').strip().lower()
    if len(username) < 3:
        return jsonify({'available': False, 'message': 'Too short (min 3 chars)'})
    if len(username) > 30:
        return jsonify({'available': False, 'message': 'Too long (max 30 chars)'})
    import re
    if not re.match(r'^[a-z0-9_]+$', username):
        return jsonify({'available': False, 'message': 'Only letters, numbers, underscores'})
    taken = User.query.filter_by(username=username).first() is not None
    return jsonify({
        'available': not taken,
        'message':   'Username taken' if taken else 'Available!'
    })


@app.route('/api/site-stats')
def site_stats():
    """Live stats for homepage counter animation."""
    cutoff = datetime.utcnow() - timedelta(minutes=5)
    return jsonify({
        'members': User.query.count(),
        'online':  User.query.filter(User.last_seen >= cutoff).count(),
        'likes':   Like.query.count(),
        'messages':Message.query.count(),
    })


@app.route('/api/admin/growth')
@login_required
@admin_required
def admin_growth_data():
    """Returns daily signups for the last 30 days for the admin chart."""
    from sqlalchemy import func, text
    cutoff = datetime.utcnow() - timedelta(days=30)
    # Use dialect-aware date truncation:
    # PostgreSQL: DATE_TRUNC / CAST works; SQLite: strftime fallback
    dialect = db.engine.dialect.name
    if dialect == 'postgresql':
        from sqlalchemy import cast, Date as SADate
        day_expr = cast(User.created_at, SADate).label('day')
    else:
        # SQLite fallback
        day_expr = func.strftime('%Y-%m-%d', User.created_at).label('day')
    rows = db.session.query(
        day_expr,
        func.count(User.id).label('count')
    ).filter(
        User.created_at >= cutoff
    ).group_by(day_expr)\
     .order_by(day_expr).all()
    return jsonify([{'date': str(r.day), 'count': r.count} for r in rows])


@app.route('/api/trending-states')
@login_required
def trending_states():
    """Top 8 states by recently-active member count."""
    from sqlalchemy import func
    cutoff = datetime.utcnow() - timedelta(days=7)
    rows = db.session.query(Profile.state, func.count(User.id).label('cnt'))\
        .join(User, User.id == Profile.user_id)\
        .filter(User.last_seen >= cutoff, Profile.state != None)\
        .group_by(Profile.state)\
        .order_by(func.count(User.id).desc())\
        .limit(8).all()
    return jsonify([{'state': r[0], 'count': r[1]} for r in rows])


@app.route('/api/reactions/<int:message_id>')
@login_required
def message_reactions(message_id):
    """Return reaction summary for a message."""
    from sqlalchemy import func
    rows = db.session.query(MessageReaction.emoji, func.count(MessageReaction.id))\
        .filter_by(message_id=message_id).group_by(MessageReaction.emoji).all()
    my   = MessageReaction.query.filter_by(message_id=message_id, user_id=current_user.id).first()
    return jsonify({
        'counts': {r[0]: r[1] for r in rows},
        'mine':   my.emoji if my else None
    })


@app.route('/api/online-count')
@login_required
def online_count():
    """Live count of online members for the navbar badge."""
    cutoff = datetime.utcnow() - timedelta(minutes=5)
    count  = User.query.filter(
        User.last_seen >= cutoff,
        User.is_hidden == False,
        User.id != current_user.id
    ).count()
    return jsonify({'count': count})


# ══════════════════════════════════════════════════════════════════════════════
#  TYPING INDICATOR (simple last-typed timestamp store, per conversation pair)
# ══════════════════════════════════════════════════════════════════════════════
# In-memory store: {(sender_id, receiver_id): last_typed_utc}
_typing_store: dict = {}
_TYPING_TTL = 4   # seconds before "typing…" clears

@app.route('/api/typing/<username>', methods=['POST'])
@login_required
@csrf.exempt
def typing_ping(username):
    """Called by the JS client every ~2 s while the user is typing."""
    partner = User.query.filter_by(username=username).first_or_404()
    _typing_store[(current_user.id, partner.id)] = datetime.utcnow()
    return jsonify({'ok': True})


@app.route('/api/typing/<username>')
@login_required
def typing_status(username):
    """Returns whether the partner is currently typing."""
    partner = User.query.filter_by(username=username).first_or_404()
    last = _typing_store.get((partner.id, current_user.id))
    is_typing = last is not None and (datetime.utcnow() - last).total_seconds() < _TYPING_TTL
    return jsonify({'typing': is_typing})


# ══════════════════════════════════════════════════════════════════════════════
#  STATIC INFO PAGES
# ══════════════════════════════════════════════════════════════════════════════
@app.route('/terms')
def terms():
    return render_template('terms.html')

@app.route('/privacy')
def privacy():
    return render_template('privacy.html')

@app.route('/contact')
def contact():
    return render_template('contact.html')


# ══════════════════════════════════════════════════════════════════════════════
#  ENTRY POINT
# ══════════════════════════════════════════════════════════════════════════════
if __name__ == '__main__':
    with app.app_context():
        db.create_all()
        os.makedirs(os.path.join(app.root_path, 'static', 'uploads'), exist_ok=True)
    app.run(debug=True, host='0.0.0.0', port=5000)
